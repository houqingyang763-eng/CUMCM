import copy
import math
import unittest
import adaptive as a

class Checks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case=a.base.generate(270100,'uniform','hashed')
        cls.state=a.first_state(cls.case)

    def test_count_weights(self):
        ns,w=a.count_weights(0,1)
        self.assertTrue(all(abs(v-1/7)<1e-12 for v in w))
        ns,w=a.count_weights(16,.5)
        self.assertEqual(ns,[16])
        self.assertEqual(w,[1.])

    def test_worlds_compatible(self):
        worlds,_=a.sample_worlds(self.state,20)
        for world in worlds:
            env=a.ConditionalEnvironment(world,self.state)
            a.audit_state(self.state,env)
            for s in world.sources:
                c=self.state.channels[s.channel]
                self.assertEqual(math.dist(s.position,self.state.position)<=s.radius,c.status=='found')
            self.assertTrue(10<=len(world.sources)<=16)

    def test_fixed_noise(self):
        world=a.sample_worlds(self.state,1)[0][0]
        env=a.ConditionalEnvironment(world,self.state)
        for j,c in self.state.channels.items():
            action={'kind':'measure','position':self.state.position,'channel':j}
            x,y=env.act(action),env.act(action)
            self.assertEqual(x['measure_result'],y['measure_result'])
            self.assertEqual(x.get('svd_deg'),y.get('svd_deg'))
            self.assertEqual(x['measure_result'],c.observations[0][1])

    def test_rollout_true_case_matches_fixed(self):
        candidate=a.candidates(self.state)[0]
        duration=a.rollout(self.state,self.case,candidate,True)
        env=a.LocalEnvironment(self.case)
        state=a.CoverageInformationState()
        policy=a.PatrolPolicy(a.CONFIG)
        for _ in range(3000):
            if state.complete:
                break
            action=policy.choose(state)
            state.update(action,env.act(action))
        self.assertTrue(state.complete)
        self.assertAlmostEqual(duration+self.state.virtual_time_s,env.virtual_time_s,places=6)

    def test_rollout_no_mutation_and_completion(self):
        before=copy.deepcopy(self.state.__dict__)
        world=a.sample_worlds(self.state,1)[0][0]
        for candidate in a.candidates(self.state)[::3]:
            self.assertGreater(a.rollout(self.state,world,candidate,True),0)
        self.assertEqual(self.state.actions,before['actions'])
        self.assertEqual(self.state.position,before['position'])

    def test_fixed_adapter_matches_original(self):
        candidate=a.candidates(self.state)[0]
        traces=[]
        for policy in (a.PatrolPolicy(a.CONFIG),a.AdaptivePolicy(candidate)):
            env=a.LocalEnvironment(self.case)
            state=a.CoverageInformationState()
            trace=[]
            while not state.complete:
                action=policy.choose(state)
                trace.append((action['kind'],tuple(action['position']),action['channel']))
                state.update(action,env.act(action))
            traces.append(trace)
        self.assertEqual(traces[0],traces[1])

    def test_seed_uses_observations_only(self):
        modified=copy.deepcopy(self.state)
        modified.virtual_time_s+=10000
        self.assertEqual(a.history_seed(self.state),a.history_seed(modified))
        x=a.sample_worlds(self.state,2)[0]
        y=a.sample_worlds(modified,2)[0]
        self.assertEqual(x,y)

    def test_count_update_matches_binomial_detection(self):
        for k in (0,4,8,12):
            ns,w=a.count_weights(k,.51)
            independent=[math.comb(n,k)*.49**k*.51**(n-k) for n in ns]
            total=sum(independent)
            for x,y in zip(w,independent):
                self.assertAlmostEqual(x,y/total,places=12)

if __name__=='__main__':
    unittest.main()
