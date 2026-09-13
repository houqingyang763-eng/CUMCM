"""连续覆盖边界检查；另可 --smoke 运行两个自建完整案例的成对对照。"""
import argparse
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time
import unittest

from coverage import (CoverageInformationState, CoverageLeaf, CoveragePolicyMixin,
                      coverage_certificate, verify_certificate)
import geometry as g
from policy import BasePolicy


def ring_points(radius=1200, count=6, rotation=0):
    return [g.mul(g.unit(rotation + i * 360 / count), radius) for i in range(count)]


def negative_update(state, q, channel=1):
    state.update(dict(kind="measure", position=q, channel=channel),
                 dict(accepted=True, measure_result="no_signal",
                      virtual_time_s=state.virtual_time_s + 5))


class CoverageTests(unittest.TestCase):
    def test_no_data_never_proves_absence(self):
        cert = coverage_certificate([])
        self.assertFalse(cert.complete)
        self.assertGreater(cert.area_upper_m2, 0)
        self.assertTrue(verify_certificate(cert))
        self.assertTrue(cert.witness_points())

    def test_single_enlarged_disk_and_tangent_boundary(self):
        inside = coverage_certificate([((0, 0), 1802)])
        self.assertTrue(inside.complete)
        self.assertTrue(inside.rational_verified)
        tangent = coverage_certificate([((0, 0), 1800)])
        self.assertFalse(tangent.complete)
        self.assertTrue(verify_certificate(tangent))

    def test_rotated_seven_points_certify_without_fixed_anchors(self):
        points = [(0, 0)] + ring_points(rotation=17)
        state = CoverageInformationState()
        for q in points:
            negative_update(state, q)
        self.assertEqual(state.channels[1].status, "absent")
        self.assertEqual(state.absence_reasons[1], "negative_disk_union")
        self.assertEqual(state.channels[1].anchors_missed, {0})
        self.assertTrue(verify_certificate(state.coverage(1), require_complete=True))

    def test_all_grid_samples_covered_can_leave_continuous_hole(self):
        points = [(999.0, 0)] + ring_points()
        mask = 0
        state = CoverageInformationState()
        for q in points:
            mask |= g.coverage_mask(q)
            negative_update(state, q)
        self.assertEqual(mask, (1 << len(g.GRID)) - 1)
        hidden_point = (-100.0, 0.0)
        self.assertTrue(all(g.distance(hidden_point, q) > 1000 for q in points))
        cert = state.coverage(1)
        self.assertFalse(cert.complete)
        self.assertEqual(state.channels[1].status, "unknown")
        self.assertTrue(any(b.x0 <= hidden_point[0] <= b.x1 and
                            b.y0 <= hidden_point[1] <= b.y1 for b in cert.unresolved))
        self.assertTrue(verify_certificate(cert))

    def test_tiny_central_hole_survives_depth_limit(self):
        # 7 个排除圆把圆心外几乎全部盖住，圆心仍距所有圆心大于 1000m。
        circles = [(q, 1000) for q in ring_points(1000.00001, 7)]
        cert = coverage_certificate(circles)
        self.assertFalse(cert.complete)
        self.assertTrue(any(b.x0 <= 0 <= b.x1 and b.y0 <= 0 <= b.y1
                            for b in cert.unresolved))
        self.assertTrue(verify_certificate(cert))

    def test_additional_exclusions_never_enlarge_outer_remaining_area(self):
        points = [(0, 0)] + ring_points(rotation=17)
        areas = [coverage_certificate([(q, 1000) for q in points[:k]]).area_upper_m2
                 for k in range(len(points) + 1)]
        self.assertTrue(all(a + 1e-8 >= b for a, b in zip(areas, areas[1:])))
        self.assertEqual(areas[-1], 0)

    def test_duplicate_negative_measurements_have_no_new_coverage(self):
        one = coverage_certificate([((150, 250), 1000)])
        duplicate = coverage_certificate([((150, 250), 1000), ((150, 250), 1000)])
        self.assertIs(one, duplicate)

    def test_invalid_inputs_fail_closed(self):
        for circles in ([((math.nan, 0), 1000)], [((0, math.inf), 1000)], [((0, 0), -1)]):
            with self.assertRaises(ValueError):
                coverage_certificate(circles)

    def test_rational_verifier_rejects_broken_partition(self):
        cert = coverage_certificate([((0, 0), 1800.1)])
        with self.assertRaises(AssertionError):
            verify_certificate(replace(cert, leaves=cert.leaves[1:]), require_complete=True)

    def test_rational_verifier_rejects_forged_covered_leaf(self):
        cert = coverage_certificate([])
        first = cert.leaves[0]
        forged = CoverageLeaf(first.box, "covered", 0)
        with self.assertRaises(AssertionError):
            verify_certificate(replace(cert, exclusions=(((0, 0), 1.0),),
                                       leaves=(forged,) + cert.leaves[1:]))

    def test_found_channels_not_deleted_by_coverage_extension(self):
        state = CoverageInformationState()
        state.update(dict(kind="measure", position=(0, 0), channel=1),
                     dict(accepted=True, measure_result="near", virtual_time_s=5))
        negative_update(state, (1500, 0))
        self.assertEqual(state.channels[1].status, "found")

    def test_sixteen_source_rule_preserved(self):
        state = CoverageInformationState()
        for j in range(1, 17):
            state.update(dict(kind="measure", position=(0, 0), channel=j),
                         dict(accepted=True, measure_result="near", virtual_time_s=j * 5))
        self.assertTrue(all(state.channels[j].status == "absent" for j in range(17, 21)))
        self.assertEqual(state.absence_reasons[20], "maximum_source_count")

    def test_dynamic_candidates_and_positive_gain_for_grid_hole(self):
        state = CoverageInformationState()
        for j in range(2, 21):
            state.channels[j].status = "absent"
        for q in [(999.0, 0)] + ring_points():
            negative_update(state, q)
        points = state.discovery_points(limit=8)
        self.assertTrue(points)
        self.assertTrue(all(math.hypot(*q) <= 1800 for q in points))
        self.assertTrue(any(state.discovery_gain(1, q) > 0 for q in points))

    def test_mixin_can_close_small_hole_without_seven_anchors(self):
        class CoveragePolicy(CoveragePolicyMixin, BasePolicy):
            pass
        state = CoverageInformationState()
        for j in range(2, 21):
            state.channels[j].status = "absent"
        for q in [(999.0, 0)] + ring_points():
            negative_update(state, q)
        policy = CoveragePolicy()
        action = policy.choose(state)
        self.assertEqual(action["kind"], "measure")
        negative_update(state, action["position"])
        self.assertTrue(state.complete)


