"""只测足以改变P1实验解释的接口；固定历史公共状态，不新跑性能案例。"""
import copy
import itertools
import json
import math
import time
import unittest
from unittest.mock import patch

from p1_policy import P1Policy
from p1_tasks import task, plan_route, service_pool, nominal_cost, a, Q3
from p1_run import validate_inputs, ROOT
from state import ChannelState


class Checks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest, cls.items = validate_inputs()
        cls.case, item = cls.items[0]
        cls.selection = json.loads((ROOT/item['artifacts']['selection.json']['path']).read_text())['selected']
        cls.rows = [json.loads(s) for s in (ROOT/item['artifacts']['f3/actions.jsonl']['path']).read_text().splitlines()]
        cls.s = a.CoverageInformationState()
        for row in cls.rows[:40]:
            cls.s.update(row, row['response'])

    def policy(self):
        p = P1Policy(self.selection)
        p.initial_index = 2; p.initial_finish_s = self.s.virtual_time_s; p.phase = 'service'
        return p

    def test_baseline_fingerprints(self):
        self.assertEqual(len(self.items), 8)

    def test_disabled_policy_exact_f3_public_prefix(self):
        from refined import RefinedPolicy
        p = P1Policy(self.selection, enabled=False)
        old = RefinedPolicy(self.selection, 3, 4)
        s = a.CoverageInformationState()
        for row in self.rows[:40]:
            x, y = p.choose(s), old.choose(s)
            self.assertEqual(x, y)
            self.assertEqual(x['kind'], row['kind'])
            self.assertEqual(tuple(x['position']), tuple(row['position']))
            s.update(x, row['response'])
        # 比较完整原F3在后续公开状态的一个决策，不把它当成新整局成绩。
        self.assertEqual(p.choose(s), old.choose(s))

    def test_guaranteed_footprint_all_exits_and_orders(self):
        for points in itertools.permutations([(0., 0.), (35., 0.), (20., 28.)]):
            job = task('clear', points, 1, True)
            ref, r = job['footprint']
            for k in range(72):
                x = (ref[0]+r*math.cos(k*math.pi/36), ref[1]+r*math.sin(k*math.pi/36))
                self.assertTrue(all(math.dist(x, q) <= 1000+1e-8 for q in points))

    def test_early_success_and_actual_exit_scans(self):
        for count in (2, 3):
            for hit in range(count):
                s = a.CoverageInformationState()
                for c in s.channels.values(): c.status = 'absent'
                s.channels[1].status = 'found'; s.channels[2].status = 'unknown'
                p = P1Policy(self.selection); p.phase = 'service'
                job = task('clear', [(40.*i, 0.) for i in range(count)], 1, True)
                job['scan_channels'] = [2]
                act = p.install_task(s, job); virtual = 0.; previous = (0., 0.)
                for i in range(hit+1):
                    self.assertEqual(act['kind'], 'clear'); self.assertEqual(act['p1_attempt'], i+1)
                    virtual += math.dist(previous, act['position'])/5+(5 if i == hit else 3)
                    previous = tuple(act['position']); s.position = previous; s.actions += 1
                    if i == hit: s.channels[1].status = 'cleared'
                    act = p.active_action(s)
                self.assertEqual(act['kind'], 'measure'); self.assertEqual(act['channel'], 2)
                self.assertEqual(tuple(act['position']), job['points'][hit])
                self.assertEqual(s.measuring_channel, 1)
                self.assertAlmostEqual(virtual, 40*hit/5+3*hit+5)
                self.assertEqual(p.task_events[-1]['cancelled'], count-hit-1)

    def test_exhausted_certified_task_fails(self):
        s = a.CoverageInformationState(); s.channels[1].status = 'found'
        p = self.policy(); p.install_task(s, task('clear', [(0.,0.)], 1, True))
        with self.assertRaises(AssertionError): p.active_action(s)

    def test_channel_certificates_and_no_state_pollution(self):
        s = copy.deepcopy(self.s); p = self.policy()
        before = (a.history_seed(s), s.virtual_time_s, [(j,c.status) for j,c in s.channels.items()])
        route, info = plan_route(s, service_pool(s,p))
        self.assertTrue(all(x['conditional_coverage_complete'] for x in info['per_channel'].values()))
        self.assertEqual(before, (a.history_seed(s),s.virtual_time_s,[(j,c.status) for j,c in s.channels.items()]))
        unknown = [c for c in s.channels.values() if c.status == 'unknown']
        for c, d in itertools.combinations(unknown, 2):
            if c.observations == d.observations:
                self.assertEqual([i for i,t in enumerate(route) if c.channel in t['scan_channels']],
                                 [i for i,t in enumerate(route) if d.channel in t['scan_channels']])

    def test_prefix_replaces_source_slot(self):
        s = copy.deepcopy(self.s); p = self.policy(); pool = service_pool(s,p)
        first = copy.deepcopy(next(iter(pool.values()))[0])
        route, info = plan_route(s, pool, prefix=first)
        self.assertEqual(sum(t['channel']==first['channel'] for t in route), 1)
        self.assertEqual(route[0]['points'], first['points'])
        self.assertAlmostEqual(info['total_s'],nominal_cost(s,route)['total_s'])

    def test_candidate_enumeration_does_not_mutate_controller(self):
        s = copy.deepcopy(self.s); p = self.policy(); before = copy.deepcopy(p.__dict__)
        old = p.fork(); action = a.PatrolPolicy.choose_joint(old,s)
        options, _ = p.candidates(s,old,action)
        self.assertEqual(before,p.__dict__)
        self.assertEqual(options[0]['id'],'original')
        self.assertEqual(options[-1]['id'],'channel_joint')

    def test_no_nested_sampling_and_all_failed_sample_reverts(self):
        p = self.policy(); s = copy.deepcopy(self.s); p.lookahead=False
        with patch('p1_policy.sample_worlds',side_effect=AssertionError('nested sample')):
            self.assertIn(p.choose(s)['kind'],('measure','clear'))
        p = self.policy(); old = p.fork(); expected = a.PatrolPolicy.choose_joint(old,s)
        with patch('p1_policy.sample_worlds',side_effect=ValueError('forced sampling exhaustion')):
            got = p.choose(s)
        for key in ('kind','position','channel'): self.assertEqual(got[key],expected[key])
        self.assertEqual(p.decisions[-1]['chosen'],'original')
        self.assertEqual(p.station_channels,old.station_channels)

    def test_deadline_applies_inside_decision(self):
        p = self.policy(); p.deadline=0
        with self.assertRaises(TimeoutError): p.choose(copy.deepcopy(self.s))

    def test_single_conditional_world_completes_without_nested_sampling(self):
        from posterior import sample_worlds
        p = self.policy(); p.deadline=time.perf_counter()+120
        s = copy.deepcopy(self.s); old=p.fork(); action=a.PatrolPolicy.choose_joint(old,s)
        options,_=p.candidates(s,old,action)
        worlds,_=sample_worlds(s,4)
        with patch('p1_policy.sample_worlds',side_effect=AssertionError('nested sample')):
            seconds,steps,fallbacks=p.rollout(s,worlds[0],options[-1])
        self.assertGreater(seconds,0); self.assertLess(steps,3000)


if __name__=='__main__':
    unittest.main(verbosity=2)
