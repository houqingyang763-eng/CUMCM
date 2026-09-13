"""第四问连续位置小格与发射朝向的联合外包；不改冻结 Q4。"""
from dataclasses import dataclass, field
import math

from q4 import Q4InformationState, g
from q2_geometry import guaranteed_reception
from state import ChannelState

ANGLE_MARGIN_DEG = 1e-6
POSITION_MARGIN_M = 1e-5
FULL_CIRCLE = [(0.0, 360.0)]


def point_segment_distance(p, a, b):
    v = g.sub(b, a)
    vv = g.dot(v, v)
    if vv == 0:
        return g.distance(p, a)
    t = max(0.0, min(1.0, g.dot(g.sub(p, a), v) / vv))
    return g.distance(p, g.add(a, g.mul(v, t)))


def vector_angle_arc(poly, observer):
    """覆盖全部 observer-s, s∈凸poly 的方向弧，返回起角与弧长。

    观察点在格内或极近边界时退回全圆；否则凸集的视角由顶点极射线
    确定，取排序角度最大空隙的补弧。弧长超过180度也保守退回全圆。
    """
    if not poly:
        raise ValueError("空多边形不定义方向外包")
    if g.contains(poly, observer, tolerance=POSITION_MARGIN_M):
        return 0.0, 360.0
    if any(point_segment_distance(observer, a, b) <= POSITION_MARGIN_M
           for a, b in zip(poly, poly[1:] + poly[:1])):
        return 0.0, 360.0
    angles = sorted(math.degrees(math.atan2(observer[1] - s[1], observer[0] - s[0])) % 360
                    for s in poly)
    gaps = [(angles[(i + 1) % len(angles)] + (360 if i + 1 == len(angles) else 0) - a, i)
            for i, a in enumerate(angles)]
    gap, index = max(gaps)
    start, width = angles[(index + 1) % len(angles)], 360 - gap
    if width > 180 + ANGLE_MARGIN_DEG:
        return 0.0, 360.0
    return start, width


def arc_intervals(start, width):
    if width >= 360:
        return list(FULL_CIRCLE)
    if width < 0:
        raise ValueError("弧长不能为负")
    start %= 360
    end = start + width
    if end <= 360:
        return [(start, end)]
    return [(0.0, end - 360), (start, 360.0)]


def allowed_orientation_outer(poly, observer, opposite=False):
    """阳性取视角扩±90度，可靠距离内阴性取反方向再扩±90度。"""
    start, width = vector_angle_arc(poly, observer)
    return arc_intervals(start + (180 if opposite else 0) - 90 - ANGLE_MARGIN_DEG,
                         min(360.0, width + 180 + 2 * ANGLE_MARGIN_DEG))


def intersect_intervals(first, second):
    pieces = sorted((max(a, c), min(b, d)) for a, b in first for c, d in second
                    if max(a, c) <= min(b, d))
    merged = []
    for a, b in pieces:
        if merged and a <= merged[-1][1] + 1e-10:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    return merged


def orientation_in(intervals, angle, tolerance=1e-7):
    return any(a - tolerance <= theta <= b + tolerance
               for a, b in intervals for theta in (angle % 360, angle % 360 + 360, angle % 360 - 360))


def joint_cell_certificate(poly, positive_positions, negative_positions):
    """只能在全向解释被排除且方向外包交为空时排除整格。

    接收半径下界用历史阳性距离；阴性点必须对整格有可靠距离证书。
    所有角区间取连续格上联合外包，各观测之间主动放松位置耦合，故
    空交足以排除，非空不代表一定存在可行的共同源位置和方向。
    """
    positive_positions = list(dict.fromkeys(tuple(p) for p in positive_positions))
    negative_positions = list(dict.fromkeys(tuple(q) for q in negative_positions))
    allowed = list(FULL_CIRCLE)
    for p in positive_positions:
        allowed = intersect_intervals(allowed, allowed_orientation_outer(poly, p))
    omni_possible = True
    effective_negatives = []
    for q in negative_positions:
        if guaranteed_reception(poly, q, positive_positions):
            omni_possible = False
            effective_negatives.append(q)
            allowed = intersect_intervals(allowed, allowed_orientation_outer(poly, q, opposite=True))
    return dict(discarded=not omni_possible and not allowed, omni_possible=omni_possible,
                orientation_intervals=allowed, effective_negative_positions=effective_negatives,
                polygon=list(poly))


@dataclass
class JointChannelState(ChannelState):
    joint_excluded: dict = field(default_factory=dict)
    joint_last_details: list = field(default_factory=list)
    joint_certificate_calls: int = 0
    joint_distance_negative_uses: int = 0

    def possible_cells(self):
        if self.cached_cells is not None:
            return self.cached_cells
        raw = super().possible_cells()
        if not raw:
            return raw
        positive = [p for p, result, _ in self.observations if result in ("direction", "near")]
        negative = [p for p, result, _ in self.observations if result == "no_signal"]
        if not negative:
            self.joint_last_details = []
            return raw
        kept, details = [], []
        for cell in raw:
            index = tuple(cell["index"])
            cert = self.joint_excluded.get(index)
            if cert is None:
                cert = joint_cell_certificate(cell["polygon"], positive, negative)
                cert["index"] = index
                self.joint_certificate_calls += 1
                self.joint_distance_negative_uses += len(cert["effective_negative_positions"])
                if cert["discarded"]:
                    # first/格框固定，后续位置约束只收紧；此前已证空的格可持久排除。
                    self.joint_excluded[index] = cert
            details.append(cert)
            if not cert["discarded"]:
                kept.append(cell)
        self.joint_last_details = details
        if not kept:
            raise AssertionError("已发现源的全部小格被联合证书排除，观测或实现不相容")
        self.cached_cells = kept
        return kept

    def compatible(self, p):
        if not super().compatible(p):
            return False
        if self.first is None:
            return True
        return any(g.contains(cell["polygon"], p) for cell in self.possible_cells())


class Q4JointInformationState(Q4InformationState):
    """只加强已发现目标的清除格，不改变37点发现与有限后备。"""
    def __init__(self):
        super().__init__()
        self.channels = {j: JointChannelState(j) for j in range(1, 21)}

    def joint_statistics(self):
        return dict(unique_removed_cells=sum(len(c.joint_excluded) for c in self.channels.values()),
                    channels_with_removal=sum(bool(c.joint_excluded) for c in self.channels.values()),
                    certificate_calls=sum(c.joint_certificate_calls for c in self.channels.values()),
                    effective_negative_uses=sum(c.joint_distance_negative_uses for c in self.channels.values()))
