"""关键独立核验：动作计费、无信号覆盖证据、状态分离与结束约束。"""
import dataclasses
import math
import unittest

from runner import independent_cost, make_cases, visible_snapshot
from simulation import LocalEnvironment, Scenario, Source, noise_deg
from state import audit_state
from coverage_state import CoverageInformationState, coverage_certificate, verify_certificate
from patrol import PatrolPolicy
import geometry as g


def env(sources=(), noise='zero', seed=1):
    return LocalEnvironment(Scenario('unit', seed, 'unit', noise, tuple(sources)))


class IndependentLedgerTests(unittest.TestCase):
    def test_documented_199_seconds(self):
        environment = env()
        position, channel, ledger = (0., 0.), 1, 0.
        sequence = [('measure', (300., 400.), 1, 105),
                    ('measure', (300., 400.), 2, 111),
                    ('clear', (300., 0.), 3, 194),
                    ('measure', (300., 0.), 2, 199)]
        for kind, q, j, expected in sequence:
            action = dict(kind=kind, position=q, channel=j)
            response = environment.act(action)
            # 故意损坏环境提供的费用明细，证明独立账本不读取它。
            response['costs'] = {'move_s': -1e9}
            costs, channel = independent_cost(position, channel, action, response)
            ledger += sum(costs.values())
            self.assertEqual(ledger, expected)
            self.assertEqual(ledger, environment.virtual_time_s)
            position = q
        self.assertEqual(channel, 2)

    def test_shared_station_charges_each_channel(self):
        environment = env([Source(1, (100., 0.), 1000.)])
        position, channel, ledger = (0., 0.), 1, 0.
        for j in range(1, 21):
            action = dict(kind='measure', position=(300., 400.), channel=j)
            response = environment.act(action)
            costs, channel = independent_cost(position, channel, action, response)
            ledger += sum(costs.values())
            position = action['position']
        self.assertEqual(ledger, 100 + 20 * 5 + 19)

    def test_fixed_noise_not_resampled(self):
        for kind in ('zero', 'smooth', 'biased', 'hashed'):
            for q in ((0., 0.), (1500., .001), (-800., 300.)):
                value = noise_deg(121, kind, q, 7)
                self.assertLessEqual(abs(value), 1.)
                self.assertEqual(value, noise_deg(121, kind, q, 7))


class ContinuousCoverageTests(unittest.TestCase):
    def test_free_nonanchor_cover_certifies_absence(self):
        # 旋转七点覆盖网，均非原固定锚点；有余量的连续覆盖应能确认。
        angle = math.radians(11)
        points = [(30., 0.)] + [(1200 * math.cos(angle + k * math.pi / 3),
                                1200 * math.sin(angle + k * math.pi / 3)) for k in range(6)]
        state, environment = CoverageInformationState(), env()
        for q in points:
            action = dict(kind='measure', position=q, channel=20)
            state.update(action, environment.act(action))
        self.assertEqual(state.channels[20].status, 'absent')
        cert = state.coverage(20)
        self.assertTrue(cert.complete)
        self.assertTrue(cert.rational_verified)
        self.assertTrue(verify_certificate(cert, require_complete=True))
        self.assertLess(len(state.channels[20].anchors_missed), 7)

    def test_two_disks_leave_real_gap(self):
        cert = coverage_certificate((((-750., 0.), 1000.), ((750., 0.), 1000.)))
        self.assertFalse(cert.complete)
        gap = (0., 1799.)
        self.assertTrue(any(b.x0 <= gap[0] <= b.x1 and b.y0 <= gap[1] <= b.y1 for b in cert.unresolved))
        self.assertTrue(verify_certificate(cert))

    def test_certificate_tamper_rejected(self):
        cert = coverage_certificate((((0., 0.), 3000.),))
        self.assertTrue(cert.complete)
        broken = dataclasses.replace(cert, exclusions=(((0., 0.), 10.),))
        with self.assertRaises(AssertionError):
            verify_certificate(broken, require_complete=True)

    def test_ten_seen_does_not_imply_complete(self):
        state = CoverageInformationState()
        environment = env([Source(j, (10., 0.), 1000.) for j in range(1, 11)])
        for j in range(1, 11):
            action = dict(kind='clear', position=(0., 0.), channel=j)
            state.update(action, environment.act(action))
        self.assertEqual(len(state.ever_seen), 10)
        self.assertFalse(state.complete)
        self.assertEqual(state.channels[20].status, 'unknown')
        audit_state(state, environment)


class PatrolIntegrationTests(unittest.TestCase):
    def test_initial_scan_does_not_force_origin(self):
        points = [[-820., 20.], [720., 100.]]
        policy = PatrolPolicy({'initial_points': points})
        state, environment = CoverageInformationState(), env([Source(1, (10., 100.), 1500.)])
        positions = []
        for _ in range(40):
            action = policy.choose(state)
            positions.append(tuple(action['position']))
            self.assertEqual(action['kind'], 'measure')
            self.assertEqual(action['phase'], 'initial')
            state.update(action, environment.act(action))
            audit_state(state, environment)
        self.assertEqual(set(positions), {tuple(p) for p in points})
        self.assertNotIn((0., 0.), positions)

    def test_cleared_target_does_not_break_shared_queue(self):
        policy = PatrolPolicy()
        policy.initial_finish_s, policy.phase = 0., 'service'
        state = CoverageInformationState()
        environment = env([Source(1, (0., 0.), 1000.), Source(2, (400., 0.), 1000.)])
        action = dict(kind='measure', position=(0., 0.), channel=1)
        state.update(action, environment.act(action))
        policy.start_station(state, (0., 0.), 'unit_station', priority=1)
        action = policy.choose(state)
        self.assertEqual((action['kind'], action['channel']), ('clear', 1))
        state.update(action, environment.act(action))
        action = policy.choose(state)
        self.assertEqual(action['kind'], 'measure')
        self.assertNotEqual(action['channel'], 1)
        self.assertEqual(tuple(action['position']), (0., 0.))
        state.update(action, environment.act(action))
        audit_state(state, environment)

    def test_case_splits_and_known_failure(self):
        dev, hold, stress = (make_cases(name) for name in ('development', 'holdout', 'stress'))
        self.assertEqual((len(dev), len(hold), len(stress)), (12, 24, 8))
        self.assertIn('edge_biased_161104', {c.name for c in dev})
        self.assertFalse({c.seed for c in dev} & {c.seed for c in hold})
        self.assertFalse({c.seed for c in dev + hold} & {c.seed for c in stress})

    def test_visible_snapshot_has_no_truth(self):
        snap = visible_snapshot(CoverageInformationState(), 1)
        self.assertNotIn('sources', snap)
        self.assertNotIn('real_n', snap)
        self.assertNotIn('radius', snap['selected_channel'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
