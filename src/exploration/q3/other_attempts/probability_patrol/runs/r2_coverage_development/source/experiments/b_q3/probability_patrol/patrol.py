"""两点起搜、清除位置共享补测的独立 Q3 原型。

R1 只用几何规则；概率初始设计在离线模块完成。不使用旧 W/G 评分。
策略输入只有公开 InformationState，禁止传入 LocalEnvironment。
"""
import math

from coverage_state import CoverageInformationState
import geometry as g


DEFAULT_CONFIG = {
    "name": "r1_plain",
    "initial_points": [[-750.0, 0.0], [750.0, 0.0]],
    "try_radius_m": 30.0,
    "local_action_limit": 16,
    "local_offset_fraction": 0.5,
    "local_offset_min_m": 30.0,
    "local_offset_max_m": 300.0,
    "shared_scan_gap_m": 0.0,
    "route_mode": "nearest",
}


def major_axis(poly):
    if len(poly) < 2:
        return (1.0, 0.0)
    a, b = max(((a, b) for i, a in enumerate(poly) for b in poly[i+1:]),
               key=lambda pair: g.distance(*pair))
    d = g.sub(b, a)
    norm = math.hypot(*d)
    return g.mul(d, 1 / norm) if norm > 1e-9 else (1.0, 0.0)


