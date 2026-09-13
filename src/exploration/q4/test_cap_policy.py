"""Cap 子类公开动作边界测试；不读取模拟器真值。"""
import copy
import unittest
from unittest.mock import Mock, patch

from common import Q4State
from candidate_cap import CapConfig, CapPolicy
from cap_value import CapValueEstimator


def public_state():
    state = Q4State()
    state.ever_seen = set(range(1, 16))
    for j in range(1, 15):
        state.channels[j].status = "cleared"
    state.channels[15].status = "found"
    return state


def policy_for(state, result=None):
    policy = CapPolicy(CapConfig(initial_points=(), rollout_samples=0))
    policy.cap_observed_clears = {j for j, c in state.channels.items() if c.status == "cleared"}
    policy.seen_cleared = set(policy.cap_observed_clears)
    policy.cap_estimator = Mock()
    policy.cap_estimator.evaluate.return_value = (dict(prob=.1, fee=30., scanproxy=1000., net=70.)
                                                  if result is None else result)
    return policy


def reply(state, action, result):
    response = dict(accepted=True, virtual_time_s=state.virtual_time_s+6.)
    response["measure_result" if action["kind"] == "measure" else "clear_result"] = result
    state.update(action, response)


def semantic(state):
    return copy.deepcopy((state.position, state.actions, state.virtual_time_s, state.ever_seen,
                          [(j, c.status, c.observations, c.exclusions, c.measured)
                           for j, c in state.channels.items()]))


