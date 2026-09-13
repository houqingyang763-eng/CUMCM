"""Q3 阳性与阴性之间共享接收半径，给出额外的距离次序半平面。"""
from pathlib import Path
import math
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "b_adaptive_q3"))
from state import InformationState
import geometry as g


def clip_distance_order(poly, positive, negative):
    """收到p、未收到q => |s-p| <= R < |s-q|，保守保留其闭半平面。"""
    n = g.sub(negative, positive)
    length = math.hypot(*n)
    if length == 0:
        raise ValueError("静态全向源同地点不可能同时阳性与阴性")
    local = [g.sub(s, positive) for s in poly]
    clipped = g.clip(local, g.mul(n, 1 / length), length / 2)
    return [g.add(s, positive) for s in clipped]


class RangeOrderMixin:
    def __init__(self):
        super().__init__()
        self.range_order_constraints = 0

    def update(self, action, response):
        super().update(action, response)
        if action["kind"] != "measure":
            return
        c = self.channels[action["channel"]]
        if c.status != "found":
            return
        q, outcome, _ = c.observations[-1]
        pairs = []
        for p, old, _ in c.observations[:-1]:
            if outcome == "no_signal" and old in ("direction", "near"):
                pairs.append((p, q))
            elif outcome in ("direction", "near") and old == "no_signal":
                pairs.append((q, p))
        for positive, negative in pairs:
            c.polygon = clip_distance_order(c.polygon, positive, negative)
            self.range_order_constraints += 1
        if pairs:
            c.invalidate()
            if not c.polygon:
                raise AssertionError("距离次序约束与历史不一致")


class RangeOrderInformationState(RangeOrderMixin, InformationState):
    pass
