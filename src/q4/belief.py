"""Q4 条件模型：对半径与发射朝向分段积分，只抽样二维位置。

概率仅用于行动比较，绝不删除真实保守状态或宣布频道不存在。
位置、半径、类型先验均为工作假设，不代表官方生成规律。
"""
import hashlib
import json
import math
import random
from dataclasses import dataclass

import common  # 安全配置旧核心模块路径，不调用历史运行器
import geometry as g
from q4 import _arc, _intersection, _subtract
from simulation import LocalEnvironment, Scenario, Source


def history_seed(state, salt=2026091304):
    rows = [(j, c.status, c.observations, c.exclusions)
            for j, c in state.channels.items()]
    return int.from_bytes(hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).digest()[:8], 'big') ^ salt


@dataclass(frozen=True)
class Slice:
    lo: float
    hi: float
    omni: bool
    arcs: tuple
    omni_mass: float
    directional_mass: float

    @property
    def mass(self):
        return self.omni_mass + self.directional_mass


def radial_slices(c, x, omni_prior=.5):
    """给定位置x后，精确分段计算均匀R、均匀朝向的相容质量。

角度与半径边界的零测度集合不用于统计采样；保守状态另行保留。
示向度似然用均匀有界误差近似，兼容两位小数舍入外包。
"""
    if math.hypot(*x) > 1800 or not c.compatible(x):
        return ()
    for q, result in getattr(c, 'clear_history', []):
        d = math.dist(q, x)
        if (result == 'success' and d > 20) or (result == 'no_target_in_range' and d <= 20):
            return ()
    lower, positives, negatives = 1000., [], []
    for q, result, bearing in c.observations:
        d = math.dist(q, x)
        if result == 'no_signal':
            negatives.append((d, q))
            continue
        lower = max(lower, d)
        if result == 'near':
            if d > 5 + 1e-9:
                return ()
        elif result == 'direction':
            if d <= 5:
                return ()
            truth = math.degrees(math.atan2(x[1]-q[1], x[0]-q[0])) % 360
            if abs(g.angle_delta(truth, bearing)) > g.ANGLE_ERROR:
                return ()
        else:
            raise ValueError(result)
        if d > 1e-9:
            positives.append(q)
    if lower >= 1500:
        return ()
    positive_arcs = [(0., 360.)]
    for q in positives:
        angle = math.degrees(math.atan2(q[1]-x[1], q[0]-x[0])) % 360
        positive_arcs = _intersection(positive_arcs, _arc(angle))
    breaks = sorted({lower, 1500.} | {d for d, _ in negatives if lower < d < 1500})
    result = []
    for lo, hi in zip(breaks, breaks[1:]):
        radius = (lo + hi) / 2
        arcs, omni = list(positive_arcs), True
        for d, q in negatives:
            if d <= radius:
                omni = False
                angle = math.degrees(math.atan2(q[1]-x[1], q[0]-x[0])) % 360
                arcs = _subtract(arcs, _arc(angle))
        width = hi - lo
        omass = width / 500 * omni_prior * int(omni)
        dmass = width / 500 * (1-omni_prior) * sum(b-a for a, b in arcs) / 360
        if omass + dmass > 0:
            result.append(Slice(lo, hi, omni, tuple(arcs), omass, dmass))
    return tuple(result)


def reception_mass(x, slices, q):
    """在给定x的相容R/朝向模型中，q可接收的条件概率。"""
    denominator = sum(s.mass for s in slices)
    if denominator <= 0:
        return 0.
    d = math.dist(x, q)
    angle = math.degrees(math.atan2(q[1]-x[1], q[0]-x[0])) % 360
    total = 0.
    for s in slices:
        fraction = max(0., s.hi-max(s.lo, d)) / (s.hi-s.lo)
        length = sum(b-a for a, b in s.arcs)
        hit = sum(b-a for a, b in _intersection(list(s.arcs), _arc(angle))) / length if length > 0 else 0.
        total += fraction * (s.omni_mass + s.directional_mass * hit)
    return min(1., max(0., total / denominator))


def _proposal(state, c, rng):
    if c.status == 'unknown':
        boxes = state.coverage(c.channel).unresolved
        if not boxes:
            raise ValueError('未知频道无未决格；不能用空抽样判空')
        areas = [b.area for b in boxes]
        def draw():
            b = rng.choices(boxes, areas)[0]
            return (rng.uniform(b.x0, b.x1), rng.uniform(b.y0, b.y1))
        return draw, sum(areas)
    poly = c.support()
    for q, result in getattr(c, 'clear_history', []):
        if result == 'success':
            poly = g.intersect_disk_outer(poly, q, 20.)
    triangles = [(poly[0], poly[i], poly[i+1]) for i in range(1, len(poly)-1)]
    areas = [g.area(list(t)) for t in triangles]
    if not areas or sum(areas) <= 1e-12:
        raise ValueError('退化位置支持，概率评估回退保守控制器')
    def draw():
        a, b, z = rng.choices(triangles, areas)[0]
        u, v = math.sqrt(rng.random()), rng.random()
        return tuple((1-u)*a[k]+u*(1-v)*b[k]+u*v*z[k] for k in (0, 1))
    return draw, sum(areas)


