import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "b_adaptive_q3"))
from simulation import generate, LocalEnvironment
from state import InformationState
from policy import BasePolicy
from worlds import sample_environment, radial_interval
from astra_guard import quota_payload


class QuotaChecks(unittest.TestCase):
    def test_weekly_bucket_and_ten_percent(self):
        payload = {"rateLimitsByLimitId": {"codex": {"secondary": {"windowDurationMins": 10080, "usedPercent": 90}}}}
        self.assertEqual(quota_payload(payload)["remaining_percent"], 10)

    def test_missing_or_invalid_fails_closed(self):
        for value in (None, float("nan"), True):
            with self.assertRaises(ValueError):
                quota_payload({"rateLimits": {"primary": {"windowDurationMins": 10080, "usedPercent": value}}})


class ConditionalWorldChecks(unittest.TestCase):
    def test_every_sample_obeys_history_and_count(self):
        env, state, policy = LocalEnvironment(generate(235, "uniform", "biased")), InformationState(), BasePolicy()
        for _ in range(35):
            a = policy.choose(state)
            state.update(a, env.act(a))
        samples = [sample_environment(state, seed) for seed in range(5)]
        valid = [e for e in samples if e is not None]
        self.assertTrue(valid)
        for world in valid:
            unseen = sum(state.channels[j].status == "unknown" for j in world.sources)
            self.assertTrue(10 <= len(state.ever_seen)+unseen <= 16)
            for j, source in world.sources.items():
                interval = radial_interval(state.channels[j], source.position)
                self.assertIsNotNone(interval)
                self.assertTrue(interval[0] <= source.radius <= interval[1])
                for q, result, bearing in state.channels[j].observations:
                    response = world.act(dict(kind="measure", position=q, channel=j))
                    self.assertEqual(response["measure_result"], result)
                    if result == "direction":
                        self.assertEqual(response["svd_deg"], bearing)


if __name__ == "__main__":
    unittest.main(verbosity=2)
