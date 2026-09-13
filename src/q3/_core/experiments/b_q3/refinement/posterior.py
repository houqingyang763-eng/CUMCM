"""只读取公开历史的条件场景近似；采样失败不改变真实信息状态。"""
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'adaptive_second'))
import adaptive as a
import geometry as g


def radius_interval(c, x):
    if math.hypot(*x) > 1800 or not c.compatible(x):
        return None
    lower, upper = 1000., 1500.
    for q, result, bearing in c.observations:
        d = math.dist(q, x)
        if result == 'no_signal':
            upper = min(upper, d)
        else:
            lower = max(lower, d)
            if result == 'near':
                if d > 5:
                    return None
            elif d <= 5:
                return None
            else:
                truth = math.degrees(math.atan2(x[1]-q[1], x[0]-q[0])) % 360
                if abs(g.angle_delta(truth, bearing)) > g.ANGLE_ERROR:
                    return None
    return (lower, upper) if upper > lower else None


def pool(state, c, rng, size=256):
    """均匀空间提议，按可行接收半径长度加权。未知源用未覆盖叶格提议。"""
    if c.status == 'unknown':
        boxes = state.coverage(c.channel).unresolved
        if not boxes:
            raise ValueError('unknown has no unresolved proposal boxes')
        areas = [b.area for b in boxes]
        proposal_area = sum(areas)
        def point():
            b = rng.choices(boxes, areas)[0]
            return (rng.uniform(b.x0, b.x1), rng.uniform(b.y0, b.y1))
    else:
        poly = c.support()
        triangles = [(poly[0], poly[i], poly[i+1]) for i in range(1, len(poly)-1)]
        areas = [g.area(list(t)) for t in triangles]
        if not areas or sum(areas) <= 1e-14:
            raise ValueError('degenerate posterior support; fallback required')
        proposal_area = sum(areas)
        def point():
            x, y, z = rng.choices(triangles, areas)[0]
            u, v = math.sqrt(rng.random()), rng.random()
            return tuple((1-u)*x[k]+u*(1-v)*y[k]+u*v*z[k] for k in range(2))
    points, intervals, weights = [], [], []
    for _ in range(size):
        x = point()
        bounds = radius_interval(c, x)
        points.append(x)
        intervals.append(bounds)
        weights.append((bounds[1]-bounds[0])/500 if bounds else 0.)
    total = sum(weights)
    if total <= 0:
        # 零有限样本质量不是不存在的证明，整个动作选择退回原控制器。
        raise ValueError(f'C{c.channel}: finite posterior pool exhausted')
    mass = proposal_area/(math.pi*1800**2)*total/size
    return points, intervals, weights, mass


def subset_distribution(masses, known):
    """后验 P(U=A|H) ∝ product(z_j)/C(20,known+|A|)，N先验10..16。"""
    n = len(masses)
    suffix = [[0.]*(n+1) for _ in range(n+1)]
    suffix[n][0] = 1.
    for i in range(n-1, -1, -1):
        suffix[i][0] = 1.
        for k in range(1, n-i+1):
            suffix[i][k] = suffix[i+1][k]+masses[i]*suffix[i+1][k-1]
    ks = list(range(max(0, 10-known), min(n, 16-known)+1))
    weights = [suffix[0][k]/math.comb(20, known+k) for k in ks]
    if not weights or sum(weights) <= 0:
        raise ValueError('source count posterior exhausted; not absence')
    total = sum(weights)
    return suffix, ks, [w/total for w in weights]


def sample_worlds(state, count=4, pool_size=256, salt=310912):
    rng = random.Random(a.history_seed(state, salt))
    found = [j for j,c in state.channels.items() if c.status == 'found']
    unknown = [j for j,c in state.channels.items() if c.status == 'unknown']
    pools = {j: pool(state, state.channels[j], rng, pool_size) for j in found+unknown}
    masses = [pools[j][3] for j in unknown]
    suffix, ks, weights = subset_distribution(masses, len(state.ever_seen))
    worlds = []
    for m in range(count):
        k = rng.choices(ks, weights)[0]
        active = list(found)
        for i,j in enumerate(unknown):
            probability = masses[i]*suffix[i+1][k-1]/suffix[i][k] if k else 0.
            if rng.random() < probability:
                active.append(j)
                k -= 1
        if k:
            raise AssertionError('conditional subset sampling incomplete')
        sources = []
        for j in active:
            points, intervals, w, _ = pools[j]
            i = rng.choices(range(len(points)), w)[0]
            lo, hi = intervals[i]
            # 上界通常来自一次无信号，取开区间，避免恰好到接收边界。
            r = lo+(hi-lo)*(1e-10+(1-2e-10)*rng.random())
            sources.append(a.Source(j, points[i], r))
        worlds.append(a.Scenario(f'conditional_{m}', rng.randrange(2**31), 'posterior', 'hashed', tuple(sources)))
    return worlds, {'samples':count, 'pool_size':pool_size, 'unknown_channels':unknown,
                    'unknown_presence_mass':masses, 'remaining_unknown_count_values':ks,
                    'remaining_unknown_count_probabilities':weights,
                    'known_ever':len(state.ever_seen), 'assumption':'uniform_space_radius_bounded_angle'}
