"""条件模型独立复核：子集枚举、物理历史、清除及固定误差。"""
from itertools import combinations
import math
import random
import unittest

import common
from common import Q4State
import geometry as g
from state import ChannelState
from simulation import LocalEnvironment, Scenario, Source
from belief import (ConditionalEnvironment, make_pool, radial_slices, reception_mass,
                    sample_source, sample_worlds, subset_distribution)


def physical_result(source, q):
    distance = math.dist(source.position, q)
    if distance > source.radius:
        return "no_signal"
    if source.orientation is not None:
        angle = math.degrees(math.atan2(q[1] - source.position[1], q[0] - source.position[0]))
        if abs(g.angle_delta(angle, source.orientation)) > 90 + 1e-9:
            return "no_signal"
    return "near" if distance <= 5 else "direction"


class BeliefExtraTests(unittest.TestCase):
    def test_same_side_negative_can_only_reduce_radius(self):
        c = ChannelState(1)
        c.observations = [((500.0, 0.0), "direction", 180.0),
                          ((1200.0, 0.0), "no_signal", None)]
        pieces = radial_slices(c, (0.0, 0.0))
        self.assertEqual([(p.lo, p.hi) for p in pieces], [(1000.0, 1200.0)])
        self.assertAlmostEqual(sum(p.mass for p in pieces), 0.3)
        self.assertEqual(reception_mass((0.0, 0.0), pieces, (1250.0, 0.0)), 0.0)

    def test_known_count_posterior_matches_direct_subset_enumeration(self):
        masses = [0.7, 0.11, 0.02, 0.3, 0.99]
        known = 8
        suffix, ks, weights = subset_distribution(masses, known)
        direct = []
        for k in ks:
            total = sum(math.prod(masses[i] for i in subset)
                        for subset in combinations(range(len(masses)), k))
            direct.append(total / math.comb(20, known + k))
        for actual, expected in zip(weights, direct):
            self.assertAlmostEqual(actual, expected, places=16)
        for i in range(len(masses)):
            for k in range(1, len(masses) - i + 1):
                probability = masses[i] * suffix[i + 1][k - 1] / suffix[i][k]
                self.assertGreaterEqual(probability, 0.0)
                self.assertLessEqual(probability, 1.0 + 1e-15)

    def test_no_observation_count_prior_is_uniform(self):
        _, ks, weights = subset_distribution([1.0] * 20, 0)
        self.assertEqual(ks, list(range(10, 17)))
        self.assertEqual(weights, [1.0] * 7)

    def test_sampled_worlds_respect_count_type_and_history(self):
        state = Q4State()
        # 单条公开阳性和一条背面阴性；其余频道仍未知。
        observations = [((200.0, 0.0), "direction", 180.0),
                        ((-100.0, 0.0), "no_signal", None)]
        for q, result, bearing in observations:
            response = dict(accepted=True, virtual_time_s=0.0, measure_result=result)
            if bearing is not None:
                response["svd_deg"] = bearing
            state.update(dict(kind="measure", position=q, channel=1), response)
        worlds, _ = sample_worlds(state, count=30, pool_size=192, salt=804311)
        for world in worlds:
            self.assertTrue(10 <= len(world.sources) <= 16)
            self.assertEqual(len({source.channel for source in world.sources}), len(world.sources))
            self.assertEqual({source.orientation is None for source in world.sources}, {False, True})
            source = next(source for source in world.sources if source.channel == 1)
            for q, result, bearing in observations:
                self.assertEqual(physical_result(source, q), result)
                if result == "direction":
                    truth = math.degrees(math.atan2(source.position[1] - q[1], source.position[0] - q[0]))
                    self.assertLessEqual(abs(g.angle_delta(truth, bearing)), g.ANGLE_ERROR + 1e-9)

    def test_sample_source_obeys_successful_and_failed_clearance(self):
        state = Q4State()
        source = Source(1, (900.0, 0.0), 1500.0, 180.0)
        env = LocalEnvironment(Scenario("clearance", 113, "custom", "zero", (source,)))
        for action in (dict(kind="measure", position=(0.0, 0.0), channel=1),
                       dict(kind="clear", position=(850.0, 0.0), channel=1),
                       dict(kind="clear", position=(900.0, 0.0), channel=1)):
            state.update(action, env.act(action))
        rng = random.Random(9120)
        pool = make_pool(state, state.channels[1], rng, size=4096)
        for _ in range(100):
            sample = sample_source(1, pool, rng)
            self.assertGreater(math.dist(sample.position, (850.0, 0.0)), 20)
            self.assertLessEqual(math.dist(sample.position, (900.0, 0.0)), 20)

    def test_new_location_error_and_existing_location_reply_are_fixed(self):
        state = Q4State()
        source = Source(1, (700.0, 0.0), 1500.0, None)
        world = Scenario("history", 113, "custom", "hashed", (source,))
        history = dict(kind="measure", position=(0.0, 0.0), channel=1)
        state.update(history, dict(accepted=True, virtual_time_s=5.0,
                                   measure_result="direction", svd_deg=359.8))
        env = ConditionalEnvironment(world, state)
        first, second = env.act(history), env.act(history)
        self.assertEqual(first["svd_deg"], 359.8)
        self.assertEqual(first["svd_deg"], second["svd_deg"])
        new = dict(kind="measure", position=(400.0, 100.0), channel=1)
        self.assertEqual(env.act(new)["svd_deg"], env.act(new)["svd_deg"])

    def test_previously_cleared_channel_does_not_resurrect_old_signal(self):
        state = Q4State()
        source = Source(1, (50.0, 0.0), 1000.0, None)
        original = LocalEnvironment(Scenario("old_clear", 22, "custom", "zero", (source,)))
        history = dict(kind="measure", position=(0.0, 0.0), channel=1)
        state.update(history, original.act(history))
        clear = dict(kind="clear", position=(50.0, 0.0), channel=1)
        state.update(clear, original.act(clear))
        empty = Scenario("after_clear", 23, "custom", "zero", ())
        conditional = ConditionalEnvironment(empty, state)
        self.assertEqual(conditional.act(history)["measure_result"], "no_signal")


if __name__ == "__main__":
    unittest.main()
