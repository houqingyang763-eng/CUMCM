import copy
import json
import math
import unittest
from pathlib import Path
from policy import UtilityPolicy,utility,a,g
from refined import clearing_plans
from channel_route import channel_route,negative_circles
from coverage_state import coverage_certificate

ROOT=Path(__file__).resolve().parents[1]/'refinement/runs/demo_f3_20260912'
CASE=json.loads((ROOT/'cases.json').read_text(encoding='utf-8'))[0]
DIRECTORY=ROOT/CASE['name']
ACTIONS=[json.loads(x) for x in (DIRECTORY/'f3/actions.jsonl').read_text(encoding='utf-8').splitlines()]


def state_at(n):
    state=a.CoverageInformationState()
    for row in ACTIONS[:n]:state.update(row,row['response'])
    return state


class Checks(unittest.TestCase):
    def test_high_prior_utility_does_not_select_provable_noop(self):
        from revision import BreakthroughPolicy
        p=Path(__file__).resolve().parent/'runs/fresh_loaded/uniform_hashed_20260925_n12/s4/actions.jsonl'
        state=a.CoverageInformationState()
        for line in p.read_text(encoding='utf-8').splitlines():
            row=json.loads(line);state.update(row,row['response'])
        best,_=BreakthroughPolicy(None).best_view(state,state.channels[13])
        self.assertFalse(best.get('certain_redundant',False))
        self.assertGreater(best['gain'],0)

    def test_utility(self):
        self.assertEqual(utility(20),1)
        self.assertAlmostEqual(utility(40),.19598220390720883)
        self.assertLess(utility(60),.001)
        self.assertEqual(utility(10000),0)
        self.assertTrue(all(utility(r)>=utility(r+1) for r in range(0,500)))

    def test_same_location_has_zero_gain(self):
        state=state_at(84);policy=UtilityPolicy(None)
        c=state.channels[9]
        self.assertEqual(policy.predict(state,c,c.observations[-1][0])['gain'],0)

    def test_two_clear_cover_at_85(self):
        state=state_at(84);c=state.channels[15]
        plans=clearing_plans(state,c)
        two=next(x for x in plans if x['id']=='clear2')
        self.assertTrue(all(r<20 for r in two['radii']))
        # Dense convex combinations independently probe the claimed union.
        poly=c.support()
        for x in poly:
            for y in poly:
                for k in range(21):
                    p=g.add(g.mul(x,k/20),g.mul(y,1-k/20))
                    self.assertLessEqual(min(math.dist(p,q) for q in two['points']),20)

    def test_channel_plan_keeps_history_and_certifies_each_channel(self):
        state=state_at(100);before=copy.deepcopy([(j,c.observations,c.status) for j,c in state.channels.items()])
        jobs=[{'kind':'service','channel':j,'position':c.circle()[0]} for j,c in state.channels.items() if c.status=='found']
        route,info=channel_route(state,jobs)
        for j,c in state.channels.items():
            if c.status=='unknown':
                proof=coverage_certificate(negative_circles(c)+[(x['position'],1000.) for x in route if j in x['channels']])
                self.assertTrue(proof.complete and proof.rational_verified)
        self.assertEqual(before,[(j,c.observations,c.status) for j,c in state.channels.items()])


if __name__=='__main__':unittest.main()
