"""夜间多方向统一评估。冻结原型不改，策略接口共享。"""
import argparse
import hashlib
import json
import math
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent / "b_adaptive_q3"
sys.path.insert(0, str(BASE))
from policy import BasePolicy, Config
from simulation import LocalEnvironment, Scenario, generate
from state import InformationState, audit_state
from astra_guard import check_cached


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def factories(name, overrides=None):
    overrides = overrides or {}
    if name == "baseline":
        return lambda: BasePolicy(Config(**overrides)), InformationState
    if name == "committed_baseline":
        from batch_commitment import CommittedBasePolicy
        return lambda: CommittedBasePolicy(Config(**overrides)), InformationState
    if name in ("configured", "refined"):
        from task_cost import CompletionCostConfig, CompletionCostPolicy
        return lambda: CompletionCostPolicy(CompletionCostConfig(**overrides)), InformationState
    if name in ("range_completion", "range_configured"):
        from task_cost import CompletionCostConfig, CompletionCostPolicy
        from range_state import RangeOrderInformationState
        return lambda: CompletionCostPolicy(CompletionCostConfig(**overrides)), RangeOrderInformationState
    if name == "reception":
        from reception import ReceptionConfig, ReceptionPolicy
        return lambda: ReceptionPolicy(ReceptionConfig(**overrides)), InformationState
    if name == "short_rollout":
        from short_rollout import ShortRolloutConfig, ShortRolloutPolicy
        return lambda: ShortRolloutPolicy(ShortRolloutConfig(**overrides)), InformationState
    if name == "full_completion_rollout":
        from short_rollout import ShortRolloutConfig, ShortRolloutPolicy
        values = dict(planning_prefix_actions=2000, future_action_limit=2000,
                      decision_wall_s=45., total_rollout_wall_s=180., max_decisions=6)
        values.update(overrides)
        return lambda: ShortRolloutPolicy(ShortRolloutConfig(**values)), InformationState
    if name == "shared_completion":
        from shared_completion import SharedCompletionConfig, SharedCompletionPolicy
        return lambda: SharedCompletionPolicy(SharedCompletionConfig(**overrides)), InformationState
    if name == "bisect":
        from center_refinement import BisectConfig, BisectPolicy
        return lambda: BisectPolicy(BisectConfig(**overrides)), InformationState
    if name == "sweep":
        from sweep_policy import Q3SweepPolicy
        from task_cost import CompletionCostConfig
        return lambda: Q3SweepPolicy(CompletionCostConfig(**overrides)), InformationState
    if name == "coverage":
        from coverage import CoverageInformationState, CoveragePolicyMixin
        class Policy(CoveragePolicyMixin, BasePolicy):
            pass
        return lambda: Policy(Config(**overrides)), CoverageInformationState
    if name in ("task_cost", "coverage_cost", "completion", "coverage_completion"):
        from task_cost import TaskCostConfig, TaskCostPolicy, CompletionCostConfig, CompletionCostPolicy
        use_completion = "completion" in name
        core_cls = CompletionCostPolicy if use_completion else TaskCostPolicy
        config_cls = CompletionCostConfig if use_completion else TaskCostConfig
        policy_cls, state_cls = core_cls, InformationState
        if name.startswith("coverage_"):
            from coverage import CoverageInformationState, CoveragePolicyMixin
            class Policy(CoveragePolicyMixin, core_cls):
                pass
            policy_cls, state_cls = Policy, CoverageInformationState
        return lambda: policy_cls(config_cls(**overrides)), state_cls
    if name in ("rollout", "coverage_rollout"):
        from rollout import RolloutConfig, RolloutPolicy
        state_cls = InformationState
        if name == "coverage_rollout":
            from coverage import CoverageInformationState
            state_cls = CoverageInformationState
        return lambda: RolloutPolicy(RolloutConfig(**overrides), use_coverage=name == "coverage_rollout"), state_cls
    raise ValueError(name)


