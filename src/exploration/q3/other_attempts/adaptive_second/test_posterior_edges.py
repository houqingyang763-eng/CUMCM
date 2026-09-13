import unittest
import adaptive as a


class PosteriorEdges(unittest.TestCase):
    def test_sixteen_positives_and_unmeasured_absent_channels(self):
        q=a.CONFIG['initial_points'][0]
        case=a.Scenario('sixteen',998,'test','zero',tuple(a.Source(j,(q[0]+100,q[1]),1000) for j in range(1,17)))
        state=a.first_state(case)
        self.assertEqual(len(state.ever_seen),16)
        worlds,_=a.sample_worlds(state,4)
        for w in worlds:
            self.assertEqual(len(w.sources),16)
            a.audit_state(state,a.ConditionalEnvironment(w,state))

    def test_near_reading(self):
        q=a.CONFIG['initial_points'][0]
        sources=[a.Source(1,(q[0]+1,q[1]),1000)]
        sources.extend(a.Source(j,(1750.,0.),1000) for j in range(2,11))
        case=a.Scenario('near',999,'test','zero',tuple(sources))
        state=a.first_state(case)
        self.assertEqual(state.channels[1].observations[0][1],'near')
        for w in a.sample_worlds(state,4)[0]:
            env=a.ConditionalEnvironment(w,state)
            a.audit_state(state,env)
            self.assertLessEqual(a.math.dist(env.sources[1].position,q),5)

    def test_no_signal_current_candidate_is_no_move(self):
        case=a.Scenario('empty_first',1000,'test','zero',tuple(a.Source(j,(1750.,0.),1000) for j in range(1,11)))
        state=a.first_state(case)
        self.assertFalse(state.ever_seen)
        candidate=next(c for c in a.candidates(state) if c['id']=='p1_all')
        self.assertEqual(candidate['channels'],[])
        policy=a.continuation(state,candidate)
        self.assertEqual(policy.station_channels,[])
        self.assertIsNone(policy.initial_finish_s)


if __name__=='__main__':
    unittest.main()
