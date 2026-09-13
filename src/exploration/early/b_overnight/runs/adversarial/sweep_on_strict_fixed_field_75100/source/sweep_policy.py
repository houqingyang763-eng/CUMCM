"""先利用共同发现巡查路上的信息，再集中清除；与原状态和后备兼容。"""
from task_cost import CompletionCostConfig, CompletionCostPolicy
from q4_anchor_design import Q4Symmetric25Policy, Q4_SYMMETRIC25_ANCHORS
import geometry as g


class SweepMixin:
    sweep_anchors = ()

    def __init__(self, config=None):
        super().__init__(config)
        self.stats = dict(sweep_measures=0, shared_known_measures=0, stationary_clears=0)

    def choose(self, state):
        if state.complete:
            return None
        if (self.fallback_started or state.virtual_time_s >= self.config.adaptive_virtual_budget_s or
                state.actions >= self.config.adaptive_action_limit):
            return self.fallback(state)
        unknown = [c for c in state.channels.values() if c.status == "unknown"]
        if not unknown:
            return super().choose(state)
        # 巡查时只做无需额外移动的可靠清除；未发现频道存在时不追逐远处目标。
        for c in state.channels.values():
            if c.status == "found" and all(g.distance(state.position, p) <= 20 - 1e-5 for p in c.support()):
                self.stats["stationary_clears"] += 1
                return self.action("clear", state.position, c.channel, "sweep_stationary_clear")
        here = any(g.distance(state.position, q) < 1e-7 for q in self.sweep_anchors)
        due_here = [c.channel for c in unknown if state.position not in c.measured] if here else []
        if due_here:
            j = state.measuring_channel if state.measuring_channel in due_here else min(due_here)
            self.stats["sweep_measures"] += 1
            return self.action("measure", state.position, j, "sweep_unknown_at_node")
        self._prepare(state)
        choices = []
        mask = g.coverage_mask(state.position)
        for j, c in state.channels.items():
            if c.status != "found":
                continue
            gain = self.utility(c, state.position, mask)
            cost = 5 + int(j != state.measuring_channel)
            if gain >= self.config.current_probe_ratio * cost:
                choices.append((gain / cost, j))
        if choices:
            _, j = max(choices)
            self.stats["shared_known_measures"] += 1
            return self.action("measure", state.position, j, "sweep_shared_known_probe")
        needed = [(g.distance(state.position, q), q) for q in self.sweep_anchors
                  if any(q not in c.measured for c in unknown)]
        if not needed:
            # 原发现网络已全部测过但状态仍未知时，不假称结束，进入原有限后备。
            return self.fallback(state)
        _, q = min(needed)
        channels = [c.channel for c in unknown if q not in c.measured]
        j = state.measuring_channel if state.measuring_channel in channels else min(channels)
        self.stats["sweep_measures"] += 1
        return self.action("measure", q, j, "sweep_next_discovery_node")


class Q3SweepPolicy(SweepMixin, CompletionCostPolicy):
    sweep_anchors = g.ANCHORS


class Q4SweepPolicy(SweepMixin, Q4Symmetric25Policy):
    sweep_anchors = Q4_SYMMETRIC25_ANCHORS
