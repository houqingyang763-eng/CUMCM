"""绕路插入的少量机制检查、已知反例回放及四新布局整局对照。"""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time
import unittest
from unittest.mock import patch

from sweep_detour import Q3DetourSweepPolicy, insertion_cost, later_insertion_cost, g
from sweep_policy import Q3SweepPolicy
from task_cost import CompletionCostConfig, CompletionCostPolicy
from state import InformationState
from simulation import Scenario, generate
from astra_guard import check_cached
import runner

ROOT = Path(__file__).resolve().parent


class DetourChecks(unittest.TestCase):
    def test_route_insertion_comparison_has_meter_units(self):
        self.assertEqual(insertion_cost((0, 0), (100, 0), (50, 0)), 0)
        self.assertEqual(later_insertion_cost([(100, 0), (200, 0)], (150, 0)), 0)
        self.assertEqual(insertion_cost((0, 0), (100, 0), (0, 100)), 100 * 2**.5)

    def test_only_certified_clear_can_replace_sweep(self):
        state, policy = InformationState(), Q3DetourSweepPolicy()
        state.channels[1].status = "found"
        raw = dict(kind="measure", position=(1200., 0.), channel=2, reason="sweep_next_discovery_node")
        clear = dict(kind="clear", position=(100., 0.), channel=1, reason="completion_cell_clear")
        for radius, expected in ((40, "sweep_next_discovery_node"), (2, "sweep_detour_certified_clear")):
            state.channels[1].polygon = g.outer_disk((100., 0.), radius)
            state.channels[1].invalidate()
            with patch.object(Q3SweepPolicy, "choose", return_value=raw), patch.object(CompletionCostPolicy, "choose", return_value=clear):
                self.assertEqual(policy.choose(state)["reason"], expected)

    def test_reserved_anchor_is_not_changed_after_last_known_target_clears(self):
        state, policy = InformationState(), Q3DetourSweepPolicy()
        state.position = (10., 10.)
        policy._reserved_anchor = g.ANCHORS[4]
        self.assertEqual(policy.choose(state)["position"], g.ANCHORS[4])

    def test_protection_overrides_detour(self):
        state, policy = InformationState(), Q3DetourSweepPolicy(CompletionCostConfig(adaptive_action_limit=0))
        action = policy.choose(state)
        self.assertTrue(policy.fallback_started)
        self.assertTrue(action["reason"].startswith("fallback"))


def batch(out):
    check_cached()
    out = out.resolve()
    if ROOT / "runs" not in out.parents:
        raise ValueError("输出必须在本夜runs")
    out.mkdir(parents=True, exist_ok=False)
    old = json.loads((ROOT / "runs/q3_sweep_validation/cases.json").read_text(encoding="utf-8"))
    counterexample = Scenario.from_dict(next(c for c in old if c["name"] == "line_biased_48110"))
    scenes = [generate(97100+i, layout, noise) for i, (layout, noise) in enumerate(
        (("uniform", "smooth"), ("edge", "biased"), ("cluster", "hashed"), ("line", "biased")))]
    runner.dump(out / "cases.json", [s.to_dict() for s in [counterexample, *scenes]])
    runner.dump(out / "config.json", CompletionCostConfig().to_dict())
    versions = {}
    for folder, prefix in ((ROOT, "night"), (ROOT.parent / "b_adaptive_q3", "base")):
        for path in folder.glob("*.py"):
            data = path.read_bytes()
            relative = f"{prefix}/{path.name}"
            versions[relative] = hashlib.sha256(data).hexdigest()
            dest = out / "source" / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
    runner.dump(out / "manifest.json", dict(created_at=time.time(), python=sys.version, code_sha256=versions,
        known_counterexample="line_biased_48110", new_seed_base=97100,
        model_fixed_before_execution=True, purpose="一个绕路插入机制，已知反例一次和四新布局三策略对照"))
    original = runner.factories
    def factories(name, config=None):
        if name == "detour_sweep":
            return lambda: Q3DetourSweepPolicy(CompletionCostConfig(**(config or {}))), InformationState
        return original(name, config)
    runner.factories = factories
    results = []
    try:
        runs = [(counterexample, "detour_sweep")]
        for i, scene in enumerate(scenes):
            labels = ["sweep", "detour_sweep", "completion"]
            runs += [(scene, label) for label in labels[i % 3:] + labels[:i % 3]]
        for scene, label in runs:
            check_cached()
            result = runner.run_case(scene, label, trace_path=out / "actions" / f"{scene.name}_{label}.jsonl")
            results.append(result)
            runner.dump(out / "results.json", results)
            print(json.dumps(result, ensure_ascii=False), flush=True)
            if result["error"] and "ASTRA_STOP" in result["error"]:
                raise SystemExit(3)
    finally:
        runner.factories = original
        fresh = [r for r in results if r["case"] != counterexample.name]
        groups = {}
        for label in ("sweep", "detour_sweep", "completion"):
            selected = [r for r in fresh if r["policy"] == label]
            if selected:
                groups[label] = dict(cases=len(selected), all_success=all(r["success"] for r in selected),
                    mean_s=statistics.mean(r["virtual_time_s"] for r in selected), worst_s=max(r["virtual_time_s"] for r in selected),
                    wall_total_s=sum(r["wall_time_s"] for r in selected), failed_clears=sum(r["failed_clears"] for r in selected))
        runner.dump(out / "analysis.json", dict(complete=len(results)==13 and all(r["success"] for r in results),
                                               known_counterexample=results[:1], fresh_groups=groups))
    for name in ("sweep_detour.py", "sweep_policy.py", "task_cost.py"):
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == versions[f"night/{name}"]
    if len(results) != 13 or not all(r["success"] for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=Path)
    args, rest = parser.parse_known_args()
    if args.batch:
        batch(args.batch)
    else:
        unittest.main(argv=[sys.argv[0], *rest], verbosity=2)
