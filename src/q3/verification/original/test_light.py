"""轻量算子的因果边界、真实覆盖与关闭开关兼容性。"""
import copy
import json
import unittest
from unittest.mock import patch
from light_route import *
from light_run import check,read


class Checks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest,cls.cases,cls.receipt=check()
        item=cls.manifest['cases'][0]
        cls.selected=read(ROOT/item['baseline_selection'])['selected']
        cls.rows=[json.loads(x) for x in (ROOT/item['baseline_actions']).read_text().splitlines()]
        cls.state=a.CoverageInformationState()
        for r in cls.rows[:40]:cls.state.update(r,r['response'])

    def test_off_reproduces_original_public_prefix_and_full_decision(self):
        p=LightPolicy(self.selected);old=RefinedPolicy(self.selected,3,4)
        s=a.CoverageInformationState()
        with route_context(RunContext('OFF')):
            for r in self.rows[:40]:
                x,y=p.choose(s),old.choose(s)
                self.assertEqual(x,y)
                self.assertEqual(x['kind'],r['kind'])
                self.assertEqual(tuple(x['position']),tuple(r['position']))
                s.update(x,r['response'])
            self.assertEqual(p.choose(s),old.choose(s))
        self.assertIs(cr.covering_route,ORIGINAL_ROUTE)

    def test_transfer_accept_reject_and_no_mutation(self):
        jobs=[dict(kind='scan',position=(0,10),scan_unknown=True,_light_id=0),
              dict(kind='service',position=(10,0),scan_unknown=False,_light_id=1)]
        before=copy.deepcopy(jobs)
        # 有限集合覆盖替身只验证转移/拒绝逻辑；真实连续几何单独检查。
        cert=lambda route:any(j.get('scan_unknown') for j in route)
        route,record=transfer((0,0),jobs,1,cert)
        self.assertEqual(record['accepted'],1)
        self.assertEqual(record['events'][0]['added_service_labels'],[1])
        self.assertEqual(len(route),1)
        rejected,r=transfer((0,0),jobs,1,lambda x:any(j['kind']=='scan' for j in x))
        self.assertEqual(rejected,jobs);self.assertEqual(r['accepted'],0)
        self.assertEqual(jobs,before)

    def test_reinsertion_preserves_all_tasks_and_service_order(self):
        jobs=[dict(kind='service',position=(10,0),scan_unknown=False,_light_id=0),
              dict(kind='scan',position=(1,0),scan_unknown=True,_light_id=1),
              dict(kind='service',position=(20,0),scan_unknown=True,_light_id=2)]
        route,r=reinsert((0,0),jobs)
        self.assertEqual(r['accepted'],1)
        self.assertEqual(cr.route_length((0,0),route),20)
        self.assertEqual(sorted(route,key=lambda j:j['_light_id']),jobs)
        self.assertEqual([j['_light_id'] for j in route if j['kind']=='service'],[0,2])

    def test_real_certificate_all_modes_and_composition(self):
        s=copy.deepcopy(self.state);before=copy.deepcopy(s.__dict__)
        jobs,info=ORIGINAL_ROUTE(s,[])
        original=copy.deepcopy(jobs)
        cert=proof_function(cr.common_negative_circles(s),lambda:None)
        self.assertTrue(cert(jobs));self.assertFalse(cert([]))
        for mode in ('A','B','AB'):
            route,record=process(s,jobs,mode)
            self.assertTrue(cert(route))
            self.assertLessEqual(record['after_nominal_s'],record['before_nominal_s']+1e-6)
        route_a,_=process(s,jobs,'A');route_ab,_=process(s,route_a,'B')
        self.assertEqual(route_ab,process(s,jobs,'AB')[0])
        self.assertEqual(jobs,original)
        self.assertEqual(a.history_seed(s),a.history_seed(self.state))
        self.assertEqual(s.actions,self.state.actions)

    def test_online_and_continuation_use_same_hook(self):
        context=RunContext('AB')
        with route_context(context):
            cr.covering_route(self.state,[])
            token=SIMULATING.set(True)
            try:cr.covering_route(self.state,[])
            finally:SIMULATING.reset(token)
        self.assertEqual(context.counts['online'],context.counts['rollout'])
        self.assertEqual(len(context.online_plans),1)
        self.assertIs(cr.covering_route,ORIGINAL_ROUTE)

    def test_deadline_propagates_and_restores_hook(self):
        with self.assertRaises(TimeoutError):
            with route_context(RunContext('AB',0)):LightPolicy(self.selected).choose(self.state)
        self.assertIs(cr.covering_route,ORIGINAL_ROUTE)


if __name__=='__main__':unittest.main(verbosity=2)
