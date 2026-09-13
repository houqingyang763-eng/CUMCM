"""只在 F3 已有多候选测点比较中加入越界圆面积惩罚。"""
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'refinement'))
from refined import RefinedPolicy
from posterior import a


def outside_fraction(q, radius=1000., domain_radius=1800.):
    """接收圆落在任务圆外的面积 / 接收圆面积；使用两圆相交解析式。"""
    if radius <= 0 or domain_radius <= 0:
        raise ValueError('radii must be positive')
    d = math.hypot(*q)
    r, R = radius, domain_radius
    if d + r <= R:
        return 0.
    if d + R <= r:
        return 1. - (R/r)**2
    if d >= r + R:
        return 1.
    clamp = lambda x: max(-1., min(1., x))
    lens = (r*r*math.acos(clamp((d*d+r*r-R*R)/(2*d*r)))
            + R*R*math.acos(clamp((d*d+R*R-r*r)/(2*d*R)))
            - .5*math.sqrt(max(0., (-d+r+R)*(d+r-R)*(d-r+R)*(d+r+R))))
    return max(0., min(1., 1.-lens/(math.pi*r*r)))


class BoundaryPolicy(RefinedPolicy):
    def __init__(self, selected=None, strength_s=180.):
        super().__init__(selected, level=3, samples=4)
        if strength_s < 0:
            raise ValueError('negative boundary strength')
        self.strength_s = strength_s

    def select_candidate(self, state, records, original):
        for record in records:
            if record['kind'] == 'scan':
                q = record['q']
            elif record['kind'] == 'original' and original['kind'] == 'measure':
                q = original['position']
            else:
                q = None  # 清除实际目标没有覆盖面积损失惩罚。
            fraction = outside_fraction(q) if q is not None else 0.
            record['outside_fraction'] = fraction
            record['boundary_penalty_s'] = self.strength_s * fraction
            record['rank_cost_s'] = record['mean_s'] + record['boundary_penalty_s']
        unpenalized = min(records, key=lambda r: r['mean_s'])
        chosen = min(records, key=lambda r: r['rank_cost_s'])
        return chosen, {
            'boundary_strength_s': self.strength_s,
            'unpenalized_choice': unpenalized['id'],
            'boundary_changed_choice': chosen['id'] != unpenalized['id'],
            'estimated_time_tradeoff_s': chosen['mean_s']-unpenalized['mean_s'],
        }

    def metadata(self):
        return dict(super().metadata(), boundary_strength_s=self.strength_s,
                    boundary_scope='F3 existing multi-candidate decision roots only; sensing stops, not clear actions',
                    boundary_radius_m=1000., boundary_domain_radius_m=1800.)