def make_pool(state, c, rng, size=96, omni_prior=.5):
    draw, area = _proposal(state, c, rng)
    points, slices, weights = [], [], []
    for _ in range(size):
        x = draw()
        parts = radial_slices(c, x, omni_prior)
        points.append(x)
        slices.append(parts)
        weights.append(sum(s.mass for s in parts))
    if sum(weights) <= 0:
        raise ValueError(f'C{c.channel}有限池耗尽；不是不存在证据')
    return {'points': points, 'slices': slices, 'weights': weights,
            'presence_mass': area / (math.pi*1800**2) * sum(weights)/size,
            'ess': sum(weights)**2 / sum(w*w for w in weights)}


def sample_source(channel, pool, rng):
    i = rng.choices(range(len(pool['points'])), pool['weights'])[0]
    x, parts = pool['points'][i], pool['slices'][i]
    s = rng.choices(parts, [s.mass for s in parts])[0]
    radius = s.lo + (s.hi-s.lo) * (1e-9+(1-2e-9)*rng.random())
    orientation = None
    if rng.random() * s.mass >= s.omni_mass:
        arc = rng.choices(s.arcs, [b-a for a, b in s.arcs])[0]
        orientation = arc[0] + (arc[1]-arc[0]) * (1e-9+(1-2e-9)*rng.random())
    return Source(channel, x, radius, orientation)


def subset_distribution(masses, known):
    n = len(masses)
    suffix = [[0.]*(n+1) for _ in range(n+1)]
    suffix[n][0] = 1.
    for i in range(n-1, -1, -1):
        suffix[i][0] = 1.
        for k in range(1, n-i+1):
            suffix[i][k] = suffix[i+1][k]+masses[i]*suffix[i+1][k-1]
    ks = list(range(max(0, 10-known), min(n, 16-known)+1))
    weights = [suffix[0][k]/math.comb(20, known+k) for k in ks]
    if sum(weights) <= 0:
        raise ValueError('源数条件质量耗尽')
    return suffix, ks, weights


def sample_worlds(state, count=4, pool_size=96, omni_prior=.5, salt=2026091304):
    rng = random.Random(history_seed(state, salt))
    found = [j for j, c in state.channels.items() if c.status == 'found']
    unknown = [j for j, c in state.channels.items() if c.status == 'unknown']
    cleared = [j for j, c in state.channels.items() if c.status == 'cleared']
    pools = {j: make_pool(state, state.channels[j], rng, pool_size, omni_prior)
             for j in found + unknown + cleared}
    masses = [pools[j]['presence_mass'] for j in unknown]
    suffix, ks, weights = subset_distribution(masses, len(state.ever_seen))
    worlds = []
    # 对完整源集合至少各有一类作拒绝条件；已清除源类型仍由历史抽样，
    # 但不放入后续环境。条件模型从不使用实际隐藏类型。
    for m in range(count):
        for attempt in range(1000):
            k = rng.choices(ks, weights)[0]
            active = list(found)
            for i, j in enumerate(unknown):
                probability = masses[i]*suffix[i+1][k-1]/suffix[i][k] if k else 0.
                if rng.random() < probability:
                    active.append(j)
                    k -= 1
            if k:
                raise AssertionError('频道子集抽样未完成')
            sources = [sample_source(j, pools[j], rng) for j in active]
            removed = [sample_source(j, pools[j], rng) for j in cleared]
            kinds = {s.orientation is None for s in sources + removed}
            if len(kinds) == 2:
                worlds.append(Scenario(f'q4_conditional_{m}', rng.randrange(2**31),
                                       'conditional', 'hashed', tuple(sources)))
                break
        else:
            raise ValueError('混合类型条件抽样耗尽，回退')
    return worlds, {'samples': count, 'pool_size': pool_size, 'omni_prior': omni_prior,
                    'unknown_mass': dict(zip(unknown, masses)),
                    'pool_ess': {j: p['ess'] for j, p in pools.items()},
                    'assumption': 'uniform_position_radius_orientation_bounded_error_mixed_types'}


class ConditionalEnvironment(LocalEnvironment):
    """历史同地点反馈固定；未来新地点误差由固定空间哈希场给出。"""
    def __init__(self, world, state):
        super().__init__(world)
        self.position, self.channel = state.position, state.measuring_channel
        self.virtual_time_s = state.virtual_time_s
        self.previously_cleared = {j for j, c in state.channels.items() if c.status == 'cleared'}
        self.history = {(tuple(q), j): (r, b) for j, c in state.channels.items()
                        for q, r, b in c.observations}

    def act(self, action):
        reply = super().act(action)
        key = (tuple(action['position']), action['channel'])
        if (action['kind'] == 'measure' and key in self.history
                and action['channel'] not in self.cleared
                and action['channel'] not in self.previously_cleared):
            r, b = self.history[key]
            reply['measure_result'] = r
            reply.pop('svd_deg', None)
            if b is not None:
                reply['svd_deg'] = b
        reply.pop('costs', None)
        return reply