class PatrolPolicy:
    def __init__(self, config=None):
        self.config = dict(DEFAULT_CONFIG)
        self.config.update(config or {})
        if len(self.config["initial_points"]) != 2:
            raise ValueError("本轮初始巡查固定为两个自由点")
        self.initial_points = [tuple(map(float, p)) for p in self.config["initial_points"]]
        if g.distance(*self.initial_points) < 1e-3:
            raise ValueError("初始测点不能相同")
        self.initial_index = 0
        self.initial_finish_s = None
        self.initial_statistics = None
        self.phase = "initial"
        self.station = None
        self.station_channels = []
        self.station_reason = None
        self.stations = []
        self.target = None
        self.local_counts = {}
        self.tried_centers = set()
        self.seen_cleared = set()
        self.last_reason = None
        self.decision_data = {}

    def metadata(self):
        return {"config": self.config, "phase": self.phase,
                "initial_finish_s": self.initial_finish_s,
                "initial_statistics": self.initial_statistics,
                "stations": len(self.stations), "target": self.target,
                "reason": self.last_reason, **self.decision_data}

    def action(self, kind, q, channel, reason, **extra):
        self.last_reason = reason
        return {"kind": kind, "position": tuple(q), "channel": int(channel),
                "reason": reason, "phase": self.phase, **extra}

    def start_station(self, state, q, reason, priority=None, initial=False):
        self.station, self.station_reason = tuple(q), reason
        self.stations.append(tuple(q))
        active = []
        for j, c in state.channels.items():
            if c.status in ("cleared", "absent") or tuple(q) in c.measured:
                continue
            if c.status == "found" and not initial:
                center, radius = c.circle()
                if radius <= 20 or g.distance(center, q) - radius > 1500:
                    continue
            active.append(j)
        # 同一点共享移动；先处理当前服务目标，再保持当前频道，余下按号扫描。
        active.sort(key=lambda j: (j != priority, j != state.measuring_channel, j))
        self.station_channels = active

    def station_action(self, state):
        while self.station_channels:
            j = self.station_channels.pop(0)
            c = state.channels[j]
            if c.status in ("cleared", "absent") or self.station in c.measured:
                continue
            if self.phase != "initial" and c.status == "found" and c.circle()[1] <= 20:
                continue
            return self.action("measure", self.station, j, self.station_reason)
        self.station = None
        return None

    def initial_snapshot(self, state):
        found = [c for c in state.channels.values() if c.status == "found"]
        return {"found": len(found),
                "two_bearings": sum(sum(r == "direction" for _, r, _ in c.observations) >= 2 for c in found),
                "radius_le20": sum(c.circle()[1] <= 20 for c in found),
                "radius_le60": sum(c.circle()[1] <= 60 for c in found),
                "radii_m": {str(c.channel): c.circle()[1] for c in found}}

    def choose_target(self, state, found):
        return min(found, key=lambda c: (g.distance(state.position, c.circle()[0]), c.channel)).channel

    def local_point(self, state, c):
        center, radius = c.circle()
        axis = major_axis(c.support())
        normal = (-axis[1], axis[0])
        offset = min(self.config["local_offset_max_m"], max(
            self.config["local_offset_min_m"], radius * self.config["local_offset_fraction"]))
        candidates = [g.add(center, g.mul(normal, sign * offset)) for sign in (-1, 1)]
        candidates.sort(key=lambda q: (g.distance(state.position, q), q))
        for q in candidates:
            if all(g.distance(q, p) > 1e-3 for p in c.measured):
                return q
        # 只处理数值对称/重复，不把原地重测当成新信息。
        return g.add(candidates[0], g.mul(axis, max(5.0, radius / 4)))

    def choose(self, state):
        self.decision_data = {}
        if state.complete:
            raise RuntimeError("完成后不得再请求动作")

        # 初始阶段完整做两轮；不存在隐含的原点扫描。
        while self.initial_finish_s is None:
            if self.station is not None:
                action = self.station_action(state)
                if action:
                    return action
            if self.initial_index < 2:
                self.start_station(state, self.initial_points[self.initial_index],
                                   f"initial_{self.initial_index + 1}", initial=True)
                self.initial_index += 1
                continue
            self.initial_finish_s = state.virtual_time_s
            self.initial_statistics = self.initial_snapshot(state)
            self.phase = "service"

        # 在当前位置已经可以保守保证清除的源立即处理，不另行移动。
        for c in state.channels.values():
            if c.status == "found" and all(g.distance(state.position, p) <= 20 - 1e-6 for p in c.support()):
                return self.action("clear", state.position, c.channel, "certain_here")

        cleared = {j for j, c in state.channels.items() if c.status == "cleared"}
        newly_cleared = cleared - self.seen_cleared
        self.seen_cleared = cleared
        if self.station is not None:
            action = self.station_action(state)
            if action:
                return action
        if newly_cleared:
            self.target = None
            gap = min((g.distance(state.position, p) for p in self.stations), default=math.inf)
            if gap >= self.config["shared_scan_gap_m"] - 1e-6:
                self.start_station(state, state.position, "clearance_shared_scan")
                action = self.station_action(state)
                if action:
                    return action

        found = [c for c in state.channels.values() if c.status == "found"]
        if found:
            self.phase = "service"
            if self.target is None or state.channels[self.target].status != "found":
                self.target = self.choose_target(state, found)
            c = state.channels[self.target]
            center, radius = c.circle()
            if radius <= 20 - 1e-6:
                return self.action("clear", center, c.channel, "certain_center")
            if radius <= self.config["try_radius_m"] and c.channel not in self.tried_centers:
                self.tried_centers.add(c.channel)
                return self.action("clear", center, c.channel, "single_center_try")

            # 先利用已到达位置的视角，不能只向估计中心反复前进。
            if state.position not in c.measured:
                self.local_counts[c.channel] = self.local_counts.get(c.channel, 0) + 1
                return self.action("measure", state.position, c.channel, "current_view")
            count = self.local_counts.get(c.channel, 0)
            self.local_counts[c.channel] = count + 1
            if count >= self.config["local_action_limit"]:
                cells = c.possible_cells()
                if not cells:
                    raise AssertionError("已发现源的保守可行格为空")
                q = min(cells, key=lambda cell: g.distance(state.position, cell["position"]))["position"]
                return self.action("clear", q, c.channel, "finite_cell_clear")
            q = self.local_point(state, c)
            self.start_station(state, q, "transverse_shared_scan", priority=c.channel)
            action = self.station_action(state)
            if action:
                return action
            raise AssertionError("横向补测没有合法目标")

        self.phase = "completion"
        candidates = state.discovery_points(limit=24)
        candidates = [q for q in candidates if any(c.status == "unknown" and q not in c.measured
                                                   for c in state.channels.values())]
        if not candidates:
            raise AssertionError("未完成但查漏没有候选；不得概率终止")
        q = min(candidates, key=lambda p: (g.distance(state.position, p), p))
        self.start_station(state, q, "unresolved_region_scan")
        action = self.station_action(state)
        if action:
            return action
        raise AssertionError("查漏没有合法检测")

