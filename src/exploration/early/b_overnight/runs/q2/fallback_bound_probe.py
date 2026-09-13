"""只读复算当前默认策略的后备常量、继承触发和37点证书。"""
import hashlib
import inspect
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
NIGHT = ROOT / "experiments" / "b_overnight"
sys.path.insert(0, str(NIGHT))
from astra_guard import check_cached
check_cached()
from q4 import Q4Config, Q4InformationState, Q4Policy, Q4DirectionalPolicy, Q4_ANCHORS
from q4_search import Q4SearchPolicy
from q4_coverage import q4_coverage_certificate, verify_q4_certificate
from task_cost import CompletionCostPolicy, TaskCostPolicy
from route_cost import RouteCostPolicy
from reception import ReceptionPolicy
from rollout import RolloutPolicy
from short_rollout import ShortRolloutPolicy
from policy import BasePolicy, Config
from state import InformationState
import geometry as g

rows = []
classes = [BasePolicy, TaskCostPolicy, CompletionCostPolicy, RouteCostPolicy,
           ReceptionPolicy, RolloutPolicy, ShortRolloutPolicy, Q4Policy,
           Q4DirectionalPolicy, Q4SearchPolicy]
for cls in classes:
    for trigger in ("virtual_budget", "action_limit"):
        policy = cls()
        state = Q4InformationState() if issubclass(cls, Q4Policy) else InformationState()
        if trigger == "virtual_budget":
            state.virtual_time_s = policy.config.adaptive_virtual_budget_s
        else:
            state.actions = policy.config.adaptive_action_limit
        action = policy.choose(state)
        assert policy.fallback_started and "fallback" in action["reason"], (cls.__name__, trigger, action)
        rows.append(dict(policy=cls.__name__, trigger=trigger, action_reason=action["reason"],
                         budget_s=policy.config.adaptive_virtual_budget_s,
                         action_limit=policy.config.adaptive_action_limit))

certificate = q4_coverage_certificate(Q4_ANCHORS)
assert certificate.complete and verify_q4_certificate(certificate)
assert len(Q4_ANCHORS) == 37
row_counts = [sum(1 for i in range(-4, 5) if i * i + i * j + j * j <= 9) for j in range(-3, 4)]
D = Config().domain_radius_m
cell_radius = math.hypot(15, g.STRIP_HALF_WIDTH / 2)
source_rectangle_diagonal = math.hypot(1500, 2 * g.STRIP_HALF_WIDTH)
snake = 2 * 49 * 30 + g.STRIP_HALF_WIDTH
certified_final_jump_bound = 1600.0
assert source_rectangle_diagonal + 20 < certified_final_jump_bound
assert cell_radius < 20 - 1e-5
clear_bound = 16 * (2 * D / 5 + (snake + certified_final_jump_bound) / 5 + 99 * 3 + 5)
bounds = {}
for label, config, anchors, max_actions in [
        ("Q3", Config(), g.ANCHORS, 3000), ("Q4", Q4Config(), Q4_ANCHORS, 5000)]:
    M = len(anchors)
    A = max(math.hypot(*p) for p in anchors)
    # 圆域半径从理论常量向上取整，避免sqrt舍入使上界略偏小。
    A = float(round(A))
    adaptive = config.adaptive_virtual_budget_s + 2 * D / 5 + 6
    discovery = (D + A) / 5 + (M - 1) * 2 * A / 5 + M * 20 * 6
    total = adaptive + discovery + clear_bound
    actions = config.adaptive_action_limit + M * 20 + 16 * 100
    assert total < 360000 and actions < max_actions
    bounds[label] = dict(adaptive_with_overshoot_s=adaptive, discovery_s=discovery,
                        clear_s=clear_bound, total_s=total, total_hours=total / 3600,
                        actions_upper=actions, local_action_limit=max_actions,
                        anchor_count=M, max_anchor_radius_m=A)

files = [ROOT / "experiments" / "b_adaptive_q3" / name for name in
         ("policy.py", "state.py", "geometry.py", "simulation.py")]
files += [NIGHT / name for name in ("q4.py", "q4run.py", "task_cost.py", "runner.py",
                                  "q4_search.py", "rollout.py", "short_rollout.py")]
result = dict(schema="fallback_bound_review_v1", checks=rows, bounds=bounds,
              assumptions=["状态保守包含真源且响应符合题面", "默认或不大于5000米的行动域",
                           "不更改有限后备与预算触发", "现实网络与单次计算时间不在虚拟界内"],
              geometry=dict(cell_radius_m=cell_radius, snake_length_m=snake,
                            rectangle_diagonal_m=source_rectangle_diagonal,
                            certified_final_jump_allowance_m=certified_final_jump_bound,
                            q4_row_counts=row_counts, q4_continuous_certificate_verified=True,
                            max_coordinate_absolute_m=D),
              source_sha256={str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                             for path in files})
path = Path(__file__).with_name("fallback_bound_checks.json")
path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(dict(trigger_checks=len(rows), bounds=bounds, geometry=result["geometry"]),
                 ensure_ascii=False, indent=2))
