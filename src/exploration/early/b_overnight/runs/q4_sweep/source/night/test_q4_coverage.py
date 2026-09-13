"""Q4 方向无关连续证书的反例、边界和状态兼容检查。"""
from dataclasses import replace
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time
import unittest

from q4_coverage import (Q4CoverageInformationState, Q4CoverageLeaf,
                         q4_coverage_certificate, verify_q4_certificate)
from q4 import Q4_ANCHORS
import geometry as g
from simulation import LocalEnvironment, Scenario, Source
from state import audit_state


def negative(state, q, channel=1):
    state.update(dict(kind="measure", position=q, channel=channel),
                 dict(accepted=True, measure_result="no_signal", virtual_time_s=state.virtual_time_s + 5))


class Q4CoverageTests(unittest.TestCase):
    def test_no_data_and_one_circle_do_not_exclude_directional_source(self):
        for points in ([], [(0, 0)]):
            cert = q4_coverage_certificate(points)
            self.assertFalse(cert.complete)
            self.assertTrue(verify_q4_certificate(cert))

    def test_local_strict_triangle_covers_small_domain(self):
        points = [g.mul(g.unit(angle), 800) for angle in (0, 120, 240)]
        cert = q4_coverage_certificate(points, domain_radius=100)
        self.assertTrue(cert.complete)
        self.assertTrue(cert.rational_verified)
        self.assertTrue(verify_q4_certificate(cert, require_complete=True))

    def test_collinear_points_do_not_prove_strict_surround(self):
        points = [(-900, 0), (0, 0), (900, 0)]
        cert = q4_coverage_certificate(points, domain_radius=100)
        self.assertFalse(cert.complete)

    def test_far_triangle_hull_alone_does_not_prove_reception(self):
        points = [g.mul(g.unit(angle), 2000) for angle in (0, 120, 240)]
        cert = q4_coverage_certificate(points, domain_radius=100)
        self.assertFalse(cert.complete)

    def test_one_sided_points_leave_emission_direction_possible(self):
        points = [(q[0], q[1]) for q in Q4_ANCHORS if q[0] <= 0]
        source, outward = (1700, 0), (1, 0)
        self.assertTrue(all(g.dot(g.sub(q, source), outward) < 0 for q in points))
        cert = q4_coverage_certificate(points)
        self.assertFalse(cert.complete)
        self.assertTrue(any(b.x0 <= source[0] <= b.x1 and b.y0 <= source[1] <= b.y1
                            for b in cert.unresolved))
        self.assertTrue(verify_q4_certificate(cert))

    def test_37_point_lattice_certifies_continuous_disk(self):
        cert = q4_coverage_certificate(Q4_ANCHORS)
        self.assertEqual(len(Q4_ANCHORS), 37)
        self.assertTrue(cert.complete)
        self.assertTrue(cert.rational_verified)
        self.assertTrue(verify_q4_certificate(cert, require_complete=True))

    def test_rotated_lattice_certifies_without_fixed_anchor_rule(self):
        e = g.unit(17)
        points = [(e[0] * x - e[1] * y, e[1] * x + e[0] * y) for x, y in Q4_ANCHORS]
        state = Q4CoverageInformationState()
        for p in points:
            if state.channels[1].status == "unknown":
                negative(state, p)
        self.assertEqual(state.channels[1].status, "absent")
        self.assertEqual(state.absence_proofs[1]["kind"], "q4_local_hull_union")
        self.assertEqual(len(state.q4_anchors_missed[1]), 1)
        self.assertEqual(state.channels[1].exclusions, [])

    def test_nearby_backside_source_survives_real_negative_response(self):
        scene = Scenario("nearby_backside_unit", 1, "unit", "zero",
                         (Source(1, (10, 0), 1000, 0),))
        env, state = LocalEnvironment(scene), Q4CoverageInformationState()
        action = dict(kind="measure", position=(0, 0), channel=1)
        response = env.act(action)
        self.assertEqual(response["measure_result"], "no_signal")
        state.update(action, response)
        self.assertEqual(state.channels[1].status, "unknown")
        self.assertEqual(state.channels[1].exclusions, [])
        audit_state(state, env)

    def test_exact_verifier_rejects_missing_leaf(self):
        cert = q4_coverage_certificate(Q4_ANCHORS)
        with self.assertRaises(AssertionError):
            verify_q4_certificate(replace(cert, leaves=cert.leaves[:-1]), require_complete=True)

    def test_exact_verifier_rejects_hull_without_distance_guarantee(self):
        points = [g.mul(g.unit(angle), 2000) for angle in (0, 120, 240)]
        cert = q4_coverage_certificate(points, domain_radius=100)
        leaf = cert.leaves[0]
        forged = Q4CoverageLeaf(leaf.box, "surrounded", (0, 1, 2))
        with self.assertRaises(AssertionError):
            verify_q4_certificate(replace(cert, leaves=(forged,) + cert.leaves[1:]))

    def test_invalid_coordinates_rejected(self):
        with self.assertRaises(ValueError):
            q4_coverage_certificate([(math.nan, 0)])

    def test_candidates_stay_inside_motion_domain(self):
        state = Q4CoverageInformationState()
        for j in range(2, 21):
            state.channels[j].status = "absent"
        for q in Q4_ANCHORS[:8]:
            negative(state, q)
        points = state.discovery_points(limit=12)
        self.assertTrue(points)
        self.assertLessEqual(len(points), 12)
        self.assertTrue(all(math.hypot(*q) <= 5000 for q in points))


