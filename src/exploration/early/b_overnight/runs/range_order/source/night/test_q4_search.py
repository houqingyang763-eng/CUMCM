"""Q4 动态角隙搜索的构造检查和四布局完整对照。"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time
import unittest

from q4_search import (Q4SearchConfig, Q4SearchPolicy, Q4CoverageInformationState,
                       orientation_rows, oriented_gain, residual_work_fraction,
                       interval_direction)
from q4 import Q4_ANCHORS, Q4DirectionalPolicy, Q4InformationState
import geometry as g


def center_row(negatives):
    return next(row for row in orientation_rows(negatives) if row[0] == (0, 0))


class SearchTests(unittest.TestCase):
    def test_work_proxy_has_explicit_seconds_scale(self):
        self.assertEqual(Q4SearchConfig().search_work_s, 37 * (5 + 1))
        self.assertAlmostEqual(residual_work_fraction(()), 1)

    def test_negative_east_leaves_west_emission_directions(self):
        row = center_row(((500, 0),))
        self.assertEqual(row[2], ((90.0, 270.0),))
        self.assertAlmostEqual(interval_direction(row[2], 0), math.pi)

    def test_repeating_same_site_does_not_create_gain(self):
        self.assertAlmostEqual(oriented_gain(((500, 0),), (500, 0)), 0)
        self.assertGreater(oriented_gain(((500, 0),), (-500, 0)), 0)

    def test_far_negative_does_not_remove_center_orientations(self):
        row = center_row(((1500, 0),))
        self.assertEqual(row[2], ((0.0, 360.0),))

    def test_orientation_mass_is_monotone_under_extra_negatives(self):
        points = [(0, 0), (900, 0), (-900, 0), (0, 900), (0, -900)]
        values = [residual_work_fraction(tuple(sorted(points[:k]))) for k in range(6)]
        self.assertTrue(all(a >= b - 1e-12 for a, b in zip(values, values[1:])))
        self.assertGreaterEqual(values[-1], 0)

    def test_utility_scales_as_seconds_and_ignores_sampling_stop(self):
        state = Q4CoverageInformationState()
        state.channels[1].sample_mask = 0
        a = Q4SearchPolicy(Q4SearchConfig(search_work_s=222))
        b = Q4SearchPolicy(Q4SearchConfig(search_work_s=444))
        a._prepare(state)
        b._prepare(state)
        self.assertGreater(a.utility(state.channels[1], (0, 0), 0), 0)
        self.assertAlmostEqual(b.utility(state.channels[1], (0, 0), 0),
                               2 * a.utility(state.channels[1], (0, 0), 0))
        self.assertFalse(state.complete)
        self.assertEqual(state.channels[1].status, "unknown")

    def test_dynamic_candidates_include_non_anchor_gap_points(self):
        state, policy = Q4CoverageInformationState(), Q4SearchPolicy()
        for j in state.channels:
            if j != 1:
                state.channels[j].status = "absent"
        state.update(dict(kind="measure", position=(0, 0), channel=1),
                     dict(accepted=True, measure_result="no_signal", virtual_time_s=5))
        policy._prepare(state)
        points = policy.candidate_positions(state)
        self.assertTrue(any(all(g.distance(q, anchor) > 1 for anchor in Q4_ANCHORS) for q in points))
        self.assertTrue(all(math.hypot(*q) <= 5000 for q in points))

    def test_backside_true_direction_retained_at_center(self):
        row = center_row(((-500, 0), (-500, 500), (1500, 0)))
        self.assertTrue(any(a <= theta <= b for a, b in row[2] for theta in (0, 360)))


def batch(output, seed):
    from astra_guard import check_cached
    from q4run import dump, generate_q4, report, run_case
    check_cached()
    root = Path(__file__).resolve().parent
    output = output.resolve()
    allowed = root / "runs" / "q4_search"
    if output != allowed and allowed not in output.parents:
        raise ValueError("Q4 搜索结果只能放 runs/q4_search/")
    output.mkdir(parents=True, exist_ok=False)
    specs = [("uniform", "smooth", "random"), ("edge", "biased", "outward"),
             ("cluster", "hashed", "tangent"), ("line", "hashed", "aligned")]
    scenes = [generate_q4(seed + i, *spec) for i, spec in enumerate(specs)]
    dump(output / "cases.json", [scene.to_dict() for scene in scenes])
    dump(output / "config.json", Q4SearchConfig().to_dict())
    hashes = {}
    sources = [root / name for name in ("q4_search.py", "test_q4_search.py", "q4.py", "q4_coverage.py",
                                        "coverage.py", "task_cost.py", "q4run.py")]
    sources += [root.parent / "b_adaptive_q3" / name for name in
                ("geometry.py", "state.py", "policy.py", "simulation.py")]
    for path in sources:
        relative, data = path.relative_to(root.parent), path.read_bytes()
        hashes[str(relative)] = hashlib.sha256(data).hexdigest()
        dest = output / "source" / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    dump(output / "manifest.json", dict(code_sha256=hashes, created_at=time.time(), python=sys.version,
                                         purpose="Q4 自适应方向缺口搜索的四布局新种子开发对照",
                                         cases_sha256=hashlib.sha256((output / "cases.json").read_bytes()).hexdigest()))
    results = []
    for scene in scenes:
        for name, policy_cls, state_cls in (("directional", Q4DirectionalPolicy, Q4InformationState),
                                            ("search", Q4SearchPolicy, Q4CoverageInformationState)):
            check_cached()
            trace = output / "actions" / f"{scene.name}_{name}.jsonl"
            result = run_case(scene, name, trace, config=Q4SearchConfig(),
                              policy_factory=policy_cls, state_factory=state_cls)
            rows = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
            result["non_anchor_measure_count"] = sum(
                row["kind"] == "measure" and all(g.distance(row["position"], q) > 1e-5 for q in Q4_ANCHORS)
                for row in rows)
            results.append(result)
            dump(output / "results.json", results)
            report(results, output)
            compact = {k: v for k, v in result.items() if k != "absence_proofs"}
            compact["absence_proof_kinds"] = sorted({p["kind"] for p in result["absence_proofs"].values()})
            print(json.dumps(compact, ensure_ascii=False), flush=True)
            if result["error"] and "ASTRA_STOP" in result["error"]:
                raise SystemExit(3)
    if not all(row["success"] for row in results):
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=Path)
    parser.add_argument("--seed", type=int, default=31220)
    args, rest = parser.parse_known_args()
    if args.batch:
        batch(args.batch, args.seed)
    else:
        unittest.main(argv=[sys.argv[0]] + rest, verbosity=2)
