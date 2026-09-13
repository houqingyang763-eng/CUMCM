import itertools
import math
import unittest
from oracle import SCALE, distance_floor, shortest_open_path, weights


class OracleTests(unittest.TestCase):
    def test_exact_integer_distance(self):
        self.assertEqual(distance_floor((0,0),(3,4)),5*SCALE)
        d = distance_floor((0,0),(1,1))
        self.assertLessEqual(d*d,2*SCALE*SCALE)
        self.assertGreater((d+1)*(d+1),2*SCALE*SCALE)

    def test_dp_against_exhaustive_open_paths(self):
        points=[(100,30),(-200,110),(70,-250),(9,13),(310,50),(-87,-40)]
        for disk in (False,True):
            first, edges=weights(points,disk)
            actual, order=shortest_open_path(first,edges)
            best=min(first[p[0]]+sum(edges[a][b] for a,b in zip(p,p[1:]))
                     for p in itertools.permutations(range(len(points))))
            self.assertEqual(actual,best)
            self.assertEqual(sorted(order),list(range(len(points))))
            self.assertEqual(actual,first[order[0]]+sum(edges[a][b] for a,b in zip(order,order[1:])))

    def test_one_source_analytic_clear_disk(self):
        value, order=shortest_open_path(*weights([(100,0)],True))
        self.assertEqual(value/SCALE/5+5,21)
        self.assertEqual(order,[0])

    def test_overlapping_disks_at_start(self):
        value,_=shortest_open_path(*weights([(10,0),(-10,0),(0,19)],True))
        self.assertEqual(value,0)

    def test_disk_bound_below_sample_feasible_routes(self):
        points=[(100,0),(120,50),(-100,120),(30,-90)]
        lower,_=shortest_open_path(*weights(points,True))
        # 独立构造圆内清除点，枚举所有访问次序。
        clear=[(x+19*math.cos(i),y+19*math.sin(i)) for i,(x,y) in enumerate(points)]
        for p in itertools.permutations(range(4)):
            length=math.hypot(*clear[p[0]])+sum(math.dist(clear[a],clear[b]) for a,b in zip(p,p[1:]))
            self.assertLessEqual(lower/SCALE,length)


if __name__=='__main__':
    unittest.main()
