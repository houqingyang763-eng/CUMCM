import copy
import unittest

from macro_planner import (a, MacroTreePolicy, macro_candidates, station_channels,
                           execute_station, first_atomic)
from planner import fallback_policy, action_key, candidates


class MacroTests(unittest.TestCase):
    def test_atomic_candidates_retained(self):
        state=a.CoverageInformationState()
        p=fallback_policy(state)
        atomic,_=candidates(state,p)
        extended,_=macro_candidates(state,p)
        self.assertTrue({action_key(x) for x in atomic}.issubset({action_key(x) for x in extended}))
        self.assertTrue(any(x['kind']=='scan_station' for x in extended))

    def test_macro_and_real_queue_have_same_feedback_cost(self):
        state=a.CoverageInformationState()
        case=a.base.generate(330000,'uniform','hashed')
        q=(-150.,0.)
        action=dict(kind='scan_station',position=q,channel=1,channels=station_channels(state,q))
        predicted=copy.deepcopy(state)
        predicted_env=a.LocalEnvironment(case)
        replies=execute_station(predicted,predicted_env,action)
        real_env=a.LocalEnvironment(case)
        p=MacroTreePolicy(3,1,8)
        p.station_position=q
        p.station_queue=list(action['channels'])
        actual=[]
        while p.station_queue:
            atom=p.queued_action(state)
            if atom is None:
                break
            reply=real_env.act(atom)
            state.update(atom,reply)
            actual.append((atom,reply))
        self.assertEqual(actual,replies)
        self.assertEqual(state.virtual_time_s,30+20*5+19)
        self.assertEqual(state.virtual_time_s,predicted.virtual_time_s)
        self.assertEqual(state.ever_seen,predicted.ever_seen)
        self.assertEqual(actual[0][0],first_atomic(action))

    def test_skip_proven_absent_and_repeat_channels(self):
        state=a.CoverageInformationState()
        state.channels[1].status='absent'
        state.channels[2].measured.add((0.,0.))
        self.assertNotIn(1,station_channels(state,(0.,0.)))
        self.assertNotIn(2,station_channels(state,(0.,0.)))


if __name__=='__main__':unittest.main()
