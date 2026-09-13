"""独立构造边界条件；不以整局成功替代几何、计费与终止检查。"""
import math
import random
import unittest

import geometry as g
from policy import BasePolicy
from simulation import LocalEnvironment, Scenario, Source, noise_deg
from state import InformationState, audit_state


def environment(sources=(), noise="zero", seed=1):
    return LocalEnvironment(Scenario("unit", seed, "unit", noise, tuple(sources)))


def act(env, kind, q, channel):
    return env.act(dict(kind=kind, position=q, channel=channel))


class ContractChecks(unittest.TestCase):
    def test_documented_199_seconds_and_clear_preserves_channel(self):
        # problem/附件2.md §10 原样动作序列；频道 3 在清除处无目标。
        env = environment()
        act(env, "measure", (300, 400), 1)
        self.assertEqual(env.virtual_time_s, 105)
        act(env, "measure", (300, 400), 2)
        self.assertEqual(env.virtual_time_s, 111)
        act(env, "clear", (300, 0), 3)
        self.assertEqual(env.channel, 2)
        self.assertEqual(env.virtual_time_s, 194)
        act(env, "measure", (300, 0), 2)
        self.assertEqual(env.virtual_time_s, 199)

    def test_detection_and_clear_thresholds(self):
        env = environment([Source(1, (0, 0), 1000)])
        self.assertEqual(act(env, "measure", (1000, 0), 1)["measure_result"], "direction")
        self.assertEqual(act(env, "measure", (1000.0001, 0), 1)["measure_result"], "no_signal")
        self.assertEqual(act(env, "measure", (5, 0), 1)["measure_result"], "near")
        self.assertEqual(act(env, "clear", (20.0001, 0), 1)["clear_result"], "no_target_in_range")
        self.assertEqual(act(env, "clear", (20, 0), 1)["clear_result"], "success")
        self.assertEqual(act(env, "measure", (0, 0), 1)["measure_result"], "no_signal")

    def test_directional_clear_independent(self):
        env = environment([Source(1, (0, 0), 1000, 0)])
        self.assertEqual(act(env, "measure", (-10, 0), 1)["measure_result"], "no_signal")
        self.assertEqual(act(env, "clear", (-10, 0), 1)["clear_result"], "success")

    def test_noise_fixed_and_bounded(self):
        for kind in ("zero", "smooth", "biased", "hashed"):
            for i in range(30):
                q = (i * 10.23, -i * 0.12)
                x = noise_deg(12, kind, q, 9)
                self.assertEqual(x, noise_deg(12, kind, q, 9))
                self.assertLessEqual(abs(x), 1)

    def test_bad_action_rejected_without_cost(self):
        env = environment()
        for q, channel in [((math.nan, 0), 1), ((0, 0), 21)]:
            with self.assertRaises(ValueError):
                act(env, "measure", q, channel)
        self.assertEqual(env.virtual_time_s, 0)


