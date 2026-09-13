"""第四问独立状态和策略：半圆/全向混合，不作第三问阴性圆盘排除。"""
from dataclasses import dataclass
import math

from task_cost import CompletionCostConfig, CompletionCostPolicy, g
from policy import BasePolicy
from state import InformationState

Q4_ANCHORS = tuple((900.0 * (i + j / 2), 900.0 * math.sqrt(3) * j / 2)
                   for j in range(-3, 4) for i in range(-4, 5) if i * i + i * j + j * j <= 9)


class Q4InformationState(InformationState):
    def __init__(self):
        super().__init__()
        self.q4_anchors_missed = {j: set() for j in self.channels}
        self.absence_proofs = {}

    def update(self, action, response):
        if action["kind"] != "measure" or response.get("measure_result") != "no_signal":
            super().update(action, response)
            for j, c in self.channels.items():
                if c.status == "absent" and j not in self.absence_proofs:
                    self.absence_proofs[j] = {"kind": "sixteen_source_cap"}
            return
        if not response.get("accepted"):
            raise ValueError("只接收已经执行的动作")
        q, j = tuple(action["position"]), action["channel"]
        c = self.channels[j]
        c.invalidate()
        self.position = q
        self.measuring_channel = j
        self.virtual_time_s = response["virtual_time_s"]
        self.actions += 1
        c.measured.add(q)
        c.observations.append((q, "no_signal", None))
        # no_signal 不更新 polygon/exclusions/sample_mask/七点 anchors_missed。
        for i, anchor in enumerate(Q4_ANCHORS):
            if g.distance(q, anchor) < 1e-6:
                self.q4_anchors_missed[j].add(i)
        if c.status == "unknown" and len(self.q4_anchors_missed[j]) == len(Q4_ANCHORS):
            c.status = "absent"
            self.absence_proofs[j] = {"kind": "q4_37_triangular_anchors", "misses": len(Q4_ANCHORS)}


@dataclass(frozen=True)
class Q4Config(CompletionCostConfig):
    adaptive_virtual_budget_s: float = 12000.0
    adaptive_action_limit: int = 1000
    q4_anchor_value_s: float = 30.0


class Q4Policy(CompletionCostPolicy):
    """37 点发现 + 任务费用定位 + 有限清除格；不推断发射方向。"""
    def __init__(self, config=None, reference_only=False):
        super().__init__(config or Q4Config(), reference_only)
        self._state = None

    def _prepare(self, state):
        self._state = state
        super()._prepare(state)

    def candidate_positions(self, state):
        points = super().candidate_positions(state)
        points.extend(Q4_ANCHORS)
        return list(dict.fromkeys(points))

    def utility(self, c, q, mask):
        if c.status != "unknown":
            return super().utility(c, q, mask)
        if q in c.measured:
            return 0.0
        if any(g.distance(q, anchor) < 1e-6 for anchor in Q4_ANCHORS):
            return self.config.q4_anchor_value_s
        return 0.0

    def fallback(self, state):
        self.fallback_started = True
        near = [c for c in state.channels.values() if c.status == "found" and c.near_position is not None]
        if near:
            c = min(near, key=lambda c: g.distance(state.position, c.near_position))
            return self.action("clear", c.near_position, c.channel, "q4_fallback_near")
        needed = [(g.distance(state.position, q) / 5 + 5 + int(j != state.measuring_channel), i, q, j)
                  for j, c in state.channels.items() if c.status == "unknown"
                  for i, q in enumerate(Q4_ANCHORS) if i not in state.q4_anchors_missed[j]]
        if needed:
            _, _, q, j = min(needed)
            return self.action("measure", q, j, "q4_fallback_discovery")
        # 没有未知频道后，原始 fallback 仅清除已发现目标；不会再执行七点发现。
        return BasePolicy.fallback(self, state)


class Q4ReferencePolicy(Q4Policy):
    def __init__(self, config=None, reference_only=True):
        super().__init__(config, reference_only=True)


