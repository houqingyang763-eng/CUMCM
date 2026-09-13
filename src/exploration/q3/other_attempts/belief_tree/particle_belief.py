"""公共历史条件粒子；范围固定、重复观测不独立、舍入角度似然。"""
import math
import random
import sys
import hashlib
from collections import OrderedDict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'refinement'))
import posterior as old
from posterior import a, g

POOL_CACHE = OrderedDict()


def channel_pool(state,j,pool_size):
    c = state.channels[j]
    observations = tuple(sorted(set((tuple(q),r,b) for q,r,b in c.observations)))
    key = (j,c.status,observations,tuple(sorted(set(c.exclusions))),pool_size)
    if key in POOL_CACHE:
        POOL_CACHE.move_to_end(key)
        return POOL_CACHE[key]
    seed = int.from_bytes(hashlib.sha256(repr(key).encode()).digest()[:8],'big')
    points,intervals,weights,mass = old.pool(state,c,random.Random(seed),pool_size)
    if c.status == 'found':
        for i,x in enumerate(points):
            if not weights[i]:
                continue
            for q,result,bearing in observations:
                if result == 'direction':
                    truth = math.degrees(math.atan2(x[1]-q[1],x[0]-q[0])) % 360
                    weights[i] *= angle_factor(truth,bearing)
        if sum(weights) <= 0:
            raise ValueError('rounded bearing posterior exhausted')
    value = points,intervals,weights,mass
    POOL_CACHE[key] = value
    if len(POOL_CACHE) > 1024:
        POOL_CACHE.popitem(last=False)
    return value


def angle_factor(truth, reading):
    # 与Uniform[-1,1]相交的0.01度舍入区间，除以区间宽。
    d = g.angle_delta(reading, truth)
    return max(0., min(1., d + .005) - max(-1., d - .005)) / .01


def draw(state, count, salt=0, pool_size=256):
    rng = random.Random(a.history_seed(state, 991127 ^ salt))
    found = [j for j,c in state.channels.items() if c.status == 'found']
    unknown = [j for j,c in state.channels.items() if c.status == 'unknown']
    pools = {}
    for j in found + unknown:
        pools[j] = channel_pool(state,j,pool_size)
    masses = [pools[j][3] for j in unknown]
    suffix, ks, kw = old.subset_distribution(masses, len(state.ever_seen))
    worlds = []
    for m in range(count):
        k = rng.choices(ks, kw)[0]
        active = list(found)
        for i,j in enumerate(unknown):
            probability = masses[i]*suffix[i+1][k-1]/suffix[i][k] if k else 0.
            if rng.random() < probability:
                active.append(j)
                k -= 1
        if k:
            raise AssertionError('invalid conditional source subset')
        sources = []
        for j in active:
            points, intervals, weights, _ = pools[j]
            i = rng.choices(range(len(points)), weights)[0]
            lo,hi = intervals[i]
            radius = lo + (hi-lo)*rng.uniform(1e-10,1-1e-10)
            sources.append(a.Source(j, points[i], radius))
        worlds.append(a.Scenario('belief', rng.randrange(2**62), 'posterior', 'hashed', tuple(sources)))
    return worlds


def likelihood(world, state, action, reply):
    """树节点观测权重；已测地点为固定读数的点质量。"""
    j,q = action['channel'], tuple(action['position'])
    c = state.channels[j]
    source = next((s for s in world.sources if s.channel == j), None)
    distance = math.dist(q,source.position) if source else math.inf
    if action['kind'] == 'clear':
        return float((distance <= 20) == (reply['clear_result'] == 'success'))
    for p,result,bearing in c.observations:
        if tuple(p) == q:
            return float(result == reply['measure_result'] and bearing == reply.get('svd_deg'))
    result = reply['measure_result']
    if result == 'no_signal':
        return float(source is None or distance > source.radius)
    if source is None or distance > source.radius:
        return 0.
    if result == 'near':
        return float(distance <= 5)
    if distance <= 5:
        return 0.
    truth = math.degrees(math.atan2(source.position[1]-q[1],source.position[0]-q[0])) % 360
    return .005 * angle_factor(truth, reply['svd_deg'])
