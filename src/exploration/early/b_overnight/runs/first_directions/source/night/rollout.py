"""有限前瞻：只用历史相容环境，对少量移动候选模拟完整后续。"""
import copy
import math
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "b_adaptive_q3"))
import geometry as g
from policy import BasePolicy, Config
from state import audit_state
from worlds import sample_environment
from astra_guard import check_cached


@dataclass(frozen=True)
class RolloutConfig(Config):
    max_candidates: int = 3
    worlds_per_decision: int = 2
    decision_wall_s: float = 2.0
    total_rollout_wall_s: float = 12.0
    min_move_m: float = 60.0
    tail_weight: float = 0.25
    min_relative_gain: float = 0.03
    future_action_limit: int = 800
    sampler_seed: int = 43917
    continuation_kind: str = "base"


class RolloutPolicy:
    def __init__(self, config=None, use_coverage=False):
        self.config = config or RolloutConfig()
        self.use_coverage = use_coverage
        self.base = self.make_base()
        self.fallback_started = False
        self.stats = dict(decisions=0, changed=0, sampling_failed=0, unfinished=0,
                          simulation_actions=0, rollout_wall_s=0.0, completed_comparisons=0)

    def make_base(self):
        cls, config = BasePolicy, self.config
        if self.config.continuation_kind == "task_cost":
            from task_cost import TaskCostPolicy, TaskCostConfig
            cls, config = TaskCostPolicy, TaskCostConfig()
        if self.use_coverage:
            from coverage import CoveragePolicyMixin
            class Combined(CoveragePolicyMixin, cls):
                pass
            cls = Combined
        return cls(config)

    def candidates(self, state, original):
        proposed = [(math.inf, original)]
        for c in state.channels.values():
            if c.status == "found" and c.circle()[1] <= 20-1e-5:
                q, r = c.circle()
                score = self.config.clear_weight/(g.distance(state.position, q)/5+5)
                proposed.append((score, BasePolicy.action("clear", q, c.channel, "rollout_candidate_clear", enclosure_radius_m=r)))
        for q in self.base.candidate_positions(state):
            if g.distance(q, state.position) < self.config.min_move_m:
                continue
            mask = g.coverage_mask(q)
            items = sorted([(self.base.utility(c, q, mask), j) for j, c in state.channels.items()], reverse=True)
            items = [(u, j) for u, j in items if u > 1e-7]
            gain, selected, best = 0.0, [], None
            for utility, j in items:
                gain += utility
                selected.append(j)
                cost = g.distance(q, state.position)/5+6*len(selected)-int(state.measuring_channel in selected)
                order = ([state.measuring_channel]+[k for k in selected if k != state.measuring_channel]
                         if state.measuring_channel in selected else list(selected))
                if best is None or gain/cost > best[0]:
                    best = (gain/cost, BasePolicy.action("measure", q, order[0], "rollout_candidate_measure", planned_channels=order))
            if best:
                proposed.append(best)
        # 候选保持当前位置选择的原始动作，并限制为不同目的地点。
        out, seen = [], set()
        for score, action in sorted(proposed, key=lambda x: x[0], reverse=True):
            key = tuple(round(v, 2) for v in action["position"])
            if key in seen:
                continue
            seen.add(key)
            out.append(action)
            if len(out) >= self.config.max_candidates:
                break
        return out

    def complete_future(self, state, environment, first_action, deadline):
        state, env = copy.deepcopy(state), copy.deepcopy(environment)
        policy = self.make_base()
        start = env.virtual_time_s
        action = first_action
        for count in range(self.config.future_action_limit):
            if time.perf_counter() >= deadline:
                return None
            if count % 30 == 0:
                check_cached()
            response = env.act(action)
            state.update(action, response)
            # 只检查假想环境自己的真值，绝不接触当前测试案例真值。
            audit_state(state, env)
            self.stats["simulation_actions"] += 1
            if state.complete:
                return env.virtual_time_s-start
            action = policy.choose(state)
            if action is None:
                return None
        return None

    def choose(self, state):
        original = self.base.choose(state)
        self.fallback_started = self.base.fallback_started
        if original is None or self.fallback_started or original["reason"] == "near_clear":
            return original
        if (g.distance(state.position, original["position"]) < self.config.min_move_m or
                self.stats["rollout_wall_s"] >= self.config.total_rollout_wall_s):
            return original
        started = time.perf_counter()
        self.stats["decisions"] += 1
        deadline = started + min(self.config.decision_wall_s,
            self.config.total_rollout_wall_s-self.stats["rollout_wall_s"])
        try:
            candidates = self.candidates(state, original)
            if len(candidates) < 2:
                return original
            environments = [sample_environment(state, self.config.sampler_seed+state.actions*37+i)
                            for i in range(self.config.worlds_per_decision)]
            if any(e is None for e in environments):
                self.stats["sampling_failed"] += 1
                return original
            values = []
            for action in candidates:
                costs = []
                for env in environments:
                    cost = self.complete_future(state, env, action, deadline)
                    if cost is None:
                        self.stats["unfinished"] += 1
                        return original  # 不把被截断的后续任务当免费。
                    costs.append(cost)
                values.append(statistics.mean(costs)+self.config.tail_weight*max(costs))
            self.stats["completed_comparisons"] += 1
            winner = min(range(len(values)), key=lambda i: values[i])
            if winner and values[winner] < values[0]*(1-self.config.min_relative_gain):
                self.stats["changed"] += 1
                action = dict(candidates[winner])
                action["reason"] = "rollout_selected"
                action["predicted_remaining_cost"] = values[winner]
                action["base_predicted_remaining_cost"] = values[0]
                return action
            return original
        finally:
            self.stats["rollout_wall_s"] += time.perf_counter()-started
