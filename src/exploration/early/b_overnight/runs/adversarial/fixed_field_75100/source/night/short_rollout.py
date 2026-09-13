"""限制复杂规划的前瞻：短段主动策略 + 完整有限后备，不免除未完任务。"""
import copy
from dataclasses import dataclass
import statistics
import time

from rollout import RolloutConfig, RolloutPolicy
from worlds import sample_environment
from task_cost import CompletionCostPolicy, CompletionCostConfig
from policy import BasePolicy
from state import audit_state
from astra_guard import check_cached
import geometry as g


@dataclass(frozen=True)
class ShortRolloutConfig(RolloutConfig):
    planning_prefix_actions: int = 8
    max_decisions: int = 10
    decision_wall_s: float = 10.
    total_rollout_wall_s: float = 90.
    future_action_limit: int = 2000
    min_relative_gain: float = .05


class ShortRolloutPolicy(RolloutPolicy):
    def __init__(self, config=None):
        super().__init__(config or ShortRolloutConfig())
        self.stats["fallback_simulation_actions"] = 0

    def make_base(self):
        return CompletionCostPolicy(CompletionCostConfig())

    def complete_future(self, state, environment, first_action, deadline):
        state, env = copy.deepcopy(state), copy.deepcopy(environment)
        policy = self.make_base()
        terminal = BasePolicy(reference_only=True)
        start = env.virtual_time_s
        action = first_action
        for count in range(self.config.future_action_limit):
            if time.perf_counter() >= deadline:
                return None
            if count % 30 == 0:
                check_cached()
            response = env.act(action)
            state.update(action, response)
            audit_state(state, env)
            self.stats["simulation_actions"] += 1
            if state.complete:
                return env.virtual_time_s - start
            if count + 1 >= self.config.planning_prefix_actions:
                action = terminal.choose(state)
                self.stats["fallback_simulation_actions"] += 1
            else:
                action = policy.choose(state)
            if action is None:
                return None
        return None

    def choose(self, state):
        original = self.base.choose(state)
        self.fallback_started = self.base.fallback_started
        if (original is None or self.fallback_started or
            self.stats["decisions"] >= self.config.max_decisions or
            g.distance(state.position, original["position"]) < self.config.min_move_m or
            self.stats["rollout_wall_s"] >= self.config.total_rollout_wall_s):
            return original
        started = time.perf_counter()
        self.stats["decisions"] += 1
        deadline = started + min(self.config.decision_wall_s,
            self.config.total_rollout_wall_s - self.stats["rollout_wall_s"])
        try:
            candidates = self.candidates(state, original)
            if len(candidates) < 2:
                return original
            modes = ("minimum", "maximum")
            columns = [[] for _ in candidates]
            for i, mode in enumerate(modes):
                env = sample_environment(state, self.config.sampler_seed + 37 * state.actions + i, mode)
                if env is None:
                    self.stats["sampling_failed"] += 1
                    return original
                costs = [self.complete_future(state, env, action, deadline) for action in candidates]
                if any(v is None for v in costs):
                    self.stats["unfinished"] += 1
                    return original
                for column, cost in zip(columns, costs):
                    column.append(cost)
            self.stats["completed_comparisons"] += 1
            # 候选必须在两种数量解释下都不比原动作差，再比较平均+较差局费用。
            eligible = [0] + [i for i in range(1, len(columns))
                              if all(a <= b for a, b in zip(columns[i], columns[0]))]
            values = [statistics.mean(c) + self.config.tail_weight * max(c) for c in columns]
            winner = min(eligible, key=lambda i: values[i])
            if winner and values[winner] < values[0] * (1 - self.config.min_relative_gain):
                self.stats["changed"] += 1
                result = dict(candidates[winner])
                result.update(reason="short_planning_rollout", predicted_remaining_cost=values[winner],
                              base_predicted_remaining_cost=values[0], compared_worlds=2,
                              forecast=("全部后续使用Completion模拟至全清" if self.config.planning_prefix_actions >= self.config.future_action_limit
                                        else f"{self.config.planning_prefix_actions}个主动动作后切换有限后备，仍模拟至全清"))
                return result
            return original
        finally:
            self.stats["rollout_wall_s"] += time.perf_counter() - started
