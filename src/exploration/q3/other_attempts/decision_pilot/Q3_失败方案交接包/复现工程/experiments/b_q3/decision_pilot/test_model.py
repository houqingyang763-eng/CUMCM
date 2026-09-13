"""针对约束错误、历史不一致、真值旁路的关键测试。"""
import copy
import unittest
from model import (g, InformationState, radius_interval, worlds_from_history,
                   HistoryEnvironment, candidates, evaluate)
from run import scan_snapshot
from simulation import generate


class ModelTests(unittest.TestCase):
    def test_shared_radius_and_physical_domain(self):
        c = InformationState().channels[1]
        c.observations = [((0.,0.),'direction',0.), ((100.,0.),'no_signal',None)]
        # 每条单独的粗约束可能允许，却没有统一R：1200<=R<1100。
        self.assertIsNone(radius_interval(c,(1200.,0.)))
        c.observations=[]
        self.assertIsNone(radius_interval(c,(1800.1,0.)))
        c.observations=[((0.,0.),'direction',0.)]
        self.assertIsNone(radius_interval(c,(4.,0.)))
        c.observations=[((0.,0.),'near',None)]
        self.assertIsNone(radius_interval(c,(5.1,0.)))

    def test_history_world_and_revisits(self):
        state, env, _ = scan_snapshot(generate(160000,'uniform','hashed'))
        worlds = worlds_from_history(state)
        self.assertEqual(worlds, worlds_from_history(copy.deepcopy(state)))
        self.assertEqual(candidates(state)[0]['actions'], [])
        for w in worlds:
            future = HistoryEnvironment(w,state)
            for source in w.sources:
                c = state.channels[source.channel]
                bounds = radius_interval(c,source.position)
                self.assertIsNotNone(bounds)
                self.assertLessEqual(bounds[0],source.radius)
                self.assertGreaterEqual(bounds[1],source.radius)
                for q,result,angle in c.observations:
                    r = future.act(dict(kind='measure',position=q,channel=c.channel))
                    self.assertEqual(r['measure_result'],result)
                    self.assertEqual(r.get('svd_deg'),angle)


if __name__ == '__main__':
    unittest.main()
