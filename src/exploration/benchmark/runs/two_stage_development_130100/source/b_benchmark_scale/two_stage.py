"""固定扫描 -> 根据估计位置规划开放路径 -> 局部补测/试清。仅Q3。"""
import math
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
for folder in ('b_adaptive_q3', 'b_overnight', 'b_oracle_q3'):
    sys.path.insert(0, str(ROOT / 'experiments' / folder))
import geometry as g
from oracle import distance_floor, shortest_open_path, SCALE
from task_cost import CompletionCostPolicy, CompletionCostConfig


@dataclass(frozen=True)
class TwoStageConfig:
    point_count: int = 7
    scan_radius_m: float = 60.0
    try_radius_m: float = 30.0
    local_action_limit: int = 24


CONFIGS = {
    'scan7_r60': TwoStageConfig(7, 60),
    'scan13_r60': TwoStageConfig(13, 60),
    'scan19_r60': TwoStageConfig(19, 60),
    'scan7_r30': TwoStageConfig(7, 30),
}


def fixed_points(n):
    points = list(g.ANCHORS)
    if n == 13:
        points += [g.mul(g.unit(30 + 60*k), 1600) for k in range(6)]
    elif n == 19:
        points += [g.mul(g.unit(15 + 30*k), 1700) for k in range(12)]
    elif n != 7:
        raise ValueError('只支持预先定义的7/13/19点')
    return points


def fixed_route(n):
    """只依赖点集，贪心加2-opt确定巡查次序；不声称点集/巡查路线最优。"""
    remaining = fixed_points(n)[1:]
    route = [(0., 0.)]
    while remaining:
        nxt = min(range(len(remaining)), key=lambda i: (g.distance(route[-1], remaining[i]), i))
        route.append(remaining.pop(nxt))
    def length(xs):
        return sum(g.distance(a, b) for a, b in zip(xs, xs[1:]))
    improved = True
    while improved:
        improved = False
        old = length(route)
        for i in range(1, len(route)-1):
            for j in range(i+1, len(route)):
                candidate = route[:i] + list(reversed(route[i:j+1])) + route[j+1:]
                if length(candidate) < old - 1e-7:
                    route, improved = candidate, True
                    break
            if improved:
                break
    return route


def route_order(start, channels, points):
    """给定当前估计中心的开放路径DP，整数距离误差不超过N微米。"""
    weights0 = [distance_floor(start, p) for p in points]
    edges = [[distance_floor(p, q) for q in points] for p in points]
    length, order = shortest_open_path(weights0, edges)
    return [channels[i] for i in order], length/SCALE


class TwoStagePolicy:
    def __init__(self, config):
        self.config = config
        self.points = fixed_route(config.point_count)
        self.scan_cursor = 0
        self.phase = 'scan'
        self.phase_change = None
        self.routes = []
        self.target = None
        self.local = None
        self.target_actions = 0
        self.center_attempted = set()
        self.fallback_targets = set()

    @staticmethod
    def action(kind, point, channel, reason, **extra):
        return dict(kind=kind, position=tuple(point), channel=channel, reason=reason, **extra)

    def choose(self, state):
        if state.complete:
            return None
        if self.phase == 'scan':
            while self.scan_cursor < len(self.points)*20:
                index, offset = divmod(self.scan_cursor, 20)
                self.scan_cursor += 1
                channel, point = offset+1, self.points[index]
                c = state.channels[channel]
                if c.status in ('cleared', 'absent'):
                    continue
                if c.status == 'found' and c.circle()[1] <= self.config.scan_radius_m:
                    continue
                return self.action('measure', point, channel, 'fixed_scan', phase='scan', anchor_index=index)
            if any(c.status == 'unknown' for c in state.channels.values()):
                raise AssertionError('七点发现证据未完成')
            self.phase = 'service'
            found = [c for c in state.channels.values() if c.status == 'found']
            self.phase_change = {
                'time_s': state.virtual_time_s, 'position': state.position,
                'radii_m': {c.channel: c.circle()[1] for c in found},
                'centers': {c.channel: c.circle()[0] for c in found},
                'direction_counts': {c.channel: sum(o[1]=='direction' for o in c.observations) for c in found},
            }
        if self.target is None or state.channels[self.target].status == 'cleared':
            channels = [j for j,c in state.channels.items() if c.status == 'found']
            points = [state.channels[j].circle()[0] for j in channels]
            order, length = route_order(state.position, channels, points)
            self.routes.append(dict(start=state.position, channels=channels, centers=points,
                                    order=order, proxy_length_m=length))
            self.target = order[0]
            self.target_actions = 0
            self.local = CompletionCostPolicy(CompletionCostConfig(
                adaptive_virtual_budget_s=1e9, adaptive_action_limit=1000000))
        c = state.channels[self.target]
        center, radius = c.circle()
        self.target_actions += 1
        if radius <= self.config.try_radius_m and radius > 20-1e-5 and c.channel not in self.center_attempted:
            self.center_attempted.add(c.channel)
            if c.compatible(center):
                return self.action('clear', center, c.channel, 'small_region_center_try',
                                   phase='service', region_radius_m=radius)
        # 单目标视图不包含真值，只限制局部决策不抢占其他目标。
        view = SimpleNamespace(channels={c.channel:c}, position=state.position,
                               measuring_channel=state.measuring_channel,
                               virtual_time_s=state.virtual_time_s, actions=state.actions, complete=False)
        if self.target_actions > self.config.local_action_limit:
            self.fallback_targets.add(c.channel)
            self.local.fallback_started = True
        action = self.local.choose(view)
        return dict(action, phase='service', route_target=self.target, region_radius_m=radius)

    def metadata(self):
        return dict(config=asdict(self.config), fixed_points=self.points, phase_change=self.phase_change,
                    routes=self.routes, center_attempted=sorted(self.center_attempted),
                    fallback_targets=sorted(self.fallback_targets))
