"""Q4 差异约束的构造测试。"""
import math
import unittest

from q4 import Q4_ANCHORS, Q4InformationState, orientation_model, orientation_reception, g
from state import ChannelState, audit_state
from simulation import LocalEnvironment, Scenario, Source


class Q4Checks(unittest.TestCase):
    def test_37_lattice_points_and_boundary_directions(self):
        self.assertEqual(len(Q4_ANCHORS), 37)
        self.assertLessEqual(max(math.hypot(*q) for q in Q4_ANCHORS), 2700.000001)
        sources = [(0, 0), (900, 0), (450, 0), (450, 450 * math.sqrt(3))]
        sources += [g.mul(g.unit(a), 1800) for a in range(0, 360, 5)]
        for p in sources:
            for angle in range(0, 360, 5):
                n = g.unit(angle)
                self.assertTrue(any(g.distance(p, q) < 1000 and g.dot(g.sub(q, p), n) > 1e-6 for q in Q4_ANCHORS), (p, angle))

    def test_no_signal_preserves_nearby_directional_truth(self):
        env = LocalEnvironment(Scenario("unit", 1, "unit", "zero", (Source(1, (10, 0), 1000, 0),)))
        state = Q4InformationState()
        original = list(state.channels[1].polygon)
        action = dict(kind="measure", position=(0, 0), channel=1)
        response = env.act(action)
        self.assertEqual(response["measure_result"], "no_signal")
        state.update(action, response)
        self.assertEqual(state.channels[1].polygon, original)
        self.assertEqual(state.channels[1].exclusions, [])
        self.assertEqual(state.channels[1].anchors_missed, set())
        audit_state(state, env)

    def test_absence_requires_all_37_misses(self):
        state = Q4InformationState()
        for i, q in enumerate(Q4_ANCHORS):
            state.update(dict(kind="measure", position=q, channel=20), dict(accepted=True, measure_result="no_signal", virtual_time_s=5 * (i + 1)))
            self.assertEqual(state.channels[20].status, "absent" if i == 36 else "unknown")

    def test_failed_clear_can_still_exclude_a_disk(self):
        state = Q4InformationState()
        state.update(dict(kind="clear", position=(0, 0), channel=1), dict(accepted=True, clear_result="no_target_in_range", virtual_time_s=3))
        self.assertEqual(state.channels[1].exclusions, [((0, 0), 20.0)])

    def test_direction_model_retains_mixed_type_logic(self):
        c = ChannelState(1)
        c.observations = [((-100, 0), "direction", 0), ((100, 0), "no_signal", None)]
        model = orientation_model(c, (0, 0))
        self.assertFalse(model[0])
        self.assertAlmostEqual(orientation_reception(model, (0, 0), (-100, 0)), 1)
        self.assertAlmostEqual(orientation_reception(model, (0, 0), (100, 0)), 0)
        c.observations = [((-100, 0), "direction", 0), ((100, 0), "direction", 180)]
        self.assertTrue(orientation_model(c, (0, 0))[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
