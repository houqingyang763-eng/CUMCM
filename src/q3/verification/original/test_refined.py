import copy
import itertools
import json
import math
import unittest
from unittest.mock import patch
from pathlib import Path

from refined import RefinedPolicy, dominated_negative, clearing_plans, transverse_points
from posterior import a, g, sample_worlds, subset_distribution, radius_interval
from state import ChannelState

HERE = Path(__file__).resolve().parent


class Checks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = json.loads((HERE.parent/'adaptive_second/demonstration/replay.json').read_text())
        cls.states = {}
        state = a.CoverageInformationState()
        for row in cls.raw['actions']:
            state.update(row,row['response'])
            if row['step'] in (56,74,86,93,98):
                cls.states[row['step']] = copy.deepcopy(state)

    def test_redundancy_proof_without_truth(self):
        s = self.states[93]
        q = tuple(self.raw['actions'][93]['position'])
        self.assertIsNotNone(dominated_negative(s.channels[4],q))
        self.assertIsNone(dominated_negative(s.channels[15],q))
        # 未知源和只有方向没有阴性记录不能套用。
        self.assertIsNone(dominated_negative(ChannelState(1),q))

    def test_near_measurement_not_blanket_removed(self):
        s = self.states[86]
        self.assertIsNone(dominated_negative(s.channels[15],(314.3680527,-1584.1103844)))

    def test_multiclear_c20_continuous_coverage(self):
        s = self.states[86]
        plans = clearing_plans(s,s.channels[20])
        plan = next(p for p in plans if p['id']=='clear2')
        self.assertLess(max(plan['radii']),20)
        self.assertAlmostEqual(plan['worst_local_s'],98.1465894,places=5)
        # 独立覆盖多边形边界及内部凸组合，不使用真实源坐标。
        poly = s.channels[20].support()
        for x,y in itertools.product(poly,repeat=2):
            for i in range(21):
                p = tuple(x[k]*(1-i/20)+y[k]*i/20 for k in (0,1))
                self.assertLessEqual(min(math.dist(p,q) for q in plan['points']),20)

    def test_large_disk_not_certified_by_radius(self):
        c = ChannelState(1,status='found')
        c.polygon = g.outer_disk((0,0),100)
        self.assertEqual(clearing_plans(a.CoverageInformationState(),c),[])

    def test_both_mirror_candidates_retained(self):
        s = self.states[74]
        points = transverse_points(s,s.channels[20])
        self.assertEqual(len(points),2)
        self.assertAlmostEqual(math.dist(s.position,points[0]),math.dist(s.position,points[1]),places=5)
        self.assertLess(min(math.hypot(*q) for q in points),1200)

    def test_count_dp_matches_enumeration(self):
        masses = [.1,.4,.8,.2]
        _,ks,w = subset_distribution(masses,10)
        ref=[]
        for k in ks:
            ref.append(sum(math.prod(masses[i] for i in ix) for ix in itertools.combinations(range(4),k))/math.comb(20,10+k))
        total=sum(ref)
        for x,y in zip(w,ref):
            self.assertAlmostEqual(x,y/total,places=12)

    def test_conditioned_worlds_respect_all_history(self):
        s = self.states[74]
        snapshot = copy.deepcopy(s)
        worlds,info=sample_worlds(s,8,512)
        for world in worlds:
            self.assertTrue(10<=len(world.sources)+sum(c.status=='cleared' for c in s.channels.values())<=16)
            for source in world.sources:
                bounds=radius_interval(s.channels[source.channel],source.position)
                self.assertIsNotNone(bounds)
                self.assertTrue(bounds[0]<=source.radius<=bounds[1])
                for q,result,bearing in s.channels[source.channel].observations:
                    feedback=a.LocalEnvironment(world).act({'kind':'measure','position':q,'channel':source.channel})
                    self.assertEqual(feedback['measure_result'],result)
        self.assertEqual(a.history_seed(s),a.history_seed(snapshot))
        self.assertEqual(s.virtual_time_s,snapshot.virtual_time_s)

    def test_fixed_history_in_rollout(self):
        s=self.states[74]
        world=sample_worlds(s,1,512)[0][0]
        env=a.ConditionalEnvironment(world,s)
        j=next(x.channel for x in world.sources if s.channels[x.channel].observations)
        q,result,bearing=s.channels[j].observations[0]
        action={'kind':'measure','position':q,'channel':j}
        first=env.act(action);second=env.act(action)
        self.assertEqual(first['measure_result'],result)
        self.assertEqual(first.get('svd_deg'),bearing)
        self.assertEqual(first.get('svd_deg'),second.get('svd_deg'))

    def test_decision_is_unchanged_by_external_truth(self):
        # 选择接口只接收公开state；与演示真值解耦的条件样本可重复。
        s=self.states[74]
        w1,_=sample_worlds(s,2)
        w2,_=sample_worlds(copy.deepcopy(s),2)
        self.assertEqual(w1,w2)

    def test_recheck_uses_distinct_repeatable_samples(self):
        s=self.states[74]
        original,_=sample_worlds(s,2)
        fresh,_=sample_worlds(s,2,salt=310913)
        repeated,_=sample_worlds(s,2,salt=310913)
        self.assertNotEqual(original,fresh)
        self.assertEqual(fresh,repeated)

    def test_recheck_accepts_and_rejects_by_fresh_cost(self):
        from verified import VerifiedPolicy
        p=VerifiedPolicy()
        records=[{'id':'original','mean_s':100},{'id':'alternative','mean_s':90}]
        with patch('verified.sample_worlds',return_value=([None]*8,{})):
            with patch.object(p,'simulate',side_effect=lambda s,w,o,act:100 if o['id']=='original' else 120):
                chosen,info=p.select_candidate(self.states[74],records,{})
                self.assertEqual(chosen['id'],'original');self.assertFalse(info['recheck']['accepted'])
            with patch.object(p,'simulate',side_effect=lambda s,w,o,act:100 if o['id']=='original' else 80):
                chosen,info=p.select_candidate(self.states[74],records,{})
                self.assertEqual(chosen['id'],'alternative');self.assertTrue(info['recheck']['accepted'])

    def test_empty_station_does_not_disable_new_point_decision(self):
        s=copy.deepcopy(self.states[74])
        p=RefinedPolicy(level=2)
        p.phase='service';p.initial_index=2
        p.station=s.position;p.station_channels=[];p.station_reason='old_station'
        # 使用真实公开状态与原规划器，仅替换评分，核对候选确实到达选择层。
        with patch('refined.sample_worlds',return_value=([None],{})):
            with patch.object(p,'simulate',side_effect=lambda state,w,option,original: 0 if option['kind']=='scan' else 100):
                action=p.choose_joint(s)
        self.assertTrue(p.decisions)
        self.assertTrue(any(x['id'].startswith('mirror') for x in p.decisions[-1]['options']))
        self.assertTrue(action['refinement_choice'].startswith('mirror'))


if __name__=='__main__':
    unittest.main()
