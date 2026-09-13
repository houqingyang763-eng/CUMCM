"""Q4 B0：固定25点扫描、中心开放路线、单源定向补测与有限后备。"""
from dataclasses import asdict, dataclass
import math
from types import SimpleNamespace

import common  # noqa: F401；只设置旧核心模块路径，不导入旧运行器或 guard。
from common import Q4_SYMMETRIC25_ANCHORS
from route_dp import SCALE, distance_floor, shortest_open_path
from policy import BasePolicy
from q4 import Q4_ANCHORS, Q4Config, Q4DirectionalPolicy, g
from q4_joint_state import Q4JointCoverageInformationState


@dataclass(frozen=True)
class BaselineConfig(Q4Config):
    scan_radius_m: float = 20.0 - 1e-5
    try_radius_m: float = 30.0
    local_measurement_limit: int = 8


def fixed_discovery_route():
    """固定原点的最近邻加首次改进2-opt；不使用场景或反馈。"""
    remaining = [tuple(q) for q in Q4_SYMMETRIC25_ANCHORS if math.hypot(*q) > 1e-8]
    route = [(0.0, 0.0)]
    while remaining:
        index = min(range(len(remaining)),
                    key=lambda i: (g.distance(route[-1], remaining[i]), i))
        route.append(remaining.pop(index))

    def length(points):
        return sum(g.distance(a, b) for a, b in zip(points, points[1:]))

    changed = True
    while changed:
        changed = False
        before = length(route)
        for i in range(1, len(route) - 1):
            for j in range(i + 1, len(route)):
                candidate = route[:i] + list(reversed(route[i:j + 1])) + route[j + 1:]
                if length(candidate) < before - 1e-7:
                    route, changed = candidate, True
                    break
            if changed:
                break
    return tuple(route)


def center_route(start, channels, centers):
    """仅对公开估计中心作开放路线DP，绝不调用oracle.solve/真值接口。"""
    weights0 = [distance_floor(start, p) for p in centers]
    edges = [[distance_floor(p, q) for q in centers] for p in centers]
    length, order = shortest_open_path(weights0, edges)
    return [channels[i] for i in order], length / SCALE


