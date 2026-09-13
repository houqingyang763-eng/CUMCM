"""关键独立核验：动作计费、无信号覆盖证据、状态分离与结束约束。"""
import dataclasses
import copy
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

    def test_planned_future_scans_do_not_prove_absence(self):
        state, environment = CoverageInformationState(), env()
        action = dict(kind='measure', position=(-750., 0.), channel=20,
                      planned_positions=g.ANCHORS, estimated_absence_probability=1.)
        state.update(action, environment.act(action))
        self.assertEqual(state.channels[20].status, 'unknown')
        self.assertEqual(len(state.channels[20].exclusions), 1)
        self.assertFalse(state.coverage(20).complete)

    def test_empty_scoring_grid_does_not_prove_absence(self):
        state = CoverageInformationState()
        state.channels[20].sample_mask = 0
        self.assertEqual(state.channels[20].status, 'unknown')
        self.assertFalse(state.complete)
        self.assertFalse(state.coverage(20).complete)


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


class CoveringRouteTests(unittest.TestCase):
    def test_no_cross_channel_negative_evidence(self):
        from covering_route import common_negative_circles
        state, environment = CoverageInformationState(), env()
        for c in state.channels.values():
            if c.channel not in (19, 20):
                c.status = 'absent'
        for q, channel in [((-700., 0.), 19), ((700., 0.), 20)]:
            action = dict(kind='measure', position=q, channel=channel)
            state.update(action, environment.act(action))
        self.assertEqual(common_negative_circles(state), [])
        action = dict(kind='measure', position=(-700., 0.), channel=20)
        state.update(action, environment.act(action))
        self.assertEqual(common_negative_circles(state), [((-700., 0.), 1000.)])

    def test_plan_preserves_service_and_does_not_change_real_state(self):
        from covering_route import covering_route, common_negative_circles, planned_certificate
        state, environment = CoverageInformationState(), env()
        for q in ((-150., 0.), (600., 0.)):
            for channel in range(1, 21):
                action = dict(kind='measure', position=q, channel=channel)
                state.update(action, environment.act(action))
        jobs = [{'kind': 'service', 'position': (1100., 400.), 'channel': 1},
                {'kind': 'service', 'position': (-1000., -500.), 'channel': 2}]
        before = copy.deepcopy([(c.status, c.observations, c.exclusions)
                                for c in state.channels.values()])
        route, metadata = covering_route(state, jobs)
        self.assertEqual({j['channel'] for j in route if j['kind'] == 'service'}, {1, 2})
        self.assertTrue(all(j['kind'] == 'service' or j['scan_unknown'] for j in route))
        self.assertTrue(metadata['planned_coverage_complete'])
        cert = planned_certificate(common_negative_circles(state), route)
        self.assertTrue(verify_certificate(cert, require_complete=True))
        self.assertEqual(before, [(c.status, c.observations, c.exclusions)
                                  for c in state.channels.values()])
        self.assertFalse(state.complete)
        # 只有实际执行各扫描站阴性检测，才允许状态真正完成。
        for job in route:
            if not job['scan_unknown']:
                continue
            for c in state.channels.values():
                if c.status == 'unknown':
                    action = dict(kind='measure', position=job['position'], channel=c.channel)
                    state.update(action, environment.act(action))
        self.assertTrue(state.complete)
        self.assertTrue(all(c.status == 'absent' for c in state.channels.values()))

    def test_insertion_includes_open_end_and_two_opt_preserves_jobs(self):
        from covering_route import insertion, optimize_route, route_length
        start = (0., 0.)
        jobs = [{'kind': 'service', 'position': (10., 0.), 'channel': 1},
                {'kind': 'service', 'position': (20., 0.), 'channel': 2}]
        self.assertEqual(insertion(start, jobs, (25., 0.)), (5., 2))
        self.assertEqual(insertion(start, jobs, (5., 0.)), (0., 0))
        route = optimize_route(start, list(reversed(jobs)))
        self.assertEqual({j['channel'] for j in route}, {1, 2})
        self.assertEqual(route_length(start, route), 20.)

    def test_arrival_scan_runs_at_real_clearance_position(self):
        policy = PatrolPolicy({'planning': 'covering'})
        policy.initial_finish_s, policy.phase = 0., 'service'
        state, environment = CoverageInformationState(), env([Source(1, (100., 0.), 1000.)])
        action = dict(kind='clear', position=(100., 0.), channel=1)
        state.update(action, environment.act(action))
        policy.after_arrival_scan = ((100., 0.), True, 1)
        action = policy.choose(state)
        self.assertEqual(action['kind'], 'measure')
        self.assertEqual(action['reason'], 'planned_clearance_scan')
        self.assertNotEqual(action['channel'], 1)
        self.assertEqual(tuple(action['position']), state.position)


if __name__ == '__main__':
    unittest.main(verbosity=2)
