import json
import unittest
from unittest.mock import patch
import adaptive as a
from online import OnlineAdaptivePolicy


class OnlineChecks(unittest.TestCase):
    def test_streaming_matches_frozen_selection(self):
        folder=a.HERE/'runs/pilot/uniform_hashed_270100'
        selection=json.loads((folder/'selection.json').read_text())
        case=a.base.generate(270100,'uniform','hashed')
        expected=a.first_state(case)
        called=[]
        def select(state,*args):
            self.assertEqual(a.history_seed(state),a.history_seed(expected))
            self.assertEqual(state.position,expected.position)
            called.append(state.actions)
            return selection
        policy=OnlineAdaptivePolicy(samples=8)
        state=a.CoverageInformationState()
        env=a.LocalEnvironment(case)
        trace=[]
        with patch.object(a,'select',select):
            while not state.complete:
                action=policy.choose(state)
                trace.append((action['kind'],tuple(action['position']),action['channel']))
                state.update(action,env.act(action))
        saved=[json.loads(line) for line in (folder/'joint/actions.jsonl').read_text().splitlines()]
        self.assertEqual(trace,[(r['kind'],tuple(r['position']),r['channel']) for r in saved])
        self.assertEqual(called,[20])


if __name__=='__main__':
    unittest.main()
