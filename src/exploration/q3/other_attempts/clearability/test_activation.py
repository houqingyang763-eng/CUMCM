"""函数消融：关闭筛选必须复现原F3，预测器只变函数。"""
import json
import unittest
from pathlib import Path
from activation_only import ActivationOnly,Predictor,linear,module,a

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent/'refinement/runs/demo_f3_20260912'
CASE=json.loads((ROOT/'cases.json').read_text(encoding='utf-8'))[0]
DIR=ROOT/CASE['name']
ROWS=[json.loads(x) for x in (DIR/'f3/actions.jsonl').read_text(encoding='utf-8').splitlines()]


class Checks(unittest.TestCase):
    def test_predictors_share_samples_and_candidates(self):
        state=a.CoverageInformationState()
        for row in ROWS[:82]:state.update(row,row['response'])
        c=state.channels[9];l=Predictor(linear);s=Predictor(module.utility)
        self.assertEqual(l.cloud(state,c),s.cloud(state,c))
        self.assertEqual(l.candidate_points(state,c),s.candidate_points(state,c))
        self.assertEqual(l.predict(state,c,c.observations[-1][0])['gain'],0)
        self.assertEqual(s.predict(state,c,c.observations[-1][0])['gain'],0)

    def test_gate_off_reproduces_all_original_actions(self):
        selected=json.loads((DIR/'selection.json').read_text(encoding='utf-8'))['selected']
        policy=ActivationOnly(selected,'off');state=a.CoverageInformationState()
        for row in ROWS:
            action=policy.choose(state)
            for key in ('kind','channel','reason'):
                self.assertEqual(action[key],row[key],row['step'])
            self.assertEqual(list(action['position']),row['position'],row['step'])
            state.update(action,row['response'])
        self.assertTrue(state.complete)
        a.base.dump(HERE/'runs/activation_only/equivalence.json',{'off_matches_original_actions':len(ROWS),'public_complete':True})


if __name__=='__main__':unittest.main()
