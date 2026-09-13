"""解析半径积分的独立核验，不导入环境或主策略。

运行：py -3.13 -m unittest discover -s experiments/b_q3/probability_patrol -p test_belief.py -v
独立交叉检查重新抽取 X 与 R，并逐个事件判定；不复用主模块的区间权重。
"""
import math
from types import SimpleNamespace
import unittest

import numpy as np

from belief import (
    DEFAULT_SEED,
    InsufficientPosteriorMass,
    UnknownDiscoveryBelief,
    unknown_discovery_probability,
)


def channel(positions=()):
    return SimpleNamespace(status="unknown", observations=[(p, "no_signal", None) for p in positions])


def independent_radius_monte_carlo(negative_positions, q, samples=600000, seed=981326):
    """显式独立采样固定 R、位置 X，按同一 R 检查所有历史反馈。"""
    rng = np.random.default_rng(seed)
    # 用正方形拒绝采样圆域，与主程序极坐标 sqrt(U) 方法独立。
    blocks = []
    count = 0
    while count < samples:
        xy = rng.uniform(-1800.0, 1800.0, size=(samples, 2))
        xy = xy[np.sum(xy * xy, axis=1) <= 1800.0 ** 2]
        blocks.append(xy)
        count += len(xy)
    xy = np.vstack(blocks)[:samples]
    radius = rng.uniform(1000.0, 1500.0, size=samples)
    survives = np.ones(samples, dtype=bool)
    for position in negative_positions:
        distances_squared = np.sum((xy - position) ** 2, axis=1)
        survives &= distances_squared > radius ** 2
    total = int(survives.sum())
    detected = np.sum((xy - q) ** 2, axis=1) <= radius ** 2
    probability = float(np.mean(detected[survives]))
    stderr = math.sqrt(probability * (1.0 - probability) / total)
    return probability, stderr, total / samples


class AnalyticProbabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.belief = UnknownDiscoveryBelief(samples=262144, seed=DEFAULT_SEED)

    def test_origin_without_history_matches_expected_circle_area(self):
        # 对均匀 R，E[R²]=(a²+ab+b²)/3；全部接收圆位于1800米域内。
        exact = (1000.0 ** 2 + 1000.0 * 1500.0 + 1500.0 ** 2) / (3 * 1800.0 ** 2)
        result = self.belief.estimate(channel(), (0.0, 0.0))
        self.assertAlmostEqual(result.history_likelihood, 1.0)
        self.assertLess(abs(result.probability - exact), 5 * result.standard_error)

    def test_same_point_remeasurement_is_exactly_zero(self):
        c = channel([(-750.0, 0.0), (750.0, 0.0)])
        for q in [(-750.0, 0.0), (750.0, 0.0)]:
            result = self.belief.estimate(c, q)
            self.assertEqual(result.probability, 0.0)
            self.assertEqual(result.standard_error, 0.0)

    def test_small_displacement_has_small_additional_chance(self):
        c = channel([(0.0, 0.0)])
        near, farther = self.belief.estimate_many(c, [(1.0, 0.0), (500.0, 0.0)])
        self.assertLess(near.probability, 0.002)
        self.assertGreater(farther.probability, 0.05)

    def test_duplicate_and_reordered_history_does_not_add_information(self):
        a, b = (-750.0, 0.0), (750.0, 0.0)
        first = self.belief.estimate(channel([a, b]), (0.0, 1200.0))
        duplicate = self.belief.estimate(channel([b, a, a]), (0.0, 1200.0))
        self.assertEqual(first, duplicate)

    def test_joint_probability_and_remaining_miss_mass_obey_chain_rule(self):
        c = channel([(-750.0, 0.0), (750.0, 0.0)])
        result = self.belief.estimate(c, (0.0, 1200.0))
        after = channel([(-750.0, 0.0), (750.0, 0.0), (0.0, 1200.0)])
        self.assertAlmostEqual(
            self.belief.history_likelihood(after),
            result.history_likelihood * (1.0 - result.probability),
            places=12,
        )

    def test_all_negative_observations_match_independent_radius_sampling(self):
        negatives = [(-750.0, 0.0), (750.0, 0.0), (300.0, -850.0)]
        q = (0.0, 1200.0)
        result = self.belief.estimate(channel(negatives), q)
        estimate, stderr, mass = independent_radius_monte_carlo(negatives, q)
        tolerance = 5 * math.hypot(result.standard_error, stderr)
        self.assertLess(abs(result.probability - estimate), tolerance)
        mass_stderr = math.sqrt(mass * (1.0 - mass) / 600000)
        # 独立二元抽样与位置积分都带误差；下式用二元方差上界覆盖两者。
        mass_tolerance = 5 * math.sqrt(mass_stderr ** 2 + 0.25 / self.belief.samples)
        self.assertLess(abs(result.history_likelihood - mass), mass_tolerance)

    def test_unrepresented_posterior_mass_never_becomes_absence_claim(self):
        points = [(0.0, 0.0)] + [(1200 * math.cos(k * math.pi / 3),
                                  1200 * math.sin(k * math.pi / 3)) for k in range(6)]
        with self.assertRaises(InsufficientPosteriorMass):
            UnknownDiscoveryBelief(samples=4096).estimate(channel(points), (0.0, 0.0))

    def test_positive_history_is_rejected_instead_of_silently_ignored(self):
        c = channel()
        c.observations.append(((0.0, 0.0), "direction", 45.0))
        with self.assertRaises(ValueError):
            self.belief.estimate(c, (100.0, 0.0))

    def test_scalar_wrapper_is_reproducible_and_reads_no_geometry_or_truth(self):
        class PublicHistoryOnly:
            status = "unknown"
            observations = [((0.0, 0.0), "no_signal", None)]

            def __getattr__(self, name):
                raise AssertionError("不允许读取历史以外的字段: " + name)

        c = PublicHistoryOnly()
        first = unknown_discovery_probability(c, (600.0, 0.0))
        second = unknown_discovery_probability(c, (600.0, 0.0))
        self.assertEqual(first, second)
        self.assertTrue(0.0 <= first <= 1.0)


if __name__ == "__main__":
    unittest.main()