class CapPolicyTests(unittest.TestCase):
    def test_dict_config_uses_cap_config_and_preserves_inherited_options(self):
        for config in ({}, dict(cap_scan_limit=1, cap_pool_size=32, pool_size=24,
                                prune_planned_stops=False)):
            with self.subTest(config=config):
                original = copy.deepcopy(config)
                policy = CapPolicy(config)
                self.assertIsInstance(policy.config, CapConfig)
                for key, value in config.items():
                    self.assertEqual(getattr(policy.config, key), value)
                self.assertEqual(policy.cap_estimator.cache.size, policy.config.cap_pool_size)
                self.assertEqual(config, original)

    def test_planned_clear_commitment_charged_once(self):
        state = public_state()
        policy = policy_for(state)
        q = (500., 100.)
        job = dict(kind="clear", channel=15, position=q, scan_unknown=False)
        original = copy.deepcopy(job)
        action = policy._install(state, job)
        self.assertEqual(policy.cap_used, 1)
        self.assertEqual(job, original)
        self.assertEqual(policy.clear_scan_commitment, (15, q))
        reply(state, action, "success")
        action = policy.choose(state)
        self.assertEqual(policy.cap_used, 1)
        self.assertEqual(policy.cap_estimator.evaluate.call_count, 1)
        self.assertEqual(action["kind"], "measure")
        self.assertIn(action["channel"], range(16, 21))
        self.assertEqual(action["position"], q)

    def test_uncertain_multi_evaluates_only_actual_success_position(self):
        state = public_state()
        policy = policy_for(state)
        p0, p1 = (500., 100.), (537., 100.)
        action = policy._install(state, dict(kind="multi", channel=15, position=p0,
                                            points=[p0, p1], scan_unknown=False))
        policy.cap_estimator.evaluate.assert_not_called()
        reply(state, action, "no_target_in_range")
        action = policy.choose(state)
        policy.cap_estimator.evaluate.assert_not_called()
        self.assertEqual(action["position"], p1)
        reply(state, action, "success")
        action = policy.choose(state)
        policy.cap_estimator.evaluate.assert_called_once_with(state, p1)
        self.assertEqual(policy.cap_used, 1)
        self.assertEqual(action["position"], p1)
        self.assertIn(action["channel"], range(16, 21))

    def test_known16_queued_unknown_stops_and_complete_stops(self):
        state = public_state()
        policy = policy_for(state)
        q = (100., 100.)
        action = policy._station(state, q, "test", priority=16, scan_unknown=True)
        self.assertEqual(action["channel"], 16)
        reply(state, action, "near")
        self.assertEqual(len(state.ever_seen), 16)
        action = policy.choose(state)
        self.assertEqual((action["kind"], action["channel"]), ("clear", 16))
        reply(state, action, "success")
        for j in range(1, 17):
            state.channels[j].status = "cleared"
        self.assertTrue(state.complete)
        self.assertIsNone(policy.choose(state))
        self.assertIsNone(policy._station_action(state))
        policy.cap_estimator.evaluate.assert_not_called()
        self.assertEqual(policy.cap_used, 0)

    def test_no_value_or_nonpositive_value_spends_no_budget(self):
        for value in (None, dict(prob=0., fee=30., scanproxy=1000., net=-30.),
                      dict(prob=.03, fee=30., scanproxy=1000., net=0.)):
            with self.subTest(value=value):
                state = public_state()
                policy = policy_for(state)
                policy.cap_estimator.evaluate.return_value = value
                before = semantic(state)
                self.assertFalse(policy._cap_accept(state, (100., 100.), "test"))
                self.assertEqual(policy.cap_used, 0)
                self.assertEqual(semantic(state), before)

    def test_budget_upper_bound_and_wrong_known_do_not_evaluate(self):
        state = public_state()
        policy = policy_for(state)
        for q in ((100., 0.), (200., 0.)):
            self.assertTrue(policy._cap_accept(state, q, "test"))
        self.assertFalse(policy._cap_accept(state, (300., 0.), "test"))
        self.assertEqual(policy.cap_used, 2)
        self.assertEqual(policy.cap_estimator.evaluate.call_count, 2)
        policy = policy_for(state)
        state.ever_seen.remove(15)
        self.assertFalse(policy._cap_accept(state, (100., 0.), "test"))
        policy.cap_estimator.evaluate.assert_not_called()

    def test_already_planned_scan_does_not_consume_cap_budget(self):
        state = public_state()
        policy = policy_for(state)
        action = policy._install(state, dict(kind="measure", channel=15, position=(500., 0.),
                                            scan_unknown=True))
        self.assertEqual(action["channel"], 15)
        policy.cap_estimator.evaluate.assert_not_called()
        self.assertEqual(policy.cap_used, 0)

    def test_real_estimator_failure_returns_none_without_state_evidence(self):
        state = public_state()
        before = semantic(state)
        with patch("cap_value.make_pool", side_effect=ValueError("pool exhausted")):
            self.assertIsNone(CapValueEstimator(16).evaluate(state, (100., 0.)))
        self.assertEqual(semantic(state), before)

    def test_cap_measure_then_certain_clear_does_not_double_charge(self):
        """测量已承诺的未知队列被即时清除打断后，仍属于同一次顺扫。"""
        state = public_state()
        policy = policy_for(state)
        q = (500., 100.)
        action = policy._install(state, dict(kind="measure", channel=15, position=q,
                                            scan_unknown=False))
        self.assertEqual(policy.cap_used, 1)
        self.assertEqual(action["channel"], 15)
        reply(state, action, "near")
        action = policy.choose(state)
        self.assertEqual((action["kind"], action["channel"]), ("clear", 15))
        reply(state, action, "success")
        action = policy.choose(state)
        self.assertEqual(action["kind"], "measure")
        self.assertIn(action["channel"], range(16, 21))
        self.assertEqual(policy.cap_used, 1)
        self.assertEqual(policy.cap_estimator.evaluate.call_count, 1)

    def test_existing_planned_unknown_queue_survives_clear_without_cap_charge(self):
        """几何计划原已安排全扫时，清除插队也不应消耗cap预算。"""
        state = public_state()
        policy = policy_for(state)
        q = (500., 100.)
        action = policy._install(state, dict(kind="measure", channel=15, position=q,
                                            scan_unknown=True))
        reply(state, action, "near")
        action = policy.choose(state)
        self.assertEqual((action["kind"], action["channel"]), ("clear", 15))
        reply(state, action, "success")
        action = policy.choose(state)
        self.assertEqual(action["kind"], "measure")
        self.assertIn(action["channel"], range(16, 21))
        self.assertEqual(policy.cap_used, 0)
        policy.cap_estimator.evaluate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
