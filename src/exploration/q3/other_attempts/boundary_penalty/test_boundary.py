"""解析面积独立切片复算、零惩罚完整轨迹一致、候选比较量纲。"""
import json
import math
from pathlib import Path
import unittest
from boundary_policy import BoundaryPolicy, outside_fraction, a

HERE = Path(__file__).resolve().parent


class Checks(unittest.TestCase):
    def test_geometry_against_independent_strip_integration(self):
        for d in (0., 400., 800., 801., 1000., 1400., 1800., 2200., 2800., 3000.):
            n = 40000
            width = 2000/n
            overlap = 0.
            for k in range(n):
                x = -1000 + (k+.5)*width
                small_y = math.sqrt(max(0., 1000**2-x*x))
                big_y = math.sqrt(max(0., 1800**2-(x+d)**2))
                overlap += 2*min(small_y, big_y)*width
            expected = 1.-overlap/(math.pi*1000**2)
            self.assertAlmostEqual(outside_fraction((d, 0)), expected, delta=2e-6)
        values = [outside_fraction((d, 0)) for d in range(0, 3001)]
        self.assertEqual(values[800], 0.)
        self.assertTrue(all(x <= y for x, y in zip(values, values[1:])))
        self.assertAlmostEqual(outside_fraction((840,1120)), outside_fraction((1400,0)))

    def test_zero_strength_reproduces_original_f3(self):
        root = HERE.parent/'refinement/runs/demo_f3_20260912'
        case = json.loads((root/'cases.json').read_text(encoding='utf-8'))[0]
        directory = root/case['name']
        selected = json.loads((directory/'selection.json').read_text(encoding='utf-8'))['selected']
        rows = [json.loads(x) for x in (directory/'f3/actions.jsonl').read_text(encoding='utf-8').splitlines()]
        policy = BoundaryPolicy(selected, 0.)
        state = a.CoverageInformationState()
        for row in rows:
            action = policy.choose(state)
            for key in ('kind','channel','reason'):
                self.assertEqual(action[key], row[key], row['step'])
            self.assertEqual(list(action['position']), row['position'], row['step'])
            state.update(action, row['response'])
        self.assertTrue(state.complete)
        a.base.dump(HERE/'runs/zero_equivalence.json', {'matched_actions':len(rows), 'public_complete':True})


if __name__ == '__main__':
    unittest.main()
