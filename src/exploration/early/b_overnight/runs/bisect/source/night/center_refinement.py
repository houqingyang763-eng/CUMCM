"""选定目标后连续逼近可能区域中点；模块名避开标准库 bisect。"""
import math
from dataclasses import dataclass

from task_cost import CompletionCostConfig, CompletionCostPolicy
import geometry as g


@dataclass(frozen=True)
class BisectConfig(CompletionCostConfig):
    minimum_probe_displacement_m: float = 1.0


class BisectPolicy(CompletionCostPolicy):
    def __init__(self, config=None):
        super().__init__(config or BisectConfig())
        self.focus_channel = None
        self.stats = dict(focused_measures=0, focus_changes=0, completed_focus=0)

    def choose(self, state):
        if state.complete:
            return None
        if (self.fallback_started or state.virtual_time_s >= self.config.adaptive_virtual_budget_s or
                state.actions >= self.config.adaptive_action_limit):
            return self.fallback(state)
        found = [c for c in state.channels.values() if c.status == "found"]
        if not found:
            return super().choose(state)
        self._prepare(state)
        near = [c for c in found if c.near_position is not None]
        if near:
            c = min(near, key=lambda c: g.distance(state.position, c.near_position))
            return self.action("clear", c.near_position, c.channel, "bisect_near_clear")
        # 先利用停在同一点的低费用检测机会，不为它们新增往返路程。
        mask = g.coverage_mask(state.position)
        immediate = []
        for j, c in state.channels.items():
            gain = self.utility(c, state.position, mask)
            cost = 5 + int(j != state.measuring_channel)
            if gain >= self.config.current_probe_ratio * cost:
                immediate.append((gain / cost, j))
        if immediate:
            _, j = max(immediate)
            return self.action("measure", state.position, j, "bisect_shared_probe")
        if self.focus_channel is None or state.channels[self.focus_channel].status != "found":
            if self.focus_channel is not None:
                self.stats["completed_focus"] += 1
            # 2r/5 是在区域中点之间逼近的路程代理，不作为严格几何上界。
            def cost(c):
                center, r = c.circle()
                scans = max(0., math.ceil(math.log2(max(1., r / 20))))
                return g.distance(state.position, center) / 5 + 2 * r / 5 + 6 * scans + 5
            self.focus_channel = min(found, key=cost).channel
            self.stats["focus_changes"] += 1
        c = state.channels[self.focus_channel]
        center, radius = c.circle()
        if radius <= 20 - 1e-5:
            return self.action("clear", center, c.channel, "bisect_certified_clear", enclosure_radius_m=radius)
        q = center
        if any(g.distance(q, old) < self.config.minimum_probe_displacement_m for old in c.measured):
            # 相同位置读数固定：若区域中心不再移动，转向近处侧点，禁止原地重测循环。
            poly = c.support()
            a, b = max(((a, b) for a in poly for b in poly), key=lambda pair: g.distance(*pair))
            d = g.sub(b, a)
            length = math.hypot(*d)
            n = (-d[1] / length, d[0] / length) if length else (0., 1.)
            points = [g.add(center, g.mul(n, offset)) for offset in (20., -20., 40., -40.)]
            points = [p for p in points if p not in c.measured]
            if not points:
                return super().choose(state)
            q = min(points, key=lambda p: g.distance(p, state.position))
        self.stats["focused_measures"] += 1
        return self.action("measure", q, c.channel, "bisect_region_center", prior_radius_m=radius)
