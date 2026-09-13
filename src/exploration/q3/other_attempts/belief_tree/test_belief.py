import copy
import math
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import random

from particle_belief import a, angle_factor, draw, likelihood, channel_pool
from planner import candidates, fallback_policy, BeliefTreePolicy, Node, Edge


class BeliefTests(unittest.TestCase):
    def test_rounding_likelihood(self):
        self.assertAlmostEqual(angle_factor(0.,0.),1.)
        self.assertAlmostEqual(angle_factor(0.,1.),.5)
        self.assertAlmostEqual(angle_factor(359.5,.5),.5)
        self.assertAlmostEqual(angle_factor(0.,1.01),0.)

    def test_initial_presence_count(self):
        state = a.CoverageInformationState()
        worlds = draw(state,40,pool_size=64)
        self.assertTrue(all(10<=len(w.sources)<=16 for w in worlds))
        self.assertTrue(all(math.hypot(*s.position)<=1800 and 1000<=s.radius<=1500 for w in worlds for s in w.sources))
        self.assertFalse(state.complete)

    def test_repeat_does_not_add_probability(self):
        state = a.first_state(a.base.generate(330000,'uniform','hashed'))
        once = draw(state,4,salt=11,pool_size=256)
        j = next(j for j,c in state.channels.items() if c.status=='found')
        c = state.channels[j]
        q,result,bearing = c.observations[0]
        reply = dict(measure_result=result,svd_deg=bearing)
        self.assertEqual(likelihood(once[0],state,dict(kind='measure',position=q,channel=j),reply),1.)
        pool_once = channel_pool(state,j,256)
        duplicate = copy.deepcopy(state)
        duplicate.channels[j].observations.append((q,result,bearing))
        self.assertEqual(channel_pool(duplicate,j,256),pool_once)

    def test_all_target_candidates(self):
        state = a.CoverageInformationState()
        state.channels[1].status = 'found'
        state.channels[1].polygon = [(-30.,-1.),(30.,-1.),(30.,1.),(-30.,1.)]
        state.ever_seen.add(1)
        actions,_ = candidates(state,fallback_policy(state))
        self.assertTrue(any(x['kind']=='clear' and x['channel']==1 for x in actions))
        self.assertTrue(any(x['kind']=='measure' and x['position']==state.position for x in actions))

    def test_expansion_conditions_on_feedback(self):
        state = a.first_state(a.base.generate(330000,'uniform','hashed'))
        p = BeliefTreePolicy(3,4,8)
        import random
        p.rng = random.Random(13)
        p.counters = dict(min_ess=8.,nodes=0,posterior_refreshes=0)
        node = Node(state,fallback_policy(state),draw(state,8))
        node.actions,node.incumbent_policy = candidates(state,node.policy)
        action = next(x for x in node.actions if x['kind']=='measure' and x['position']!=state.position)
        _,child = p.expand(node,Edge(action))
        self.assertEqual(child.state.actions,state.actions+1)
        self.assertEqual(len(child.worlds),8)
        self.assertGreater(len({tuple(s.position for s in w.sources) for w in child.worlds}),1)
        for world in child.worlds:
            for source in world.sources:
                self.assertTrue(child.state.channels[source.channel].compatible(source.position))

    def test_depth_can_change_decision_after_feedback(self):
        # 独立小问题：直接完成8秒；先看2秒，获知左右后选对动作0秒、选错20秒。
        # 固定尾部不利用新信息，付10秒；两层搜索应学会利用反馈。
        class Toy(BeliefTreePolicy):
            def leaf(self,node):
                return 0. if node.state.complete else 10.

            def expand(self,node,edge):
                label=edge.action['label']
                if node.state.stage==0 and label=='observe':
                    observed=self.rng.randrange(2)
                    child=Node(SimpleNamespace(stage=1,complete=False,observed=observed),None,[])
                    cost=2.
                    for index,(past_cost,past_child,_) in enumerate(edge.children):
                        if past_child.state.observed==observed:
                            edge.multiplicities[index]+=1
                            return past_cost,past_child
                else:
                    cost=8. if node.state.stage==0 else (0. if label==str(node.state.observed) else 20.)
                    child=Node(SimpleNamespace(stage=2,complete=True),None,[])
                edge.children.append((cost,child,{}))
                edge.multiplicities.append(1)
                return cost,child

        def options(state,policy):
            return ([dict(label=x) for x in (['direct','observe'] if state.stage==0 else ['0','1'])],None)

        choices=[]
        with patch('planner.candidates',options):
            for depth in (1,2):
                p=Toy(depth,particles=1)
                p.exploration=10. # 小问题费用为个位/十位秒，探索参数按费用尺度设置。
                p.rng=random.Random(15)
                p.counters={'max_depth':0}
                root=Node(SimpleNamespace(stage=0,complete=False),None,[])
                for _ in range(12000):
                    p.simulate(root,depth)
                choices.append(min(root.edges,key=lambda e:e.mean).action['label'])
        self.assertEqual(choices,['direct','observe'])

    def test_identical_negative_observations_share_node(self):
        state=a.CoverageInformationState()
        p=BeliefTreePolicy(3,4,8)
        p.rng=random.Random(13)
        p.counters=dict(min_ess=8.,nodes=0,posterior_refreshes=0)
        node=Node(state,fallback_policy(state),draw(state,8))
        node.actions,node.incumbent_policy=candidates(state,node.policy)
        edge=Edge(dict(kind='measure',position=(4000.,0.),channel=1,reason='test'))
        _,first=p.expand(node,edge)
        _,second=p.expand(node,edge)
        self.assertIs(first,second)
        self.assertEqual(edge.multiplicities,[2])
        self.assertEqual(len(edge.children),1)

    def test_sampled_empty_world_does_not_skip_public_search(self):
        state=a.CoverageInformationState()
        for j in range(1,11):
            state.channels[j].status='cleared'
            state.ever_seen.add(j)
        self.assertFalse(state.complete)
        world=a.Scenario('empty_remaining',1,'toy','hashed',())
        node=Node(state,fallback_policy(state),[world])
        p=BeliefTreePolicy(1,1,1)
        p.rng=random.Random(1)
        p.counters={'tail_calls':0}
        self.assertGreater(p.leaf(node),100.)
        self.assertFalse(state.complete)


if __name__ == '__main__':
    unittest.main()
