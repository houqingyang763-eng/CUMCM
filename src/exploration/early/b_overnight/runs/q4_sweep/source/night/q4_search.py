"""Q4 动态搜索：用尚未排除的位置与发射角区间评价扫描工作，单位秒。"""
from dataclasses import dataclass
from functools import lru_cache
import math

from q4 import Q4_ANCHORS, Q4Config, Q4DirectionalPolicy, _arc, _intersection, _subtract
from q4_coverage import (Q4CoverageInformationState, q4_coverage_certificate,
                         _corners, _strictly_inside)
import geometry as g


# 区域内部与边界共同作为确定性的数值求积节点，不是概率后验或停止证据。
INTERIOR_SITES = tuple(g.GRID)
BOUNDARY_SITES = tuple(g.mul(g.unit(15 * i), 1800.0) for i in range(24))
SITES = tuple((p, 0.85 / len(INTERIOR_SITES)) for p in INTERIOR_SITES) + tuple(
    (p, 0.15 / len(BOUNDARY_SITES)) for p in BOUNDARY_SITES)


@dataclass(frozen=True)
class Q4SearchConfig(Q4Config):
    # 每个未知频道完成37点参照检测的观测费用标尺，不含共享路程。
    search_work_s: float = 6.0 * len(Q4_ANCHORS)
    search_candidate_limit: int = 16
    search_probe_radius_m: float = 850.0


def negative_history(channel):
    return tuple(sorted(set(tuple(q) for q, result, _ in channel.observations if result == "no_signal")))


@lru_cache(maxsize=256)
def orientation_rows(negatives):
    """位置给定后，无信号排除距离1000m内测点对应的发射半圆。"""
    rows = []
    for p, weight in SITES:
        intervals = [(0.0, 360.0)]
        for q in negatives:
            if g.distance(p, q) < 1000 - 1e-5:
                theta = math.degrees(math.atan2(q[1] - p[1], q[0] - p[0])) % 360
                intervals = _subtract(intervals, _arc(theta))
                if not intervals:
                    break
        length = sum(b - a for a, b in intervals)
        if length > 1e-8:
            rows.append((p, weight, tuple(intervals), length))
    return tuple(rows)


@lru_cache(maxsize=32768)
def oriented_gain(negatives, q):
    """一次阴性反馈可删去的位置-方向工作比例，仅用于策略评分。"""
    value = 0.0
    for p, weight, intervals, length in orientation_rows(negatives):
        if g.distance(p, q) >= 1000 - 1e-5:
            continue
        theta = math.degrees(math.atan2(q[1] - p[1], q[0] - p[0])) % 360
        removed = sum(b - a for a, b in _intersection(intervals, _arc(theta)))
        value += weight * removed / 360.0
    return value


def residual_work_fraction(negatives):
    return sum(weight * length / 360.0 for p, weight, intervals, length in orientation_rows(negatives))


def interval_direction(intervals, fallback):
    """残余角区间的圆周均值；跨越0度时仍指向正确角隙。"""
    x = sum(math.sin(math.radians(b)) - math.sin(math.radians(a)) for a, b in intervals)
    y = sum(math.cos(math.radians(a)) - math.cos(math.radians(b)) for a, b in intervals)
    return math.atan2(y, x) if math.hypot(x, y) > 1e-9 else fallback


class Q4SearchPolicy(Q4DirectionalPolicy):
    """未知频道采用方向缺口收益；已发现频道仍用冻结的定位/清除策略。"""
    def __init__(self, config=None, reference_only=False):
        super().__init__(config or Q4SearchConfig(), reference_only)
        self._negative_keys = {}

    def _prepare(self, state):
        super()._prepare(state)
        for j, c in state.channels.items():
            if c.status == "unknown":
                self._negative_keys[j] = negative_history(c)

    def utility(self, c, q, mask):
        if c.status != "unknown":
            return super().utility(c, q, mask)
        if q in c.measured:
            return 0.0
        key = self._negative_keys.get(c.channel)
        if key is None:
            key = negative_history(c)
        return self.config.search_work_s * oriented_gain(key, tuple(q))

    def candidate_positions(self, state):
        points = list(super().candidate_positions(state))
        models = {self._negative_keys.get(j, negative_history(c))
                  for j, c in state.channels.items() if c.status == "unknown"}
        proposed = {}
        for negatives in models:
            for p, weight, intervals, length in orientation_rows(negatives):
                fallback = math.atan2(state.position[1] - p[1], state.position[0] - p[0])
                angle = interval_direction(intervals, fallback)
                q = (p[0] + self.config.search_probe_radius_m * math.cos(angle),
                     p[1] + self.config.search_probe_radius_m * math.sin(angle))
                # 这里只决定保留哪些动态候选，实际行动仍按各频道总工作/费用排序。
                priority = weight * length / (6.0 + g.distance(q, state.position) / 5.0)
                proposed[q] = max(proposed.get(q, 0.0), priority)
        selected = []
        for q in sorted(proposed, key=lambda q: (-proposed[q], q)):
            if all(g.distance(q, old) >= 180 for old in selected):
                selected.append(q)
            if len(selected) >= self.config.search_candidate_limit:
                break
        points.extend(selected)
        # 连续证书可以保留求积网格看不到的窄缺口，继续提供位置候选。
        if hasattr(state, "discovery_points"):
            points.extend(state.discovery_points(limit=6))
        return list(dict.fromkeys(q for q in points if math.hypot(*q) <= self.config.domain_radius_m))