def run_case(scenario, name, config=None, trace_path=None, max_wall_s=1200):
    check_cached()
    make_policy, make_state = factories(name, config)
    policy, state, env = make_policy(), make_state(), LocalEnvironment(scenario)
    if any(s.orientation is not None for s in scenario.sources):
        raise ValueError("Q3 驱动不能处理定向源")
    started, planning, checking = time.perf_counter(), 0.0, 0.0
    rows, error = [], None
    ledger = dict(move_s=0.0, switch_s=0.0, measure_s=0.0, clear_s=0.0)
    previous, channel = (0, 0), 1
    state.action_history = []
    try:
        while not state.complete:
            if len(rows) % 10 == 0:
                check_cached()
            if len(rows) >= 3000 or time.perf_counter()-started > max_wall_s:
                raise TimeoutError("整局动作或现实耗时上限")
            t = time.perf_counter()
            action = policy.choose(state)
            planning += time.perf_counter()-t
            assert action is not None and math.hypot(*action["position"]) <= 5000 + 1e-6
            response = env.act(action)
            row = dict(step=len(rows)+1, **action, response=response)
            rows.append(row)
            q, j = action["position"], action["channel"]
            ledger["move_s"] += math.hypot(q[0]-previous[0], q[1]-previous[1])/5
            if action["kind"] == "measure":
                ledger["switch_s"] += int(j != channel)
                ledger["measure_s"] += 5
                channel = j
            else:
                ledger["clear_s"] += 5 if response["clear_result"] == "success" else 3
            previous = q
            assert abs(sum(ledger.values()) - env.virtual_time_s) < 1e-5
            t = time.perf_counter()
            state.update(action, response)
            state.action_history.append(row)
            audit_state(state, env)
            checking += time.perf_counter()-t
            assert env.virtual_time_s <= 100*3600
    except Exception:
        error = traceback.format_exc()
    if trace_path:
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        with trace_path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False)+"\n")
    measures = [r for r in rows if r["kind"] == "measure"]
    return dict(case=scenario.name, seed=scenario.seed, layout=scenario.layout, noise=scenario.noise,
        policy=name, source_count=len(scenario.sources), cleared=len(env.cleared),
        success=error is None and state.complete, error=error,
        virtual_time_s=env.virtual_time_s, wall_time_s=time.perf_counter()-started,
        planning_s=planning, checking_s=checking, actions=len(rows),
        measure_count=len(measures), scan_position_count=len({tuple(r["position"]) for r in measures}),
        failed_clears=sum(r["kind"] == "clear" and r["response"]["clear_result"] != "success" for r in rows),
        cleared_ratio=len(env.cleared)/len(scenario.sources),
        average_localization_clear_s=env.virtual_time_s/len(env.cleared) if env.cleared else None,
        fallback=policy.fallback_started, policy_stats=getattr(policy, "stats", {}), **ledger)


def make_cases(base_seed, repeats):
    pairs = [(layout, noise) for layout in ("uniform", "edge", "cluster", "line")
             for noise in ("smooth", "biased", "hashed") for _ in range(repeats)]
    return [generate(base_seed+i, layout, noise) for i, (layout, noise) in enumerate(pairs)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--policies", nargs="+", required=True)
    parser.add_argument("--seed", type=int, default=20100)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--cases", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    check_cached()
    out = args.output.resolve()
    if ROOT not in out.parents:
        raise ValueError("产物必须在夜间实验目录内")
    out.mkdir(parents=True, exist_ok=False)
    scenes = [Scenario.from_dict(s) for s in json.loads(args.cases.read_text(encoding="utf-8"))] if args.cases else make_cases(args.seed, args.repeats)
    scenes = scenes[:args.limit] if args.limit else scenes
    configs = json.loads(args.config.read_text(encoding="utf-8")) if args.config else {}
    dump(out / "cases.json", [s.to_dict() for s in scenes])
    dump(out / "configs.json", configs)
    versions = {}
    for folder, prefix in ((BASE, "base"), (ROOT, "night")):
        for p in folder.glob("*.py"):
            if p.name == "astra_guard.py":
                continue
            relative = f"{prefix}/{p.name}"
            data = p.read_bytes()
            versions[relative] = hashlib.sha256(data).hexdigest()
            dest = out / "source" / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
    dump(out / "manifest.json", dict(created_at=time.time(), python=sys.version, policies=args.policies,
        code_sha256=versions, cases_sha256=hashlib.sha256((out/"cases.json").read_bytes()).hexdigest(),
        interpretation="本地开发或验证案例；不是官方分布，不保证稀有失败率"))
    results = []
    for scene in scenes:
        for name in args.policies:
            check_cached()
            result = run_case(scene, name, configs.get(name), out/"actions"/f"{scene.name}_{name}.jsonl")
            results.append(result)
            dump(out/"results.json", results)
            print(json.dumps(result, ensure_ascii=False), flush=True)
            if result["error"] and "ASTRA_STOP" in result["error"]:
                raise SystemExit(3)
    if not all(r["success"] for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
