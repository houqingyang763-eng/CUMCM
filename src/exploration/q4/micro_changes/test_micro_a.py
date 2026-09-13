"""冻结前检查：真实历史单点诊断、任务保留、相等路线边界。"""
import json
import math
from pathlib import Path
import unittest
from micro_a import compare_prefixes, MicroAPolicy, PROJECT
from common import Q4State


class MicroATests(unittest.TestCase):
    def test_pressure_prefix_choice_and_jobs(self):
        root=PROJECT/'outputs/q4/pressure01/cases/pressure_944001_edge_tangent_hashed/selected'
        result=json.loads((root/'result.json').read_text(encoding='utf-8'))
        rows=[json.loads(s) for s in (root/'actions.jsonl').read_text(encoding='utf-8').splitlines()]
        plan=next(p for p in result['policy_metadata']['plans'] if p['at_action']==266)
        route=plan['jobs']; start=rows[265]['position']
        index=next(i for i,j in enumerate(route) if j.get('channel')==12)
        chosen,record=compare_prefixes(start,route,[index])
        self.assertEqual(chosen[0]['channel'],12)
        self.assertEqual(sorted(map(id,chosen)),sorted(map(id,route)))
        self.assertAlmostEqual(record['worst_regret_s'][0],487.46336963530325,places=5)
        self.assertAlmostEqual(record['worst_regret_s'][1],84.67953807453253,places=5)

    def test_equal_routes_preserve_original(self):
        route=[dict(kind='clear',position=(1,0),channel=1),dict(kind='scan',position=(2,0))]
        chosen,record=compare_prefixes((0,0),route,[0])
        self.assertEqual(record['chosen_index'],0)
        self.assertEqual(chosen,route)

    def test_real_prefix_plan_does_not_mutate_public_state(self):
        root=PROJECT/'outputs/q4/pressure01/cases/pressure_944001_edge_tangent_hashed/selected'
        rows=[json.loads(s) for s in (root/'actions.jsonl').read_text(encoding='utf-8').splitlines()]
        state=Q4State()
        for a in rows[:266]: state.update(a,a['response'])
        before=(state.position,state.actions,state.virtual_time_s,
                [(c.status,len(c.observations),len(c.exclusions)) for c in state.channels.values()])
        policy=MicroAPolicy(); route=policy._plan(state)
        self.assertEqual(route[0]['channel'],12)
        self.assertEqual(before,(state.position,state.actions,state.virtual_time_s,
                [(c.status,len(c.observations),len(c.exclusions)) for c in state.channels.values()]))
        self.assertTrue(all(math.dist(route[0]['position'],p)<20 for p in state.channels[12].support()))
        n=len(policy.a_decisions);policy._plan(state)
        self.assertEqual(len(policy.a_decisions),n)

if __name__=='__main__': unittest.main()