def box_remaining_probes(box, near):
    """方格的3/2/1/0步包围工作代理；0严格满足整格凸包条件。"""
    if not near:
        return 3
    if len(near) == 1:
        return 2
    hull = g.hull(near)
    if _strictly_inside(hull, _corners(box), 1e-5):
        return 0
    if len(hull) < 2:
        return 2
    if len(hull) == 2:
        a, b = hull
        values = [g.cross(g.sub(b, a), g.sub(p, a)) for p in _corners(box)]
        # 方格横跨两测点所在直线时，新增一点的三角形仍不能包围全格。
        if min(values) <= 1e-5 and max(values) >= -1e-5:
            return 2
    return 1


@lru_cache(maxsize=256)
def hull_work_features(negatives):
    """连续未决格按450m空间桶和工作级别聚合，仅用作控制求积规模。"""
    cert = q4_coverage_certificate(negatives)
    groups = {}
    stack = list(cert.unresolved)
    while stack:
        box = stack.pop()
        if box.x1 - box.x0 > 225:
            stack.extend(box.children())
            continue
        if box.nearest_distance((0, 0)) > 1800 + 1e-5:
            continue
        near = tuple(q for q in negatives if box.farthest_distance(q) < 1000 - 1e-5)
        need = box_remaining_probes(box, near)
        if need == 0:
            continue
        center = box.center
        key = (math.floor(center[0] / 450), math.floor(center[1] / 450), need)
        if key not in groups:
            groups[key] = [box, box.area, near, need]
        else:
            groups[key][1] += box.area
            if box.area > groups[key][0].area:
                groups[key][0], groups[key][2] = box, near
    return tuple((box, area, near, need) for box, area, near, need in groups.values())


@lru_cache(maxsize=32768)
def hull_gain(negatives, q):
    features = hull_work_features(negatives)
    before = sum(area * need for box, area, near, need in features)
    if before <= 0:
        return 0.0
    saved = 0.0
    for box, area, near, need in features:
        if box.farthest_distance(q) < 1000 - 1e-5:
            after = box_remaining_probes(box, near + (q,))
            saved += area * max(0, need - after)
    return saved / before


class Q4HullSearchPolicy(Q4SearchPolicy):
    """用尚需测点数衡量方格包围工作，避免很窄角隙的价值趋于零。"""
    def utility(self, c, q, mask):
        if c.status != "unknown":
            return super().utility(c, q, mask)
        if q in c.measured:
            return 0.0
        key = self._negative_keys.get(c.channel, negative_history(c))
        missed = len(self._state.q4_anchors_missed[c.channel]) if self._state is not None else 0
        remaining_reference_s = 6.0 * max(1, len(Q4_ANCHORS) - missed)
        return remaining_reference_s * hull_gain(key, tuple(q))

    def candidate_positions(self, state):
        points = list(Q4DirectionalPolicy.candidate_positions(self, state))
        models = {self._negative_keys.get(j, negative_history(c))
                  for j, c in state.channels.items() if c.status == "unknown"}
        proposed = {}
        for negatives in models:
            features = hull_work_features(negatives)
            total_work = sum(area * need for box, area, near, need in features)
            for box, area, near, need in features:
                p = box.point_in_domain(1800)
                if p is None:
                    continue
                angles = sorted(math.atan2(q[1] - p[1], q[0] - p[0]) for q in near
                                if g.distance(q, p) > 1e-5)
                if angles:
                    gaps = list(zip(angles, angles[1:] + [angles[0] + 2 * math.pi]))
                    a, b = max(gaps, key=lambda pair: pair[1] - pair[0])
                    angle = (a + b) / 2
                else:
                    angle = math.atan2(state.position[1] - p[1], state.position[0] - p[0])
                offsets = (0, math.pi / 4, -math.pi / 4) if need >= 2 else (0,)
                for offset in offsets:
                    q = (p[0] + self.config.search_probe_radius_m * math.cos(angle + offset),
                         p[1] + self.config.search_probe_radius_m * math.sin(angle + offset))
                    priority = area * need / max(1, total_work) / (6 + g.distance(q, state.position) / 5)
                    proposed[q] = max(proposed.get(q, 0.0), priority)
        selected = []
        for q in sorted(proposed, key=lambda q: (-proposed[q], q)):
            if all(g.distance(q, old) >= 180 for old in selected):
                selected.append(q)
            if len(selected) >= self.config.search_candidate_limit:
                break
        points.extend(selected)
        points.extend(state.discovery_points(limit=6))
        return list(dict.fromkeys(q for q in points if math.hypot(*q) <= self.config.domain_radius_m))
