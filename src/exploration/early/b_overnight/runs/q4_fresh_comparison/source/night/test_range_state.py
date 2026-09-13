import unittest
from range_state import RangeOrderInformationState, clip_distance_order
from state import InformationState
import geometry as g


class RangeOrderChecks(unittest.TestCase):
    def feedback(self, state, q, outcome, time):
        state.update(dict(kind="measure", channel=1, position=q),
                     dict(accepted=True, virtual_time_s=time, measure_result=outcome, svd_deg=0.))

    def test_range_coupling_removes_far_branch(self):
        plain, tightened = InformationState(), RangeOrderInformationState()
        for s in (plain, tightened):
            self.feedback(s, (0., 0.), "direction", 5.)
            self.feedback(s, (1000., 1000.), "no_signal", 300.)
        self.assertTrue(plain.channels[1].compatible((1400., 0.)))
        self.assertFalse(tightened.channels[1].compatible((1400., 0.)))
        self.assertTrue(tightened.channels[1].compatible((100., 0.)))

    def test_negative_before_positive(self):
        s = RangeOrderInformationState()
        self.feedback(s, (1000., 1000.), "no_signal", 290.)
        self.feedback(s, (0., 0.), "direction", 580.)
        self.assertFalse(s.channels[1].compatible((1400., 0.)))
        self.assertTrue(s.channels[1].compatible((100., 0.)))

    def test_translation_and_closed_boundary(self):
        origin = (1900000., -1900000.)
        poly = [g.add(origin, q) for q in ((-100., -100.), (1600., -100.), (1600., 100.), (-100., 100.))]
        out = clip_distance_order(poly, origin, g.add(origin, (1000., 1000.)))
        self.assertTrue(g.contains(out, g.add(origin, (1000., 0.))))
        self.assertFalse(g.contains(out, g.add(origin, (1400., 0.))))


if __name__ == "__main__":
    unittest.main()