def smoke(output):
    from astra_guard import check_cached
    from q4 import Q4Config, Q4DirectionalPolicy, Q4InformationState
    from q4run import dump, generate_q4, report, run_case
    check_cached()
    root = Path(__file__).resolve().parent
    output = output.resolve()
    allowed = root / "runs" / "q4_coverage"
    if output != allowed and allowed not in output.parents:
        raise ValueError("Q4 覆盖产物必须放 runs/q4_coverage/")
    output.mkdir(parents=True, exist_ok=False)
    scenes = [generate_q4(31104, "uniform", "smooth", "random"),
              generate_q4(31105, "edge", "biased", "outward")]
    dump(output / "cases.json", [scene.to_dict() for scene in scenes])
    dump(output / "config.json", Q4Config().to_dict())
    sources = [root / name for name in ("coverage.py", "q4_coverage.py", "test_q4_coverage.py",
                                        "q4.py", "q4run.py", "task_cost.py")]
    sources += [root.parent / "b_adaptive_q3" / name for name in
                ("geometry.py", "state.py", "policy.py", "simulation.py")]
    hashes = {}
    for path in sources:
        relative = path.relative_to(root.parent)
        data = path.read_bytes()
        hashes[str(relative)] = hashlib.sha256(data).hexdigest()
        dest = output / "source" / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    dump(output / "manifest.json", dict(code_sha256=hashes, python=sys.version,
                                         created_at=time.time(),
                                         purpose="Q4 连续覆盖停止证据的两个新种子开发整局检查",
                                         candidates_enabled=False,
                                         cases_sha256=hashlib.sha256((output / "cases.json").read_bytes()).hexdigest()))
    results, proofs = [], []
    for scene in scenes:
        for name, state_cls in (("directional", Q4InformationState),
                                 ("directional_coverage", Q4CoverageInformationState)):
            check_cached()
            trace = output / "actions" / f"{scene.name}_{name}.jsonl"
            result = run_case(scene, name, trace, policy_factory=Q4DirectionalPolicy, state_factory=state_cls)
            results.append(result)
            dump(output / "results.json", results)
            report(results, output)
            print(json.dumps(result, ensure_ascii=False), flush=True)
            if result["error"] and "ASTRA_STOP" in result["error"]:
                raise SystemExit(3)
            if name == "directional_coverage":
                state = Q4CoverageInformationState()
                for line in trace.read_text(encoding="utf-8").splitlines():
                    row = json.loads(line)
                    previous = {j: c.status for j, c in state.channels.items()}
                    state.update(row, row["response"])
                    for j, c in state.channels.items():
                        if c.status == "absent" and previous[j] != "absent":
                            proof = dict(case=scene.name, step=row["step"], channel=j,
                                         reason=state.absence_proofs[j]["kind"],
                                         fixed_anchor_count=len(state.q4_anchors_missed[j]))
                            if proof["reason"] == "q4_local_hull_union":
                                cert = state.coverage(j)
                                verify_q4_certificate(cert, require_complete=True)
                                proof["certificate"] = cert.to_dict(include_leaves=True)
                            proofs.append(proof)
                dump(output / "absence_proofs.json", proofs)
    if not all(row["success"] for row in results):
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", type=Path)
    args, rest = parser.parse_known_args()
    if args.smoke:
        smoke(args.smoke)
    else:
        unittest.main(argv=[sys.argv[0]] + rest, verbosity=2)
