"""Q4 动态搜索：用尚未排除的位置与发射角区间评价扫描工作，单位秒。"""
from dataclasses import dataclass
from functools import lru_cache
import math

from q4 import Q4_ANCHORS, Q4Config, Q4DirectionalPolicy, _arc, _intersection, _subtract
from q4_coverage import Q4CoverageInformationState
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
