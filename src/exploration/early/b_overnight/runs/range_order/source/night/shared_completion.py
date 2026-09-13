"""共享测点的完成成本：一次移动可能同时减少多个目标后续工作。"""
from dataclasses import dataclass

from task_cost import CompletionCostConfig, CompletionCostPolicy
import geometry as g


@dataclass(frozen=True)
class SharedCompletionConfig(CompletionCostConfig):
    shared_credit: float = 1.0


class SharedCompletionPolicy(CompletionCostPolicy):
    def __init__(self, config=None):
        super().__init__(config or SharedCompletionConfig())
        self.stats = dict(shared_decisions=0, shared_changes=0)

    def co_benefit(self, state, q, primary):
        """额外检测各付6秒；只计会被当前点检测规则采纳的已发现频道。"""
        benefits = []
        mask = g.coverage_mask(q)
        for j, c in state.channels.items():
            if j == primary or c.status != "found":
                continue
            gain = self.utility(c, q, mask)
            if gain >= self.config.current_probe_ratio * 6:
                benefits.append((j, max(0., gain - 6.)))
        return sum(value for _, value in benefits), [j for j, _ in benefits]

    def choose(self, state):
        original = super().choose(state)
        found = [c for c in state.channels.values() if c.status == "found"]
        if (original is None or self.fallback_started or len(found) < 2 or
            state.channels[original["channel"]].status != "found" or
            g.distance(state.position, original["position"]) < 1e-6 or
            any(c.near_position is not None for c in found)):
            return original
        self.stats["shared_decisions"] += 1
        base_cost = original.get("estimated_completion_s",
                        g.distance(state.position, original["position"]) / 5 + 5)
        bonus, extras = self.co_benefit(state, original["position"], original["channel"])
        candidates = [(base_cost - self.config.shared_credit * bonus, original, bonus, extras)]
        for c in found:
            center, radius = c.circle()
            before = self._features[c.channel][0]
            if radius <= 20 - 1e-5:
                cost = g.distance(state.position, center) / 5 + 5
                bonus, extras = self.co_benefit(state, center, c.channel)
                candidates.append((cost - self.config.shared_credit * bonus,
                    self.action("clear", center, c.channel, "shared_certified_clear", enclosure_radius_m=radius), bonus, extras))
                continue
            for q in self.candidate_positions(state):
                if q in c.measured:
                    continue
                gain = self.utility(c, q, g.coverage_mask(q))
                if gain < self.config.min_work_gain_s:
                    continue
                bonus, extras = self.co_benefit(state, q, c.channel)
                if not extras:
                    continue
                cost = (g.distance(state.position, q) / 5 + 5 + int(c.channel != state.measuring_channel)
                        + g.distance(q, center) / 5 + max(5., before - gain))
                candidates.append((cost - self.config.shared_credit * bonus,
                    self.action("measure", q, c.channel, "shared_measure_then_clear", estimated_completion_s=cost), bonus, extras))
        score, chosen, bonus, extras = min(candidates, key=lambda item: item[0])
        changed = (chosen["kind"] != original["kind"] or chosen["channel"] != original["channel"] or
                   g.distance(chosen["position"], original["position"]) > 1e-6)
        self.stats["shared_changes"] += int(changed)
        return dict(chosen, shared_adjusted_score_s=score, other_work_saved_s=bonus,
                    shared_channels=extras, shared_changed=changed)
