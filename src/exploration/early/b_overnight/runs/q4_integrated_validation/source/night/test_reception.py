import unittest
from reception import ReceptionPolicy
from task_cost import CompletionCostPolicy
from state import InformationState
import geometry as g


class ReceptionChecks(unittest.TestCase):
    def state(self):
        state = InformationState()
        state.update(dict(kind="measure", channel=1, position=(0., 0.)),
                     dict(accepted=True, virtual_time_s=5., measure_result="direction", svd_deg=0.))
        return state

    def test_distance_lower_uses_history(self):
        c = self.state().channels[1]
        self.assertEqual(ReceptionPolicy.radius_lower(c, (1450., 0.)), 1450.)
        self.assertEqual(ReceptionPolicy.radius_lower(c, (100., 0.)), 1000.)

    def test_expanded_point_and_nonzero_credit(self):
        state = self.state()
        policy = ReceptionPolicy()
        policy._prepare(state)
        self.assertIn((500., 800.), policy.candidate_positions(state))
        value = policy.utility(state.channels[1], (500., 800.), g.coverage_mask((500., 800.)))
        self.assertGreater(value, 0.)
        self.assertGreater(policy.stats["beyond_1000_representatives"], 0)


if __name__ == "__main__":
    unittest.main()
