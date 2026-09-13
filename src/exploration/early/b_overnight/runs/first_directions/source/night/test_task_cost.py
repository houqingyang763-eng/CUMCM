"""任务成本机制的解析构造检查与少量完整本地开发局。"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import unittest

from task_cost import TaskCostConfig, TaskCostPolicy, g
from state import ChannelState, InformationState


class TaskCostChecks(unittest.TestCase):
    def strip(self):
        return ChannelState(1, status="found", polygon=[(0, -10), (900, -10), (900, 10), (0, 10)], first=((0, 0), 0))

    def test_cross_bearing_saves_more_work_than_collinear(self):
        c, policy = self.strip(), TaskCostPolicy()
        self.assertGreater(policy.utility(c, (450, 200), 0), policy.utility(c, (-100, 0), 0))

    def test_no_speculative_reception_beyond_minimum_radius(self):
        c, policy = self.strip(), TaskCostPolicy()
        self.assertEqual(policy.utility(c, (-2000, 0), 0), 0)

    def test_certified_circle_needs_no_further_measurement(self):
        c = ChannelState(1, status="found", polygon=[(99, -1), (101, -1), (101, 1), (99, 1)])
        policy = TaskCostPolicy()
        self.assertEqual(policy.remaining_work(c), 5)
        self.assertEqual(policy.utility(c, (0, 0), 0), 0)

    def test_detour_is_zero_on_path_and_positive_off_path(self):
        state, policy = InformationState(), TaskCostPolicy()
        state.channels[1] = self.strip()
        self.assertAlmostEqual(policy._detour(state, (200, 0), [1]), 0)
        self.assertGreater(policy._detour(state, (200, 200), [1]), 0)

    def test_heuristics_do_not_update_evidence(self):
        state, policy = InformationState(), TaskCostPolicy()
        c = self.strip()
        state.channels[1] = c
        original_polygon = list(c.polygon)
        original_exclusions = list(c.exclusions)
        policy.choose(state)
        self.assertEqual(c.polygon, original_polygon)
        self.assertEqual(c.exclusions, original_exclusions)
        self.assertEqual(c.status, "found")
        self.assertEqual(state.actions, 0)


def smoke(output):
    import run_local
    from policy import BasePolicy, Config
    from simulation import generate
    root = Path(__file__).resolve().parent
    output = output.resolve()
    if root / "runs" / "task_cost" not in output.parents:
        raise ValueError("运行输出只允许 runs/task_cost 子目录")
    output.mkdir(parents=True, exist_ok=False)
    (output / "actions").mkdir()
    cases = [generate(seed, layout, noise) for seed, layout, noise in
             [(101, "edge", "biased"), (102, "cluster", "smooth"), (103, "line", "hashed")]]
    run_local.write_json(output / "cases.json", [case.to_dict() for case in cases])
    run_local.write_json(output / "config.json", TaskCostConfig().to_dict())
    run_local.write_json(output / "manifest.json", {
        "purpose": "已有冒烟案例开发对照，非未见数据",
        "source_sha256": {str(p.relative_to(root.parent)): run_local.digest(p) for p in
                          [root / "task_cost.py", root / "test_task_cost.py", *run_local.ROOT.glob("*.py")]}})
    results = []
    for case in cases:
        for label, cls, config in [("baseline", BasePolicy, Config()), ("task_cost", TaskCostPolicy, TaskCostConfig())]:
            subprocess.run([sys.executable, str(root / "astra_guard.py"), "check"], check=True, stdout=subprocess.DEVNULL)
            run_local.BasePolicy = cls
            result = run_local.run_case(case, config, trace_path=output / "actions" / f"{case.name}_{label}.jsonl")
            result["policy"] = label
            results.append(result)
            run_local.write_json(output / "results.json", results)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    run_local.report(results, output)
    if not all(row["success"] for row in results):
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", type=Path)
    args, rest = parser.parse_known_args()
    if args.smoke:
        smoke(args.smoke)
    else:
        unittest.main(argv=[sys.argv[0], *rest], verbosity=2)
