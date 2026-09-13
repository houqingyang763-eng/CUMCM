"""Q1/Q2 必要性质检查；包括独立距离规则与构造反例。"""
import math
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import q2_geometry as qg
g = qg.g


class Q1GeometryTests(unittest.TestCase):
    def test_empty_unbounded_point_segment(self):
        self.assertEqual(qg.halfplane_region([((1, 0), 0), ((-1, 0), -1)])["kind"], "empty")
        self.assertEqual(qg.halfplane_region(qg.bearing_halfplanes((0, 0), 0))["kind"], "unbounded")
        point = qg.halfplane_region([((1, 0), 2), ((-1, 0), -2), ((0, 1), 3), ((0, -1), -3)])
        self.assertEqual(point["kind"], "point")
        self.assertAlmostEqual(qg.polygon_diameter(point["vertices"])[0], 0)
        segment = qg.halfplane_region([((1, 0), 2), ((-1, 0), -2), ((0, 1), 3), ((0, -1), 0)])
        self.assertEqual(segment["kind"], "segment")
        self.assertAlmostEqual(qg.polygon_diameter(segment["vertices"])[0], 3)

    def test_halfplane_strip_without_vertices_is_nonempty(self):
        region = qg.halfplane_region([((1, 0), 2), ((-1, 0), -1)])
        self.assertEqual(region["kind"], "unbounded")
        self.assertTrue(1 <= region["witness"][0] <= 2)

    def test_rectangle_diameter(self):
        region = qg.halfplane_region([((1, 0), 4), ((-1, 0), 0), ((0, 1), 3), ((0, -1), 0)])
        self.assertEqual(region["kind"], "polygon")
        self.assertAlmostEqual(qg.polygon_diameter(region["vertices"])[0], 5)

    def test_wedge_wrap_and_wrong_direction(self):
        poly = qg.wedge_with_error(g.outer_disk((0, 0), 100), (0, 0), 359.8, 1)
        self.assertTrue(g.contains(poly, (90, 0)))
        self.assertFalse(g.contains(poly, (-90, 0)))

    def test_zero_error_is_ray_not_line(self):
        region = qg.halfplane_region(qg.bearing_halfplanes((0, 0), 0, 0))
        self.assertEqual(region["kind"], "unbounded")
        self.assertGreaterEqual(region["recession_direction"][0], 0)
        clipped = qg.wedge_with_error(g.outer_disk((0, 0), 100), (0, 0), 0, 0)
        self.assertTrue(g.contains(clipped, (90, 0)))
        self.assertFalse(g.contains(clipped, (-90, 0)))

    def test_equilateral_diameter_circle_fails(self):
        points = [(0, 0), (40, 0), (20, 20 * math.sqrt(3))]
        diameter, pair = qg.polygon_diameter(points)
        c, radius = g.enclosing_circle(points)
        self.assertAlmostEqual(diameter, 40)
        self.assertAlmostEqual(radius, 40 / math.sqrt(3), places=5)
        midpoint = g.mul(g.add(*pair), .5)
        self.assertGreater(max(g.distance(midpoint, p) for p in points), 20)
        self.assertGreater(radius, 20)

    def test_equilateral_is_realizable_by_three_bearing_wedges(self):
        vertices = [(0, 0), (40, 0), (20, 20 * math.sqrt(3))]
        halfplanes = []
        for a, b in zip(vertices, vertices[1:] + vertices[:1]):
            direction = g.mul(g.sub(b, a), 1 / g.distance(a, b))
            position = g.sub(a, g.mul(direction, 1000))
            bearing = math.degrees(math.atan2(direction[1], direction[0])) + 1
            halfplanes += qg.bearing_halfplanes(position, bearing)
        result = qg.halfplane_region(halfplanes)
        self.assertEqual(result["kind"], "polygon")
        self.assertEqual(len(result["vertices"]), 3)
        self.assertAlmostEqual(qg.polygon_diameter(result["vertices"])[0], 40)
        self.assertAlmostEqual(g.enclosing_circle(result["vertices"])[1], 40 / math.sqrt(3), places=5)