def _arc(center):
    lo, hi = (center - 90) % 360, (center + 90) % 360
    return [(lo, hi)] if lo < hi else [(0.0, hi), (lo, 360.0)]


def _intersection(first, second):
    return [(max(a, c), min(b, d)) for a, b in first for c, d in second if max(a, c) <= min(b, d)]


def _subtract(first, second):
    for c, d in second:
        updated = []
        for a, b in first:
            if d <= a or c >= b:
                updated.append((a, b))
            else:
                if a < c:
                    updated.append((a, c))
                if d < b:
                    updated.append((d, b))
        first = updated
    return first


def orientation_model(c, p):
    """固定候选位置的可行方向区间；仅用于评分，不用于删位置或结束证明。"""
    positive = [q for q, result, _ in c.observations if result in ("direction", "near")]
    negative = [q for q, result, _ in c.observations if result == "no_signal"]
    lower_radius = max([1000.0] + [g.distance(p, q) for q in positive])
    intervals = [(0.0, 360.0)]
    for q in positive:
        if g.distance(p, q) < 1e-8:
            continue
        bearing = math.degrees(math.atan2(q[1] - p[1], q[0] - p[0])) % 360
        intervals = _intersection(intervals, _arc(bearing))
    omni = True
    for q in negative:
        if g.distance(p, q) < lower_radius - 1e-6:
            omni = False
            bearing = math.degrees(math.atan2(q[1] - p[1], q[0] - p[0])) % 360
            intervals = _subtract(intervals, _arc(bearing))
    return omni, intervals


def orientation_reception(model, p, q):
    omni, intervals = model
    bearing = math.degrees(math.atan2(q[1] - p[1], q[0] - p[0])) % 360
    length = sum(b - a for a, b in intervals)
    if length <= 1e-10:
        return 1.0 if omni else 0.0
    hit = sum(b - a for a, b in _intersection(intervals, _arc(bearing))) / length
    # 两种仍可行源类型取等权启发；区间内取角度长度比例，非真实概率后验。
    return (1 + hit) / 2 if omni else hit


class Q4DirectionalPolicy(Q4Policy):
    """发射方向一致性评分 + 已接收侧候选；全部安全证据仍来自 Q4 状态。"""
    def __init__(self, config=None, reference_only=False):
        super().__init__(config, reference_only)
        self._orientation_models = {}
        self._orientation_stamps = {}

    def _prepare(self, state):
        super()._prepare(state)
        for j, c in state.channels.items():
            if c.status != "found":
                continue
            stamp = self._channel_stamps[j]
            if self._orientation_stamps.get(j) != stamp:
                self._orientation_models[j] = [(p, orientation_model(c, p)) for p in self._features[j][1]]
                self._orientation_stamps[j] = stamp

    def utility(self, c, q, mask):
        value = super().utility(c, q, mask)
        if value <= 0 or c.status != "found":
            return value
        models = self._orientation_models.get(c.channel)
        if models is None:
            models = [(p, orientation_model(c, p)) for p in self._representatives(c)]
        if not models:
            return 0.0
        return value * sum(orientation_reception(model, p, q) for p, model in models) / len(models)

    def candidate_positions(self, state):
        points = super().candidate_positions(state)
        for c in state.channels.values():
            if c.status != "found" or c.circle()[1] <= 20 - 1e-5:
                continue
            center = c.circle()[0]
            positive = [q for q, result, _ in c.observations if result in ("direction", "near")][-3:]
            for q in positive:
                points.extend(g.add(center, g.mul(g.sub(q, center), t)) for t in (.1, .25, .5))
            # 固定源的接收区为圆盘与半平面的交，故已接收点的凸包仍在接收区。
            for i, a in enumerate(positive):
                for b in positive[i + 1:]:
                    points.extend(g.add(a, g.mul(g.sub(b, a), t)) for t in (.25, .5, .75))
        return list(dict.fromkeys(q for q in points if g.distance(q, (0, 0)) <= self.config.domain_radius_m))