class GeometryChecks(unittest.TestCase):
    def test_all_circle_boundary_points_retained(self):
        poly = g.outer_disk((123, -456), 1800)
        for i in range(720):
            p = g.add((123, -456), g.mul(g.unit(i / 2), 1800))
            self.assertTrue(g.contains(poly, p))

    def test_first_strip_and_wedge_boundary_with_rounding(self):
        for bearing in (0, 0.0049, 89.9951, 179.9951, 359.9951):
            for error in (-1.0, 1.0):
                q = (0, 0)
                p = g.mul(g.unit(bearing), 1500)
                env = environment([Source(1, p, 1500)], "biased", 1 if error < 0 else 2)
                state = InformationState()
                action = dict(kind="measure", position=q, channel=1)
                response = env.act(action)
                # 固定误差并舍入，单独命中最大角度边界。
                response.update(measure_result="direction", svd_deg=round((bearing + error) % 360, 2) % 360)
                state.update(action, response)
                audit_state(state, env)

    def test_strip_cells_cover_entire_rectangle(self):
        half = g.STRIP_HALF_WIDTH
        self.assertGreater(half, 1500 * math.sin(math.radians(g.ANGLE_ERROR)))
        self.assertLess(math.hypot(15, half / 2), 20)
        for k in range(50):
            for v0, v1 in ((-half, 0), (0, half)):
                c = (15 + 30 * k, (v0 + v1) / 2)
                for u in (30 * k, 30 * (k + 1)):
                    for v in (v0, v1):
                        self.assertLess(g.distance(c, (u, v)), 20)

    def test_equilateral_not_half_diameter(self):
        points = [(0, 0), (39, 0), (19.5, 39 * math.sqrt(3) / 2)]
        c, r = g.enclosing_circle(points)
        self.assertGreater(r, 20)
        self.assertAlmostEqual(r, 39 / math.sqrt(3), places=5)
        self.assertTrue(all(g.distance(c, p) <= r for p in points))

    def test_negative_clear_cannot_discard_remaining_true_cell(self):
        env = environment([Source(1, (1000, 10), 1200)])
        state = InformationState()
        a = dict(kind="measure", position=(0, 0), channel=1)
        state.update(a, env.act(a))
        before = len(state.channels[1].possible_cells())
        q = min(state.channels[1].possible_cells(), key=lambda c: g.distance((0, 0), c["position"]))["position"]
        a = dict(kind="clear", position=q, channel=1)
        response = env.act(a)
        self.assertEqual(response["clear_result"], "no_target_in_range")
        state.update(a, response)
        audit_state(state, env)
        self.assertLess(len(state.channels[1].possible_cells()), before)

    def test_seven_anchor_continuous_bound_and_dense_boundary(self):
        self.assertLess(math.sqrt(1800 ** 2 + 1200 ** 2 - 2 * 1800 * 1200 * math.cos(math.pi / 6)), 1000)
        for i in range(720):
            for r in (0, 900, 1000, 1800):
                p = g.mul(g.unit(i / 2), r)
                self.assertLessEqual(min(g.distance(p, q) for q in g.ANCHORS), 1000)


class InformationChecks(unittest.TestCase):
    def test_absence_requires_all_anchor_misses(self):
        env, state = environment(), InformationState()
        for q in g.ANCHORS[:-1]:
            a = dict(kind="measure", position=q, channel=20)
            state.update(a, env.act(a))
            self.assertEqual(state.channels[20].status, "unknown")
        a = dict(kind="measure", position=g.ANCHORS[-1], channel=20)
        state.update(a, env.act(a))
        self.assertEqual(state.channels[20].status, "absent")

    def test_sixteen_cap_but_ten_not_enough(self):
        env = environment([Source(j, (10, 0), 1000) for j in range(1, 17)])
        state = InformationState()
        for j in range(1, 17):
            a = dict(kind="measure", position=(0, 0), channel=j)
            state.update(a, env.act(a))
            if j == 10:
                self.assertEqual(state.channels[20].status, "unknown")
        self.assertEqual(state.channels[20].status, "absent")
        self.assertFalse(state.complete)  # 已发现还未清除。

    def test_near_immediately_cleared(self):
        env, state = environment([Source(1, (3, 4), 1000)]), InformationState()
        a = dict(kind="measure", position=(0, 0), channel=1)
        state.update(a, env.act(a))
        next_action = BasePolicy().choose(state)
        self.assertEqual(next_action["kind"], "clear")
        self.assertEqual(tuple(next_action["position"]), (0, 0))

    def test_ready_to_clear_has_no_extra_localization_reward(self):
        state = InformationState()
        c = state.channels[1]
        c.status = "found"
        c.polygon = [(99, -1), (101, -1), (101, 1), (99, 1)]
        self.assertLess(c.circle()[1], 20)
        self.assertEqual(BasePolicy().utility(c, (0, 0), g.coverage_mask((0, 0))), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
