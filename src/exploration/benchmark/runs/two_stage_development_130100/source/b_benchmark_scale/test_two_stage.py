import itertools
import math
import unittest

from two_stage import fixed_route, route_order, TwoStagePolicy, TwoStageConfig, g
from simulation import LocalEnvironment, Scenario, Source
from state import InformationState, audit_state


class Tests(unittest.TestCase):
    def test_route_matches_exhaustive_nonorigin(self):
        start=(53.,-21.)
        points=[(0.,0.),(4.,80.),(4.,80.),(-31.,2.),(200.,-1.),(53.,-21.)]
        channels=list(range(len(points)))
        order,lower=route_order(start,channels,points)
        def length(order):
            chain=[start]+[points[i] for i in order]
            return sum(math.dist(a,b) for a,b in zip(chain,chain[1:]))
        true=min(length(p) for p in itertools.permutations(channels))
        self.assertLessEqual(lower,true+1e-8)
        self.assertLessEqual(length(order)-true,len(points)*1e-6+1e-8)
        self.assertEqual(route_order(start,[],[]),([],0.))

    def test_fixed_routes_keep_discovery_guarantee(self):
        for n in (7,13,19):
            route=fixed_route(n)
            self.assertEqual(len(route),n)
            self.assertEqual(route[0],(0.,0.))
            for q in g.ANCHORS:self.assertIn(q,route)
        self.assertAlmostEqual(sum(math.dist(a,b) for a,b in zip(fixed_route(7),fixed_route(7)[1:])),7200.)

    def test_found_channel_keeps_getting_directions(self):
        sources=tuple(Source(j,(400.+j,300.+j),1500.) for j in range(1,11))
        case=Scenario('multi',1,'test','zero',sources)
        state=InformationState();env=LocalEnvironment(case)
        policy=TwoStagePolicy(TwoStageConfig(scan_radius_m=0.))
        scans=[]
        while True:
            action=policy.choose(state)
            if action['phase']=='service':break
            scans.append(action)
            state.update(action,env.act(action));audit_state(state,env)
        self.assertEqual(sum(a['channel']==1 for a in scans),7)
        self.assertGreater(sum(o[1]=='direction' for o in state.channels[1].observations),1)
        self.assertTrue(all(c.status!='unknown' for c in state.channels.values()))
        self.assertEqual(policy.routes[0]['start'],state.position)


if __name__=='__main__':unittest.main()
