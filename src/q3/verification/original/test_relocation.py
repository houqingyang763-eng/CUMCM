"""挪站关键接口：关闭兼容、真实证书、多站不变性和退化位置。"""
import copy
import json
import math
import unittest
from unittest.mock import patch
from relocate import lr,relocation,relocation_context,RelocationPolicy
from relocation_probe import BASE,OUT,read
from light_run import check


class Checks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest,_,_=check()
        probe=read(OUT/'probe.json');record=next(r for r in probe['cases'] if r['case']=='line_smooth_320118')['first_plan']
        rows=[json.loads(x) for x in (BASE/'A/line_smooth_320118/actions.jsonl').read_text().splitlines()]
        cls.s=lr.a.CoverageInformationState()
        for r in rows[:record['at_action']]:cls.s.update(r,r['response'])
        cls.jobs=record['before_route']

    def test_real_geometry_multi_station_invariants(self):
        s=copy.deepcopy(self.s);jobs=copy.deepcopy(self.jobs);before=copy.deepcopy(jobs)
        history=lr.a.history_seed(s);route,record=relocation(s,jobs)
        self.assertGreater(record['nominal_saving_s'],30)
        self.assertTrue(lr.proof_function(lr.cr.common_negative_circles(s),lambda:None)(route))
        self.assertEqual(history,lr.a.history_seed(s));self.assertEqual(jobs,before)
        self.assertEqual(len(route),len(jobs))
        for x,y in zip(route,jobs):self.assertEqual({k:v for k,v in x.items() if k!='position'},{k:v for k,v in y.items() if k!='position'})
        for e in record['events']:
            self.assertGreater(e['fraction'],0);self.assertLess(e['fraction'],1)
            for k in (0,1):self.assertAlmostEqual(e['new_position'][k],e['old_position'][k]+e['fraction']*(e['toward'][k]-e['old_position'][k]))
        for i,job in enumerate(route):
            self.assertGreater(math.dist(job['position'],s.position),1e-3)
            self.assertTrue(all(math.dist(job['position'],p)>1e-3 for c in s.channels.values() if c.status=='unknown' for p in c.measured))
            self.assertTrue(all(math.dist(job['position'],j['position'])>1e-3 for j in route[:i]))

    def test_outside_public_phase_is_unchanged(self):
        s=copy.deepcopy(self.s)
        next(iter(s.channels.values())).status='found'
        route,record=relocation(s,self.jobs);self.assertIs(route,self.jobs);self.assertFalse(record['eligible'])
        for c in s.channels.values():c.status='absent'
        self.assertIs(relocation(s,self.jobs)[0],self.jobs)

    def test_rejected_coverage_preserves_original_and_real_bad_route_rejected(self):
        before=copy.deepcopy(self.jobs)
        same=lambda route:all(tuple(j['position'])==tuple(k['position']) for j,k in zip(route,before)) and len(route)==len(before)
        with patch.object(lr,'proof_function',return_value=same):
            route,record=relocation(self.s,before)
        self.assertEqual(record['events'],[])
        self.assertEqual([tuple(j['position']) for j in route],[tuple(j['position']) for j in before])
        proof=lr.proof_function(lr.cr.common_negative_circles(self.s),lambda:None)
        self.assertFalse(proof([]))
        with self.assertRaises(AssertionError):relocation(self.s,[])

    def test_off_matches_A_opening_and_next_full_decision(self):
        item=self.manifest['cases'][0]
        selected=read(lr.ROOT/item['baseline_selection'])['selected']
        rows=[json.loads(x) for x in (BASE/'A'/item['name']/'actions.jsonl').read_text().splitlines()]
        old,new=lr.LightPolicy(selected),RelocationPolicy(selected);s=lr.a.CoverageInformationState()
        for r in rows[:40]:
            with lr.route_context(lr.RunContext('A')):x=old.choose(s)
            with relocation_context(lr.RunContext('A'),enabled=False):y=new.choose(s)
            self.assertEqual(x,y);s.update(x,r['response'])
        with lr.route_context(lr.RunContext('A')):x=old.choose(s)
        with relocation_context(lr.RunContext('A'),enabled=False):y=new.choose(s)
        self.assertEqual(x,y)

    def test_online_rollout_hook_and_timeout_restore(self):
        context=lr.RunContext('A')
        with relocation_context(context):
            x,_=lr.cr.covering_route(self.s,[])
            token=lr.SIMULATING.set(True)
            try:y,_=lr.cr.covering_route(self.s,[])
            finally:lr.SIMULATING.reset(token)
        self.assertEqual(x,y);self.assertEqual(context.relocation_counts['online'],context.relocation_counts['rollout'])
        self.assertIs(lr.cr.covering_route,lr.ORIGINAL_ROUTE)
        with self.assertRaises(TimeoutError):
            with relocation_context(lr.RunContext('A',0)):lr.cr.covering_route(self.s,[])
        self.assertIs(lr.cr.covering_route,lr.ORIGINAL_ROUTE)


if __name__=='__main__':unittest.main(verbosity=2)
