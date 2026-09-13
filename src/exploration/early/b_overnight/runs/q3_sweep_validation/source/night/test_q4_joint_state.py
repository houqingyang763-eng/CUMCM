"""联合几何外包的独立边界检查与冻结驱动完整对照。"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import sys
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from q4_joint_state import (Q4JointInformationState, Q4JointCoverageInformationState, JointChannelState, allowed_orientation_outer,
                           intersect_intervals, joint_cell_certificate, orientation_in,
                           vector_angle_arc, g)
from q4 import Q4InformationState, Q4DirectionalPolicy
from astra_guard import check_cached


class JointGeometryTests(unittest.TestCase):
    poly = [(-10, -10), (10, -10), (10, 10), (-10, 10)]

    def test_observer_inside_on_edge_or_vertex_uses_full_circle(self):
        for p in ((0, 0), (10, 0), (10, 10), (10.000001, 0)):
            self.assertEqual(vector_angle_arc(self.poly, p)[1], 360)

    def test_continuous_polygon_direction_covered(self):
        rng = random.Random(81100)
        for p in ((100, 0), (-100, 0), (0, 100), (0, -100), (15, 15)):
            for _ in range(300):
                s = (rng.uniform(-10, 10), rng.uniform(-10, 10))
                beta = math.degrees(math.atan2(p[1] - s[1], p[0] - s[0])) % 360
                self.assertTrue(orientation_in(allowed_orientation_outer(self.poly, p), beta))
                # 实际观测视线两侧90度均须包括，独立于顶点弧计算。
                self.assertTrue(orientation_in(allowed_orientation_outer(self.poly, p), beta + 90))
                self.assertTrue(orientation_in(allowed_orientation_outer(self.poly, p), beta - 90))

    def test_zero_360_closed_endpoint_intersection(self):
        result = intersect_intervals([(180, 360)], [(0, 90)])
        self.assertTrue(orientation_in(result, 0))
        self.assertFalse(orientation_in(result, 45))

    def test_compatible_world_kept_false_cell_removed(self):
        positive = [(1450, -190), (1450, 190)]
        negative = [(150, 0)]
        bad = joint_cell_certificate(self.poly, positive, negative)
        self.assertTrue(bad["discarded"])
        good_poly = [(290, -10), (310, -10), (310, 10), (290, 10)]
        good = joint_cell_certificate(good_poly, positive, negative)
        self.assertFalse(good["discarded"])
        self.assertTrue(orientation_in(good["orientation_intervals"], 0))

    def test_far_negative_cannot_reject_omni(self):
        result = joint_cell_certificate(self.poly, [(100, 0)], [(2000, 0)])
        self.assertTrue(result["omni_possible"])
        self.assertFalse(result["discarded"])
        self.assertEqual(result["effective_negative_positions"], [])

    def test_history_radius_enables_negative_above_1000(self):
        result = joint_cell_certificate(self.poly, [(1450, -190), (1450, 190)], [(1200, 0)])
        self.assertFalse(result["omni_possible"])
        self.assertTrue(result["effective_negative_positions"])

    def test_degenerate_point_and_segment(self):
        for poly in [[(0, 0)], [(-10, 0), (10, 0)]]:
            result = joint_cell_certificate(poly, [(500, 100)], [(500, -100)])
            self.assertFalse(result["discarded"])
            self.assertTrue(orientation_in(result["orientation_intervals"], 90))

    def test_independent_random_physical_worlds_never_removed(self):
        rng = random.Random(81101)
        for trial in range(200):
            s = (rng.uniform(-10, 10), rng.uniform(-10, 10))
            radius = rng.choice([1000, 1250, 1500])
            orientation = None if trial % 3 == 0 else rng.uniform(0, 360)
            positive, negative = [], []
            for _ in range(12):
                p = (rng.uniform(-1600, 1600), rng.uniform(-1600, 1600))
                view = math.degrees(math.atan2(p[1] - s[1], p[0] - s[0]))
                covered = g.distance(p, s) <= radius and (
                    orientation is None or abs(g.angle_delta(view, orientation)) <= 90)
                (positive if covered else negative).append(p)
            result = joint_cell_certificate(self.poly, positive, negative)
            self.assertFalse(result["discarded"], (trial, s, radius, orientation, result))
            if orientation is None:
                self.assertTrue(result["omni_possible"])
            else:
                self.assertTrue(orientation_in(result["orientation_intervals"], orientation))

    def test_state_prunes_geometry_and_keeps_legal_true_source(self):
        state = Q4JointInformationState()
        true_source = (300, 0)
        for p, error in [((1450, -190), .95), ((1450, 190), -.95)]:
            bearing = math.degrees(math.atan2(true_source[1] - p[1], true_source[0] - p[0]))
            state.update(dict(kind="measure", position=p, channel=1),
                         dict(accepted=True, measure_result="direction", svd_deg=round((bearing + error) % 360, 2),
                              virtual_time_s=state.virtual_time_s + 5))
        c = state.channels[1]
        self.assertTrue(c.compatible((0, 0)))
        self.assertTrue(c.compatible(true_source))
        state.update(dict(kind="measure", position=(150, 0), channel=1),
                     dict(accepted=True, measure_result="no_signal", virtual_time_s=15))
        self.assertTrue(c.compatible(true_source))
        self.assertFalse(c.compatible((0, 0)))
        self.assertGreater(len(c.joint_excluded), 0)
        removed = set(c.joint_excluded)
        c.invalidate()
        self.assertTrue(c.compatible(true_source))
        self.assertTrue(removed <= set(c.joint_excluded))

    def test_combined_state_preserves_unknown_coverage(self):
        from q4 import Q4_ANCHORS
        state = Q4JointCoverageInformationState()
        self.assertTrue(all(isinstance(c, JointChannelState) for c in state.channels.values()))
        for i, p in enumerate(Q4_ANCHORS):
            state.update(dict(kind="measure", position=p, channel=20),
                         dict(accepted=True, measure_result="no_signal", virtual_time_s=6 * (i + 1)))
        self.assertEqual(state.channels[20].status, "absent")
        self.assertTrue(state.coverage(20).complete)
        self.assertIn(20, state.absence_proofs)
        self.assertEqual(state.channels[20].exclusions, [])
        self.assertEqual(state.joint_statistics()["unique_removed_cells"], 0)
        self.assertTrue(callable(state.discovery_points))

    def test_combined_state_preserves_known_joint_pruning(self):
        state = Q4JointCoverageInformationState()
        true_source = (300, 0)
        for p, error in [((1450, -190), .95), ((1450, 190), -.95)]:
            bearing = math.degrees(math.atan2(-p[1], true_source[0] - p[0]))
            state.update(dict(kind="measure", position=p, channel=1),
                         dict(accepted=True, measure_result="direction", svd_deg=round((bearing + error) % 360, 2),
                              virtual_time_s=state.virtual_time_s + 5))
        state.update(dict(kind="measure", position=(150, 0), channel=1),
                     dict(accepted=True, measure_result="no_signal", virtual_time_s=15))
        self.assertTrue(state.channels[1].compatible(true_source))
        self.assertFalse(state.channels[1].compatible((0, 0)))
        self.assertGreater(state.joint_statistics()["unique_removed_cells"], 0)


def audit_joint(state, env):
    """只在测试驱动里接触真值；逐格检查真实位置和朝向未被证书误排除。"""
    for j, source in env.sources.items():
        c = state.channels[j]
        if c.status != "found" or c.first is None:
            continue
        c.possible_cells()
        for cert in c.joint_last_details:
            if not g.contains(cert["polygon"], source.position):
                continue
            assert not cert["discarded"], (j, "含真源格被联合证书删除")
            if source.orientation is None:
                assert cert["omni_possible"], (j, "真实全向解释被删除")
            else:
                assert orientation_in(cert["orientation_intervals"], source.orientation), (j, "真实方向不在整格外包内")


def smoke(output):
    import q4run
    check_cached()
    output = output.resolve()
    if ROOT / "runs" / "q4_joint" not in output.parents:
        raise ValueError("结果必须位于 runs/q4_joint 新子目录")
    output.mkdir(parents=True, exist_ok=False)
    scenes = [q4run.generate_q4(73100, "uniform", "smooth", "random"),
              q4run.generate_q4(73101, "edge", "biased", "outward"),
              q4run.generate_q4(73102, "edge", "hashed", "tangent"),
              q4run.generate_q4(73103, "line", "hashed", "aligned")]
    q4run.dump(output / "cases.json", [s.to_dict() for s in scenes])
    versions = {}
    for folder, prefix in ((ROOT.parent / "b_adaptive_q3", "base"), (ROOT, "night")):
        for path in folder.glob("*.py"):
            if path.name == "astra_guard.py":
                continue
            data = path.read_bytes()
            target = output / "source" / prefix / path.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            versions[f"{prefix}/{path.name}"] = hashlib.sha256(data).hexdigest()
    manifest = dict(code_sha256=versions, created_at=time.time(), planned_runs=8,
                    audit="q4run原逐动作审计，加测试模块audit_joint；策略不接触真值")
    q4run.dump(output / "manifest.json", manifest)
    original_audit = q4run.audit_orientation
    results = []
    for scene in scenes:
        for name, state_cls in [("directional", Q4InformationState), ("joint", Q4JointInformationState)]:
            check_cached()
            captured = {}
            def extra_audit(state, env):
                original_audit(state, env)
                if name == "joint":
                    audit_joint(state, env)
                    captured.update(state.joint_statistics())
            with patch.object(q4run, "audit_orientation", extra_audit):
                result = q4run.run_case(scene, name, output / "actions" / f"{scene.name}_{name}.jsonl",
                    policy_factory=Q4DirectionalPolicy, state_factory=state_cls)
            result["joint_statistics"] = captured
            results.append(result)
            q4run.dump(output / "results.json", results)
            print(json.dumps({k: result[k] for k in ("case", "policy", "success", "virtual_time_s",
                         "wall_time_s", "failed_clears", "joint_statistics", "error")}, ensure_ascii=False), flush=True)
            check_cached()
    manifest.update(finished_at=time.time(), completed_runs=len(results))
    q4run.dump(output / "manifest.json", manifest)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", type=Path)
    args = parser.parse_args()
    if args.smoke:
        smoke(args.smoke)
    else:
        unittest.main(argv=[sys.argv[0]], verbosity=2)
