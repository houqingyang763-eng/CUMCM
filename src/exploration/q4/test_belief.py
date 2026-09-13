"""用解析例与直接角度/半径积分核验Q4条件模型。"""
import math
import random
import unittest

import common
import geometry as g
from state import ChannelState
from belief import radial_slices, reception_mass, sample_source


class BeliefTests(unittest.TestCase):
    def channel(self, observations):
        c = ChannelState(1)
        c.observations = observations
        return c

    def test_no_data_mass_and_range(self):
        c = self.channel([])
        slices = radial_slices(c, (0., 0.))
        self.assertAlmostEqual(sum(s.mass for s in slices), 1.)
        self.assertAlmostEqual(reception_mass((0, 0), slices, (100, 0)), .75)
        self.assertAlmostEqual(reception_mass((0, 0), slices, (1250, 0)), .375)
        self.assertEqual(reception_mass((0, 0), slices, (1600, 0)), 0.)

    def test_backside_negative_not_disk_exclusion(self):
        c = self.channel([((100., 0.), 'direction', 180.), ((-100., 0.), 'no_signal', None)])
        slices = radial_slices(c, (0., 0.))
        self.assertAlmostEqual(sum(s.mass for s in slices), .25)
        self.assertAlmostEqual(reception_mass((0, 0), slices, (200, 0)), 1.)
        self.assertAlmostEqual(reception_mass((0, 0), slices, (-200, 0)), 0.)

    def test_radius_breakpoint_analytic(self):
        c = self.channel([((100., 0.), 'direction', 180.), ((-1200., 0.), 'no_signal', None)])
        slices = radial_slices(c, (0., 0.))
        self.assertEqual([(s.lo, s.hi) for s in slices], [(1000., 1200.), (1200., 1500.)])
        self.assertAlmostEqual(sum(s.mass for s in slices), .45)

    def test_duplicate_observation_is_not_independent_coin(self):
        obs = ((100., 0.), 'direction', 180.)
        a = radial_slices(self.channel([obs]), (0., 0.))
        b = radial_slices(self.channel([obs, obs]), (0., 0.))
        self.assertEqual(a, b)

    def test_quadrature_matches_marginalization(self):
        # 直接枚举固定位置的R和方向，不调用被测区间运算。
        positives = [(200., 0.), (100., 100.)]
        negatives = [(-1200., 0.), (0., -1100.)]
        observations = [(q, 'direction', math.degrees(math.atan2(-q[1], -q[0])) % 360)
                        for q in positives] + [(q, 'no_signal', None) for q in negatives]
        slices = radial_slices(self.channel(observations), (0., 0.))
        omni, directional = 0, 0
        for i in range(100):
            radius = 1000+(i+.5)*5
            omni += int(all(math.hypot(*q) <= radius for q in positives)
                        and all(math.hypot(*q) > radius for q in negatives))
            for k in range(720):
                phi = (k+.5)*.5
                def visible(q):
                    angle = math.degrees(math.atan2(q[1], q[0]))
                    delta = (angle-phi+180) % 360-180
                    return math.hypot(*q) <= radius and abs(delta) <= 90
                directional += int(all(visible(q) for q in positives) and not any(visible(q) for q in negatives))
        expected = .5*omni/100 + .5*directional/(100*720)
        self.assertAlmostEqual(sum(s.mass for s in slices), expected, places=8)

    def test_sampled_source_replays_physical_visibility(self):
        c = self.channel([((100., 0.), 'direction', 180.), ((-1200., 0.), 'no_signal', None)])
        x = (0., 0.)
        slices = radial_slices(c, x)
        pool = {'points': [x], 'slices': [slices], 'weights': [sum(s.mass for s in slices)]}
        rng = random.Random(19)
        for _ in range(100):
            source = sample_source(1, pool, rng)
            for q, result, _ in c.observations:
                d = math.dist(q, x)
                visible = d <= source.radius
                if source.orientation is not None:
                    angle = math.degrees(math.atan2(q[1], q[0]))
                    visible &= abs(g.angle_delta(angle, source.orientation)) <= 90
                self.assertEqual(visible, result != 'no_signal')

    def test_clear_success_constraints(self):
        c = self.channel([])
        c.clear_history = [((0., 0.), 'success')]
        self.assertTrue(radial_slices(c, (10., 0.)))
        self.assertFalse(radial_slices(c, (30., 0.)))

    def test_incompatible_direction(self):
        c = self.channel([((100., 0.), 'direction', 179.), ((-100., 0.), 'direction', 10.)])
        self.assertFalse(radial_slices(c, (0., 0.)))


if __name__ == '__main__':
    unittest.main()