def smoke(output):
    """不改冻结文件，在独立进程的模块全局绑定中注入兼容实现。"""
    import run_local
    from simulation import generate
    from state import InformationState
    root = Path(__file__).resolve().parent
    project = root.parents[1]
    output = output.resolve()
    allowed = root / "runs" / "coverage"
    if output != allowed and allowed not in output.parents:
        raise ValueError("覆盖实验产物只能放 runs/coverage/")
    output.mkdir(parents=True, exist_ok=False)
    (output / "actions").mkdir()
    cases = [generate(21011, "uniform", "smooth"), generate(21012, "edge", "biased")]
    (output / "cases.json").write_text(json.dumps([s.to_dict() for s in cases], indent=2), encoding="utf-8")
    sources = [root / "coverage.py", Path(run_local.__file__), root / "test_coverage.py"]
    sources += [Path(run_local.__file__).with_name(name) for name in
                ("geometry.py", "state.py", "simulation.py", "policy.py")]
    manifest = {"created_local": time.strftime("%Y-%m-%d %H:%M:%S %z"),
                "code_sha256": {str(p.relative_to(project)): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in sources},
                "case_sha256": hashlib.sha256((output / "cases.json").read_bytes()).hexdigest(),
                "scope": "自建 Q3 模拟案例；不访问官方测试或隐藏真值；逐步沿用冻结审计"}
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    class CoveragePolicy(CoveragePolicyMixin, BasePolicy):
        pass

    results = []
    for scenario in cases:
        for name, policy_cls, state_cls in [("base", BasePolicy, InformationState),
                                            ("coverage", CoveragePolicy, CoverageInformationState)]:
            subprocess.run([sys.executable, str(root / "astra_guard.py"), "check"],
                           cwd=project, check=True, capture_output=True, text=True)
            run_local.BasePolicy, run_local.InformationState = policy_cls, state_cls
            result = run_local.run_case(scenario, trace_path=output / "actions" / f"{scenario.name}_{name}.jsonl")
            result["policy"] = name
            results.append(result)
            (output / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(result, ensure_ascii=False), flush=True)
    if not all(result["success"] for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", type=Path)
    args, remaining = parser.parse_known_args()
    if args.smoke:
        smoke(args.smoke)
    else:
        unittest.main(argv=[sys.argv[0]] + remaining)
