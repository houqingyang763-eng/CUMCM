"""检查候选的全清边界与计划扫描承诺落地，避免只验证分数函数。"""
import unittest

from candidate import CandidateConfig, CandidatePolicy, clearing_plans
from common import Q4State
from simulation import LocalEnvironment, Scenario, Source


class CandidateChecks(unittest.TestCase):
    def test_uncertified_custom_discovery_points_rejected(self):
        with self.assertRaisesRegex(ValueError, '覆盖证书'):
            CandidatePolicy(CandidateConfig(discovery_points=((0., 0.),)))

    def test_service_without_scan_commitment_leaves_unknown_unmeasured(self):
        state = Q4State()
        env = LocalEnvironment(Scenario('fixture', 1, 'custom', 'zero',
            (Source(1, (900., 0.), 1500., None),)))
        a = dict(kind='measure', position=(0., 0.), channel=1)
        state.update(a, env.act(a))
        policy = CandidatePolicy(CandidateConfig(prune_planned_stops=True))
        action = policy._install(state, dict(kind='measure', channel=1,
                    position=(600., 50.), scan_unknown=False))
        self.assertEqual(action['channel'], 1)
        state.update(action, env.act(action))
        while (action := policy._station_action(state)) is not None:
            self.assertEqual(action['channel'], 1)
        self.assertTrue(all(not c.observations for j, c in state.channels.items() if j != 1))

    def test_service_with_commitment_scans_all_still_unknown(self):
        state = Q4State()
        policy = CandidatePolicy(CandidateConfig(prune_planned_stops=True))
        action = policy._station(state, (40., 80.), 'fixture', scan_unknown=True)
        seen = {action['channel']}
        while (action := policy._station_action(state)) is not None:
            seen.add(action['channel'])
        self.assertEqual(seen, set(range(1, 21)))

    def test_uncertain_clear_does_not_promise_unknown_scan(self):
        state = Q4State()
        policy = CandidatePolicy(CandidateConfig(prune_planned_stops=True))
        policy._install(state, dict(kind='try', channel=1, position=(10., 10.), scan_unknown=False))
        self.assertIsNone(policy.clear_scan_commitment)

    def test_certified_clear_records_exact_scan_location(self):
        state = Q4State()
        policy = CandidatePolicy(CandidateConfig(prune_planned_stops=True))
        policy._install(state, dict(kind='clear', channel=1, position=(10., 10.), scan_unknown=True))
        self.assertEqual(policy.clear_scan_commitment, (1, (10., 10.)))

    def test_complete_rollout_uses_remaining_cost_and_preserves_state(self):
        source = Source(1, (2., 0.), 1500., None)
        world = Scenario('fixture', 1, 'custom', 'zero', (source,))
        state, env = Q4State(), LocalEnvironment(world)
        a = dict(kind='measure', position=(0., 0.), channel=1)
        state.update(a, env.act(a))
        for j, c in state.channels.items():
            if j != 1:
                c.status = 'absent'  # 独立局部夹具，其余频道由夹具给定。
        before = (state.virtual_time_s, state.actions, state.channels[1].status)
        policy = CandidatePolicy(CandidateConfig(prune_planned_stops=True))
        costs = policy._rollout(state, dict(kind='clear', channel=1,
                           position=(0., 0.), scan_unknown=False), [world])
        self.assertEqual(costs, [5.])
        self.assertEqual(before, (state.virtual_time_s, state.actions, state.channels[1].status))

    def test_expired_rollout_does_not_mutate_live_state(self):
        state = Q4State()
        policy = CandidatePolicy()
        with self.assertRaisesRegex(ValueError, '预算'):
            policy._rollout(state, dict(kind='scan', position=(0., 0.)),
                [Scenario('fixture', 1, 'custom', 'zero', ())], deadline=0.)
        self.assertEqual(state.actions, 0)


if __name__ == '__main__':
    unittest.main()
