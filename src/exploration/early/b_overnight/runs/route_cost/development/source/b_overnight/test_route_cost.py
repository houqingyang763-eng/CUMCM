"""路线机制构造检查与四类完整开发对照。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import unittest

from route_cost import RouteCostConfig, RouteCostPolicy, nearest_neighbor_routes, open_route_length, g
from task_cost import CompletionCostConfig, CompletionCostPolicy
from state import ChannelState, InformationState
from astra_guard import check_cached

ROOT = Path(__file__).resolve().parent


class RouteChecks(unittest.TestCase):
    def test_open_routes_visit_every_target_once(self):
        points = [(0, 100), (100, 0), (200, 100), (100, 200)]
        for order, length in nearest_neighbor_routes(points):
            self.assertEqual(sorted(order), list(range(4)))
            recomputed = sum(g.distance(points[a], points[b]) for a, b in zip(order, order[1:]))
            self.assertAlmostEqual(length, recomputed)

    def test_two_target_route_hand_calculation(self):
        length, order = open_route_length((0, 0), [(100, 0), (0, 100)])
        self.assertAlmostEqual(length, 100 + math.sqrt(20000))
        self.assertEqual(len(order), 2)
        self.assertEqual(open_route_length((0, 0), [])[0], 0)

    def test_trial_clear_retains_nonzero_failure_work(self):
        state = InformationState()
        for c in state.channels.values():
            c.status = "absent"
        c = ChannelState(1, status="found", polygon=[(0, -10), (90, -10), (90, 10), (0, 10)], first=((0, 0), 0))
        state.channels[1] = c
        policy = RouteCostPolicy()
        q = c.possible_cells()[0]["position"]
        before = len(c.possible_cells())
        cost, detail = policy.estimated_total(state, dict(kind="clear", position=q, channel=1))
        self.assertEqual(detail["clear_assumption"], "failure")
        self.assertEqual(detail["remaining_target_count"], 1)
        self.assertGreaterEqual(detail["remaining_work_s"], 5)
        self.assertEqual(len(c.possible_cells()), before)
        self.assertEqual(c.exclusions, [])

    def test_certified_clear_removes_only_its_own_work(self):
        state = InformationState()
        for c in state.channels.values():
            c.status = "absent"
        for j, x in ((1, 0), (2, 100)):
            state.channels[j] = ChannelState(j, status="found", polygon=[(x - 1, -1), (x + 1, -1), (x + 1, 1), (x - 1, 1)])
        cost, detail = RouteCostPolicy().estimated_total(state, dict(kind="clear", position=(0, 0), channel=1))
        self.assertEqual(detail["remaining_target_count"], 1)
        self.assertEqual(detail["remaining_work_s"], 5)
        self.assertAlmostEqual(cost, 5 + 100 / 5 + 5)


def smoke(out):
    import run_local
    from simulation import generate
    check_cached()
    out = out.resolve()
    if ROOT / "runs" / "route_cost" not in out.parents:
        raise ValueError("输出只允许 runs/route_cost 子目录")
    out.mkdir(parents=True, exist_ok=False)
    cases = [generate(41100 + i, layout, noise) for i, (layout, noise) in enumerate(
        [("uniform", "smooth"), ("edge", "biased"), ("cluster", "hashed"), ("line", "hashed")])]
    run_local.write_json(out / "cases.json", [case.to_dict() for case in cases])
    run_local.write_json(out / "configs.json", {"completion": CompletionCostConfig().to_dict(), "route": RouteCostConfig().to_dict()})
    paths = [ROOT / "route_cost.py", ROOT / "test_route_cost.py", ROOT / "task_cost.py", *run_local.ROOT.glob("*.py")]
    hashes = {}
    for path in paths:
        key = str(path.relative_to(ROOT.parent))
        data = path.read_bytes()
        hashes[key] = hashlib.sha256(data).hexdigest()
        dest = out / "source" / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    run_local.write_json(out / "manifest.json", {"code_sha256": hashes, "purpose": "四类本地开发对照", "created_at": time.time(), "python": sys.version})
    results = []
    for case in cases:
        for label, cls, config in [("completion", CompletionCostPolicy, CompletionCostConfig()), ("route", RouteCostPolicy, RouteCostConfig())]:
            check_cached()
            instances = []
            def make_policy(configuration=None, reference_only=False):
                instance = cls(configuration, reference_only)
                instances.append(instance)
                return instance
            run_local.BasePolicy = make_policy
            trace = out / "actions" / f"{case.name}_{label}.jsonl"
            trace.parent.mkdir(exist_ok=True)
            result = run_local.run_case(case, config, trace_path=trace)
            result["policy"] = label
            result["policy_stats"] = getattr(instances[-1], "stats", {})
            results.append(result)
            run_local.write_json(out / "results.json", results)
            run_local.report(results, out)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    if not all(row["success"] for row in results):
        raise SystemExit(1)


if __name__ == "__main__":
    import math
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", type=Path)
    args, rest = parser.parse_known_args()
    if args.smoke:
        smoke(args.smoke)
    else:
        unittest.main(argv=[sys.argv[0], *rest], verbosity=2)