class BaselinePolicy:
    """规则见 BASELINE.md；首次实验前冻结，安全状态与效率启发分离。"""

    def __init__(self, config=None):
        if config is None:
            config = BaselineConfig()
        elif isinstance(config, dict):
            config = BaselineConfig(**config)
        elif not isinstance(config, BaselineConfig):
            config = BaselineConfig(**asdict(config))
        if config.local_measurement_limit < 0 or not isinstance(config.local_measurement_limit, int):
            raise ValueError("局部补测上限必须为非负整数")
        if not 0 < config.scan_radius_m < 20:
            raise ValueError("停止扫描半径必须严格小于20米")
        if not config.scan_radius_m <= config.try_radius_m <= 100:
            raise ValueError("一次中心试清半径参数无效")
        self.config = config
        self.points = fixed_discovery_route()
        self.scan_cursor = 0
        self.phase = "scan"
        self.phase_change = None
        self.routes = []
        self.target = None
        self.target_measurements = 0
        self.center_attempted = set()
        self.fallback_targets = set()
        self.fallback_started = False
        self.local = Q4DirectionalPolicy(config)

    action = staticmethod(BasePolicy.action)

    @property
    def utility_calls(self):
        return self.local.utility_calls

    @staticmethod
    def _view(state, channel):
        return SimpleNamespace(channels={channel.channel: channel}, position=state.position,
                               measuring_channel=state.measuring_channel,
                               virtual_time_s=state.virtual_time_s, actions=state.actions,
                               complete=False)

    def _start_service(self, state):
        if any(c.status == "unknown" for c in state.channels.values()):
            raise AssertionError("B0固定25点扫描结束但未知频道覆盖证明未闭合")
        self.phase = "service"
        found = [c for c in state.channels.values() if c.status == "found"]
        self.phase_change = dict(
            time_s=state.virtual_time_s, position=state.position,
            radii_m={c.channel: c.circle()[1] for c in found},
            centers={c.channel: c.circle()[0] for c in found},
            direction_counts={c.channel: sum(o[1] == "direction" for o in c.observations)
                              for c in found})

    def _select_target(self, state):
        channels = [j for j, c in state.channels.items() if c.status == "found"]
        centers = [state.channels[j].circle()[0] for j in channels]
        if not channels:
            raise AssertionError("B0未完成但不存在可处理目标")
        order, length = center_route(state.position, channels, centers)
        self.routes.append(dict(start=state.position, channels=channels, centers=centers,
                                order=order, proxy_length_m=length))
        self.target = order[0]
        self.target_measurements = 0

    def _measure_candidate(self, view, c):
        """复用既有单源定向收益，不做完整续行、多目标或多圆试算。"""
        self.local._prepare(view)
        center, _ = c.circle()
        before = self.local._features[c.channel][0]
        cells = c.possible_cells()
        first = min(cells, key=lambda cell: (cell["index"][0],
                    cell["index"][1] if cell["index"][0] == 0 else -cell["index"][1]))
        direct_cost = g.distance(view.position, first["position"]) / 5 + before
        discovery_points = set(Q4_ANCHORS) | set(g.ANCHORS)
        plans = []
        for q in self.local.candidate_positions(view):
            if q in c.measured or q in discovery_points:
                continue
            gain = self.local.utility(c, q, g.coverage_mask(q))
            if gain < self.config.min_work_gain_s:
                continue
            cost = (g.distance(view.position, q) / 5 + 5
                    + int(c.channel != view.measuring_channel)
                    + g.distance(q, center) / 5 + max(5.0, before - gain))
            plans.append((cost, tuple(q), gain))
        if not plans:
            return None
        cost, q, gain = min(plans)
        if cost >= direct_cost - 1e-8:
            return None
        return self.action("measure", q, c.channel, "b0_local_directional_measure",
                           estimated_completion_s=cost, estimated_work_saved_s=gain,
                           direct_strip_proxy_s=direct_cost)

    def choose(self, state):
        if state.complete:
            return None
        if self.phase == "scan":
            while self.scan_cursor < len(self.points) * 20:
                index, offset = divmod(self.scan_cursor, 20)
                self.scan_cursor += 1
                j, q = offset + 1, self.points[index]
                c = state.channels[j]
                if c.status in ("cleared", "absent") or q in c.measured:
                    continue
                if c.status == "found" and c.circle()[1] <= self.config.scan_radius_m:
                    continue
                return self.action("measure", q, j, "b0_fixed_scan", phase="scan", anchor_index=index)
            self._start_service(state)
        if self.target is None or state.channels[self.target].status == "cleared":
            self._select_target(state)
        c = state.channels[self.target]
        center, radius = c.circle()
        view = self._view(state, c)
        if c.near_position is not None:
            action = self.action("clear", c.near_position, c.channel, "b0_near_clear")
        elif radius <= 20 - 1e-5:
            action = self.action("clear", center, c.channel, "b0_certified_clear",
                                 enclosure_radius_m=radius)
        elif (radius <= self.config.try_radius_m and c.channel not in self.center_attempted
              and c.compatible(center)):
            self.center_attempted.add(c.channel)
            action = self.action("clear", center, c.channel, "b0_small_region_center_try")
        else:
            action = None
            if c.channel not in self.fallback_targets and self.target_measurements < self.config.local_measurement_limit:
                action = self._measure_candidate(view, c)
            if action is None:
                self.fallback_targets.add(c.channel)
                self.fallback_started = True
                action = BasePolicy.fallback(self.local, view)
                action["reason"] = "b0_strip_" + action["reason"]
            else:
                self.target_measurements += 1
        return dict(action, phase="service", route_target=self.target,
                    region_radius_m=radius, local_measurements=self.target_measurements)

    def metadata(self):
        return dict(config=asdict(self.config), fixed_points=self.points,
                    phase_change=self.phase_change, routes=self.routes,
                    center_attempted=sorted(self.center_attempted),
                    fallback_targets=sorted(self.fallback_targets))


def make_state():
    return Q4JointCoverageInformationState()
