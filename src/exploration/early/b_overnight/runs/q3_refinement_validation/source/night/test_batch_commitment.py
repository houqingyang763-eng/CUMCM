"""批次履约行为契约与完整局配对。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import unittest

from batch_commitment import BatchCommitmentMixin, CommittedBasePolicy, CommittedCompletionPolicy, natural_batch_fulfilment
from policy import BasePolicy, Config
from task_cost import CompletionCostConfig, CompletionCostPolicy
from state import InformationState
from astra_guard import check_cached

ROOT = Path(__file__).resolve().parent


class ScriptedPolicy(BasePolicy):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls = 0

    def choose(self, state):
        self.calls += 1
        if self.calls == 1:
            return self.action("measure", (100, 0), 1, "scripted", planned_channels=[1, 3, 5])
        return self.action("measure", (200, 0), 20, "scripted_next")


class WrappedScript(BatchCommitmentMixin, ScriptedPolicy):
    pass


def apply_response(state, action, result="no_signal"):
    response = dict(accepted=True, virtual_time_s=state.virtual_time_s + 5)
    response["measure_result" if action["kind"] == "measure" else "clear_result"] = result
    state.update(action, response)


class BatchChecks(unittest.TestCase):
    def test_commits_only_true_plan_and_requires_feedback(self):
        state, policy = InformationState(), WrappedScript()
        first = policy.choose(state)
        self.assertEqual(policy.choose(state), first)
        self.assertEqual(policy.calls, 1)
        apply_response(state, first)
        second = policy.choose(state)
        self.assertEqual(second["channel"], 3)
        self.assertEqual(second["position"], (100, 0))
        apply_response(state, second)
        self.assertEqual(policy.choose(state)["channel"], 5)

    def test_skips_terminal_and_already_measured_channels(self):
        state, policy = InformationState(), WrappedScript()
        apply_response(state, policy.choose(state))
        state.channels[3].status = "absent"
        state.channels[5].measured.add((100, 0))
        self.assertEqual(policy.choose(state)["channel"], 20)
        self.assertEqual(policy.batch_stats["skipped_terminal"], 1)

    def test_near_clear_is_in_place_and_queue_resumes(self):
        state, policy = InformationState(), WrappedScript()
        apply_response(state, policy.choose(state), "near")
        clear = policy.choose(state)
        self.assertEqual((clear["kind"], clear["position"], clear["channel"]), ("clear", (100, 0), 1))
        apply_response(state, clear, "success")
        self.assertEqual(policy.choose(state)["channel"], 3)

    def test_protection_preempts_commitment(self):
        state, policy = InformationState(), CommittedBasePolicy(Config(adaptive_action_limit=1))
        apply_response(state, policy.choose(state))
        action = policy.choose(state)
        self.assertTrue(action["reason"].startswith("fallback"))
        self.assertTrue(policy.fallback_started)
        self.assertEqual(policy.batch_stats["cancelled_protection"], 1)

    def test_external_position_change_does_not_force_return(self):
        state, policy = InformationState(), WrappedScript()
        apply_response(state, policy.choose(state))
        state.position = (500, 0)
        state.actions += 1
        self.assertEqual(policy.choose(state)["position"], (200, 0))
        self.assertEqual(policy.batch_stats["cancelled_position"], 1)


def snapshot(out):
    paths = [ROOT / name for name in ("batch_commitment.py", "test_batch_commitment.py", "task_cost.py", "q4.py", "q4run.py",
                                    "q4_anchor_design.py", "q4_coverage.py", "coverage.py")]
    paths += list((ROOT.parent / "b_adaptive_q3").glob("*.py"))
    hashes = {}
    for path in paths:
        key = path.relative_to(ROOT.parent)
        data = path.read_bytes()
        hashes[str(key)] = hashlib.sha256(data).hexdigest()
        dest = out / "source" / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    return hashes


def batch(out):
    import run_local
    from simulation import generate
    from q4run import generate_q4, run_case as run_q4
    from q4_anchor_design import Q4ReducedAnchorPolicy
    from q4_coverage import Q4CoverageInformationState
    from q4 import Q4Config
    class CommittedQ4(BatchCommitmentMixin, Q4ReducedAnchorPolicy):
        pass
    check_cached()
    out = out.resolve()
    if ROOT / "runs" / "batch_commitment" not in out.parents:
        raise ValueError("输出必须放 runs/batch_commitment 子目录")
    out.mkdir(parents=True, exist_ok=False)
    cases = [generate(43100 + i, layout, noise) for i, (layout, noise) in enumerate(
        [("uniform", "smooth"), ("edge", "biased"), ("cluster", "hashed"), ("line", "hashed")])]
    scene4 = generate_q4(43110, "uniform", "smooth", "random")
    run_local.write_json(out / "cases.json", [case.to_dict() for case in cases] + [scene4.to_dict()])
    run_local.write_json(out / "configs.json", {"base": Config().to_dict(), "completion": CompletionCostConfig().to_dict(), "q4": Q4Config().to_dict()})
    run_local.write_json(out / "manifest.json", dict(code_sha256=snapshot(out), created_at=time.time(), python=sys.version,
                                                    purpose="两个Q3策略行为契约的四布局完整对照及一个Q4新例"))
    results = []
    for case in cases:
        for label, cls, config in [("base", BasePolicy, Config()), ("committed_base", CommittedBasePolicy, Config()),
                                   ("completion", CompletionCostPolicy, CompletionCostConfig()),
                                   ("committed_completion", CommittedCompletionPolicy, CompletionCostConfig())]:
            check_cached()
            instances = []
            def make(configuration=None, reference_only=False):
                instance = cls(configuration, reference_only)
                instances.append(instance)
                return instance
            run_local.BasePolicy = make
            trace = out / "actions" / f"{case.name}_{label}.jsonl"
            trace.parent.mkdir(exist_ok=True)
            result = run_local.run_case(case, config, trace_path=trace)
            result["policy"] = label
            result["batch_stats"] = getattr(instances[-1], "batch_stats", {})
            rows = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
            result["natural_fulfilment"] = natural_batch_fulfilment(rows, InformationState)
            results.append(result)
            run_local.write_json(out / "results.json", results)
            run_local.report(results, out)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    for label, cls in [("q4_31", Q4ReducedAnchorPolicy), ("committed_q4_31", CommittedQ4)]:
        check_cached()
        instances = []
        def make(configuration=None):
            instance = cls(configuration)
            instances.append(instance)
            return instance
        trace = out / "actions" / f"{scene4.name}_{label}.jsonl"
        result = run_q4(scene4, label, trace, policy_factory=make, state_factory=Q4CoverageInformationState)
        result["batch_stats"] = getattr(instances[-1], "batch_stats", {})
        rows = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
        result["natural_fulfilment"] = natural_batch_fulfilment(rows, Q4CoverageInformationState)
        results.append(result)
        run_local.write_json(out / "results.json", results)
        print(json.dumps({k: v for k, v in result.items() if k != "absence_proofs"}, ensure_ascii=False), flush=True)
    if not all(row["success"] for row in results):
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=Path)
    args, rest = parser.parse_known_args()
    if args.batch:
        batch(args.batch)
    else:
        unittest.main(argv=[sys.argv[0], *rest], verbosity=2)
