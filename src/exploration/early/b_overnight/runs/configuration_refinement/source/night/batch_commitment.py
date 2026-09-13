"""履行原策略真实 planned_channels 的短队列，不改变任何信息状态。"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from task_cost import CompletionCostPolicy, g
from policy import BasePolicy


class BatchCommitmentMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._batch_point = None
        self._batch_channels = []
        self._batch_first_action = None
        self._batch_created_at = None
        self._batch_id = 0
        self.batch_stats = {"planned_batches": 0, "planned_additional_channels": 0, "committed_measures": 0,
                            "near_interruptions": 0, "skipped_terminal": 0, "skipped_measured": 0,
                            "completed_batches": 0, "cancelled_protection": 0, "cancelled_position": 0}

    def _discard_batch(self):
        self._batch_point = None
        self._batch_channels = []
        self._batch_first_action = None
        self._batch_created_at = None

    def choose(self, state):
        if state.complete:
            self._discard_batch()
            return None
        protected = (self.reference_only or self.fallback_started
                     or state.virtual_time_s >= self.config.adaptive_virtual_budget_s
                     or state.actions >= self.config.adaptive_action_limit)
        if protected:
            self.batch_stats["cancelled_protection"] += int(self._batch_point is not None)
            self._discard_batch()
            return super().choose(state)
        if self._batch_point is not None:
            # 没有新反馈时不把队列推进到另一频道。
            if state.actions == self._batch_created_at:
                return self._batch_first_action
            if g.distance(state.position, self._batch_point) > 1e-6:
                self.batch_stats["cancelled_position"] += 1
                self._discard_batch()
            else:
                near = [c for c in state.channels.values() if c.status == "found" and c.near_position is not None
                        and g.distance(c.near_position, state.position) <= 1e-6]
                if near:
                    c = min(near, key=lambda c: c.channel)
                    self.batch_stats["near_interruptions"] += 1
                    return self.action("clear", state.position, c.channel, "batch_near_clear", batch_id=self._batch_id)
                retained = []
                for j in self._batch_channels:
                    c = state.channels[j]
                    if c.status in ("cleared", "absent"):
                        self.batch_stats["skipped_terminal"] += 1
                    elif self._batch_point in c.measured:
                        self.batch_stats["skipped_measured"] += 1
                    else:
                        retained.append(j)
                self._batch_channels = retained
                if retained:
                    self.batch_stats["committed_measures"] += 1
                    return self.action("measure", self._batch_point, retained[0], "committed_batch",
                                       batch_id=self._batch_id, batch_pending_channels=list(retained))
                self.batch_stats["completed_batches"] += 1
                self._discard_batch()
        action = super().choose(state)
        if action is None or action["kind"] != "measure":
            return action
        planned = action.get("planned_channels", [])
        if len(planned) <= 1:
            return action
        if any(isinstance(j, bool) or not isinstance(j, int) or j not in state.channels for j in planned):
            raise ValueError("原策略给出非法 planned_channels")
        planned = list(dict.fromkeys(planned))
        if not planned or planned[0] != action["channel"]:
            raise ValueError("原策略首动作与 planned_channels 首频道不一致")
        self._batch_id += 1
        self._batch_point = tuple(action["position"])
        self._batch_channels = planned
        self._batch_first_action = dict(action, batch_id=self._batch_id)
        self._batch_created_at = state.actions
        self.batch_stats["planned_batches"] += 1
        self.batch_stats["planned_additional_channels"] += len(planned) - 1
        return self._batch_first_action


class CommittedBasePolicy(BatchCommitmentMixin, BasePolicy):
    pass


class CommittedCompletionPolicy(BatchCommitmentMixin, CompletionCostPolicy):
    pass


def natural_batch_fulfilment(rows, state_factory):
    """重放公开反馈：计划所含频道是否在离开该点前被测/清除/证实不存在。"""
    state = state_factory()
    active = []
    stats = dict(plans=0, plans_fulfilled_before_leaving=0, plans_left_unfinished=0, abandoned_channel_count=0)
    for row in rows:
        action = {key: value for key, value in row.items() if key not in ("response", "step")}
        q = tuple(action["position"])
        kept = []
        for point, remaining in active:
            if g.distance(point, q) > 1e-6:
                stats["plans_left_unfinished"] += 1
                stats["abandoned_channel_count"] += len(remaining)
            else:
                kept.append((point, remaining))
        active = kept
        planned = action.get("planned_channels", [])
        if len(planned) > 1:
            stats["plans"] += 1
            active.append((q, list(dict.fromkeys(planned))))
        state.update(action, row["response"])
        kept = []
        for point, remaining in active:
            remaining = [j for j in remaining if state.channels[j].status not in ("cleared", "absent") and point not in state.channels[j].measured]
            if remaining:
                kept.append((point, remaining))
            else:
                stats["plans_fulfilled_before_leaving"] += 1
        active = kept
    stats["plans_left_unfinished"] += len(active)
    stats["abandoned_channel_count"] += sum(len(remaining) for _, remaining in active)
    return stats