class Q2GeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.poly = qg.first_region((0, 0), 0, sides=360)

    def test_first_region_covers_all_angular_boundaries(self):
        for r in (0, 5, 500, 1000, 1500):
            for angle in (-g.ANGLE_ERROR, 0, g.ANGLE_ERROR):
                self.assertTrue(g.contains(self.poly, g.mul(g.unit(angle), r)))

    def test_inner_candidate_polygon_is_safe(self):
        region = qg.candidate_region_1000(self.poly, sides=64)
        self.assertTrue(region)
        for q in region:
            self.assertLessEqual(max(g.distance(q, s) for s in self.poly), 1000)

    def test_history_enlarges_reliable_region(self):
        q = (500, 800)
        self.assertGreater(max(g.distance(q, s) for s in self.poly), 1000)
        self.assertTrue(qg.guaranteed_reception(self.poly, q, [(0, 0)]))
        # 独立于半平面推导，直接检验官方半径不等式。
        for r in range(6, 1501, 7):
            for angle in (-g.ANGLE_ERROR, 0, g.ANGLE_ERROR):
                s = g.mul(g.unit(angle), r)
                self.assertLessEqual(g.distance(q, s), max(1000, r))

    def test_previous_success_and_empty_fail_closed(self):
        self.assertTrue(qg.guaranteed_reception(self.poly, (0, 0), [(0, 0)]))
        with self.assertRaises(ValueError):
            qg.guaranteed_reception([], (0, 0), [(0, 0)])
        self.assertFalse(qg.guaranteed_reception(self.poly, (1600, 0), [(0, 0)]))

    def test_multiple_history_certificate_against_direct_rule(self):
        rng = random.Random(20260911)
        poly = [(-500, -400), (600, -400), (600, 500), (-500, 500)]
        past = [(-700, 0), (700, 0), (0, 750)]
        checks = 0
        for _ in range(120):
            q = (rng.uniform(-1200, 1200), rng.uniform(-1200, 1200))
            if not qg.guaranteed_reception(poly, q, past):
                continue
            checks += 1
            for _ in range(100):
                s = (rng.uniform(-500, 600), rng.uniform(-400, 500))
                implied_radius = max(1000, *(g.distance(s, p) for p in past))
                self.assertLessEqual(g.distance(s, q), implied_radius + 1e-7)
        # 数量只用于确认确实经过真分支，不是接收域面积或成功率指标。
        self.assertGreater(checks, 0)

    def test_translation_does_not_change_reception(self):
        shift = (1900000.0, -1900000.0)
        q = (500, 800)
        self.assertTrue(qg.guaranteed_reception([g.add(s, shift) for s in self.poly],
                                               g.add(q, shift), [shift]))

    def test_continuous_angle_bin_bound_covers_non_bin_readings(self):
        q = (750, 600)
        bound = qg.posterior_radius_bound(self.poly, q, 3.0)["radius_m"]
        for beta in (201.111, 220.537, 231.249, 271.111, 300.421, 319.967):
            post = qg.wedge_with_error(self.poly, q, beta)
            if post:
                self.assertLessEqual(g.enclosing_circle(post)[1], bound + 1e-5)

    def test_fifty_metre_indistinguishable_pair(self):
        for q in ((750, 600), (500, 800), (650, 750)):
            example = qg.indistinguishable_pair(q)
            self.assertTrue(qg.guaranteed_reception(self.poly, q, [(0, 0)]))
            self.assertAlmostEqual(example["separation_m"], 50)
            self.assertTrue(all(abs(a) < 1 for a in example["first_true_angles_deg"]))
            self.assertTrue(all(d <= 1500 for d in example["first_distances_m"]))
            self.assertTrue(all(5 < d <= 1500 for d in example["second_distances_m"]))
            for s in example["sources"]:
                beta = math.degrees(math.atan2(s[1] - q[1], s[0] - q[0])) % 360
                self.assertLessEqual(abs(g.angle_delta(beta, example["second_reading_deg"])), 0.0051)

    def test_universal_counterexample_direct_physical_checks(self):
        rng = random.Random(2026091102)
        threshold_y = math.sqrt(1475 ** 2 - 1450 ** 2)
        queries = [(0, 0), (1450, 0), (50, 1000), (50, -1000), (1050, 0), (-950, 0)]
        queries += [(0, threshold_y + e) for e in (-1e-5, 0, 1e-5)]
        queries += [(rng.uniform(-2000, 2000), rng.uniform(-2000, 2000)) for _ in range(500)]
        outcomes = set()
        for q in queries:
            example = qg.universal_two_measurement_counterexample(q)
            outcomes.add(example["case"])
            self.assertGreater(example["separation_m"], 40)
            self.assertTrue(all(abs(a) <= 1 for a in example["first_true_angles_deg"]))
            for source, radius in zip(example["sources"], example["radii_m"]):
                d1, d2 = math.hypot(*source), g.distance(source, q)
                self.assertTrue(1000 <= radius <= 1500)
                self.assertTrue(5 < d1 <= radius + 1e-8)
                if example["second_outcome"] == "no_signal":
                    self.assertGreater(d2, radius)
                else:
                    self.assertTrue(5 < d2 <= radius + 1e-8)
                    beta = math.degrees(math.atan2(source[1] - q[1], source[0] - q[0]))
                    self.assertLessEqual(abs(g.angle_delta(beta, example["second_reading_deg"])), .0051)
        self.assertEqual(len(outcomes), 3)


if __name__ == "__main__":
    unittest.main()
