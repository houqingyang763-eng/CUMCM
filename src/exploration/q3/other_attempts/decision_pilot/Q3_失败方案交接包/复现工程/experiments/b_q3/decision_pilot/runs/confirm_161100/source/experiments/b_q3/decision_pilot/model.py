"""Q3 小验证：历史相容场景 + 一次行动块预演。无官方接口。"""
import ast
import copy
import hashlib
import math
from pathlib import Path
import random
import statistics
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'experiments/b_benchmark_scale'))
from two_stage import TwoStagePolicy, CONFIGS, route_order, g
from simulation import LocalEnvironment, Scenario, Source
from state import InformationState, audit_state

WORLD_COUNT = 5  # 小验证的计算预算，不代表概率精度已足够。
WORLD_SEED = 271828
ACTION_LIMIT = 300  # 失败保护；触发即记为失败，不能计入成功均值。


def sweep_class():
    """原文件Q3节点原样编译；不导入其Q4依赖或历史保护模块。"""
    path = ROOT / 'experiments/b_overnight/sweep_policy.py'
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    body = [n for n in tree.body if
            isinstance(n, ast.Import) or
            isinstance(n, ast.ImportFrom) and n.module == 'task_cost' or
            isinstance(n, ast.ClassDef) and n.name in ('SweepMixin', 'Q3SweepPolicy')]
    namespace = {'__name__': 'isolated_q3_sweep'}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace['Q3SweepPolicy']


def action(kind, position, channel, reason):
    return dict(kind=kind, position=tuple(position), channel=channel, reason=reason)


def found_order(state):
    channels = [j for j, c in state.channels.items() if c.status == 'found']
    return route_order(state.position, channels,
                       [state.channels[j].circle()[0] for j in channels])[0]


class CenterContinuation:
    """可执行续行：估计中心开放路径，接近后测向，足够小时清除。无W/G。"""
    def __init__(self):
        self.target = None
        self.center_tried = set()

    def choose(self, state):
        if state.complete:
            return None
        assert not any(c.status == 'unknown' for c in state.channels.values())
        # 随途已能严格保证清除的源直接清除，无新增移动。
        for j, c in state.channels.items():
            if c.status == 'found' and all(g.distance(state.position, p) < 20-1e-5 for p in c.support()):
                return action('clear', state.position, j, 'guaranteed_here')
        if self.target is None or state.channels[self.target].status != 'found':
            self.target = found_order(state)[0]
        j, c = self.target, state.channels[self.target]
        center, radius = c.circle()
        if radius < 20-1e-5:
            return action('clear', center, j, 'guaranteed_center')
        if radius <= 30 and j not in self.center_tried and c.compatible(center):
            self.center_tried.add(j)
            return action('clear', center, j, 'one_small_center_try')
        # 大区域时继续获得方向，绝不用格子数推算剩余秒数。
        q = center
        if any(g.distance(q, old) < 1e-5 for old in c.measured):
            # 只有中心曾测过时才改变视角；40=2*清除半径，是候选几何尺度。
            support = c.support()
            u, v = max(((u, v) for u in support for v in support), key=lambda uv: g.distance(*uv))
            d = g.sub(v, u)
            n = (-d[1], d[0])
            n = g.mul(n, 1/max(math.hypot(*n), 1e-9))
            choices = [g.add(center, g.mul(n, s*40)) for s in (1, -1, 2, -2)]
            choices = [p for p in choices if all(g.distance(p, old) > 1e-5 for old in c.measured)]
            if not choices:
                raise RuntimeError('局部几何续行无新测点；小验证记失败')
            q = min(choices, key=lambda p: g.distance(state.position, p))
        return action('measure', q, j, 'approach_center_and_measure')


def radius_interval(c, x):
    """检查原始观测，返回允许的固定接收半径区间；负观测为严格上界。"""
    if (math.hypot(*x) > 1800 or not c.compatible(x)
            or any(r == 20 and g.distance(q, x) <= 20 for q, r in c.exclusions)):
        return None
    lo, hi = 1000., 1500.
    for q, result, bearing in c.observations:
        d = g.distance(q, x)
        if result == 'no_signal':
            hi = min(hi, d - 1e-7)
        else:
            lo = max(lo, d)
            if result == 'near' and d > 5:
                return None
            if result == 'direction':
                if d <= 5:
                    return None
                a = math.degrees(math.atan2(x[1]-q[1], x[0]-q[0]))
                if abs(g.angle_delta(a, bearing)) > 1.005:
                    return None
    return (lo, hi) if lo <= hi else None


def sample_source(c, rng):
    poly = c.polygon
    if len(poly) < 3 or g.area(poly) < 1e-12:
        raise ValueError('退化可行域；不伪造场景')
    triangles = [(poly[0], poly[i], poly[i+1]) for i in range(1, len(poly)-1)]
    weights = [g.area(list(t)) for t in triangles]
    for _ in range(30000):
        a, b, d = rng.choices(triangles, weights=weights, k=1)[0]
        u, v = rng.random(), rng.random()
        if u+v > 1:
            u, v = 1-u, 1-v
        x = g.add(a, g.add(g.mul(g.sub(b, a), u), g.mul(g.sub(d, a), v)))
        interval = radius_interval(c, x)
        if interval is not None:
            return Source(c.channel, x, rng.uniform(*interval))
    raise RuntimeError(f'频道{c.channel}相容场景拒绝采样耗尽')


def public_seed(state):
    # 不接收案例名、真值seed或私有环境。相同公开历史必得相同预演。
    history = [(j, c.status, c.observations, c.exclusions) for j, c in state.channels.items()]
    payload = repr((WORLD_SEED, history, state.position, state.measuring_channel)).encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], 'big')


class HistoryEnvironment(LocalEnvironment):
    """过去已测点保留原反馈，其他点使用假设的有界固定空间误差场。"""
    def __init__(self, scenario, state):
        super().__init__(scenario)
        self.position = state.position
        self.channel = state.measuring_channel
        self.virtual_time_s = state.virtual_time_s
        self.history = {(j, tuple(q)): (result, a) for j, c in state.channels.items()
                        if c.status == 'found' for q, result, a in c.observations}

    def act(self, a):
        response = super().act(a)
        key = (a['channel'], tuple(a['position']))
        if a['kind'] == 'measure' and key in self.history and a['channel'] not in self.cleared:
            result, bearing = self.history[key]
            response['measure_result'] = result
            response.pop('svd_deg', None)
            if bearing is not None:
                response['svd_deg'] = bearing
        return response


def worlds_from_history(state):
    rng = random.Random(public_seed(state))
    worlds = []
    for k, noise in enumerate(('hashed', 'smooth', 'biased', 'hashed', 'biased')):
        sources = tuple(sample_source(c, rng) for c in state.channels.values() if c.status == 'found')
        seed = rng.randrange(1, 2**30)
        worlds.append(Scenario(f'imagined_{k}', seed, 'history_conditioned', noise, sources))
    assert len(worlds) == WORLD_COUNT
    return worlds


def candidates(state):
    """完整首行动块：可改变首访对象，可在同一位置服务多个频道。"""
    result = [dict(name='default', actions=[])]
    order = found_order(state)
    sites = [(f'center_{j}', state.channels[j].circle()[0], j) for j in order[:3]]
    if len(order) >= 2:
        a, b = [state.channels[j].circle()[0] for j in order[:2]]
        sites.append(('midpoint_first_two', g.mul(g.add(a, b), .5), None))
    sites.append(('current', state.position, None))
    for label, q, primary in sites:
        if primary is not None:
            c = state.channels[primary]
            kind = 'clear' if c.circle()[1] <= 30 and c.compatible(q) else 'measure'
            single = action(kind, q, primary, label+'_single')
            if kind == 'clear' or q not in c.measured:
                result.append(dict(name=label+'_single', actions=[single]))
        js = [j for j, c in state.channels.items() if c.status == 'found'
              and c.circle()[1] > 20-1e-5 and q not in c.measured
              and g.distance(q, c.circle()[0]) <= 1000]
        # 距估计中心1000米仅筛候选，不当作保证有信号。
        js.sort(key=lambda j: (j != state.measuring_channel, j))
        if js:
            result.append(dict(name=label+'_shared', actions=[action('measure', q, j, label+'_shared') for j in js]))
    unique, seen = [], set()
    for item in result:
        key = tuple((a['kind'], a['position'], a['channel']) for a in item['actions'])
        if key not in seen:
            unique.append(item)
            seen.add(key)
    return unique


def continue_to_end(initial, env, block, audit=True):
    state = copy.deepcopy(initial)
    start = state.virtual_time_s
    queue = list(copy.deepcopy(block))
    policy = CenterContinuation()
    rows = []
    costs = dict(move_s=0., measure_s=0., switch_s=0., success_clear_s=0., fail_clear_s=0.)
    while not state.complete:
        if len(rows) >= ACTION_LIMIT:
            raise RuntimeError('续行动作上限；记为失败')
        a = queue.pop(0) if queue else policy.choose(state)
        assert a is not None and math.hypot(*a['position']) <= 5000
        # 可执行块中的目标如果刚才已经清除，跳过多余检测。
        if state.channels[a['channel']].status != 'found':
            continue
        costs['move_s'] += g.distance(state.position, a['position'])/5
        if a['kind'] == 'measure':
            costs['measure_s'] += 5
            costs['switch_s'] += int(a['channel'] != state.measuring_channel)
        r = env.act(a)
        if a['kind'] == 'clear':
            costs['success_clear_s' if r['clear_result'] == 'success' else 'fail_clear_s'] += 5 if r['clear_result'] == 'success' else 3
        state.update(a, r)
        assert abs(env.virtual_time_s-start-sum(costs.values())) < 1e-5
        if audit:
            audit_state(state, env)
        rows.append(dict(step=len(rows)+1, action=a, response=r))
    return dict(remaining_s=state.virtual_time_s-start, total_s=state.virtual_time_s,
                costs=costs, actions=rows)


def evaluate(state, options, worlds):
    rows = []
    for item in options:
        values = []
        errors = []
        for world in worlds:
            try:
                result = continue_to_end(state, HistoryEnvironment(world, state), item['actions'])
                values.append(result['remaining_s'])
            except (RuntimeError, ValueError, AssertionError) as e:
                values.append(None)
                errors.append(str(e))
        score = statistics.mean(values) if all(v is not None for v in values) else None
        rows.append(dict(name=item['name'], mean_s=score, scenario_s=values, errors=errors))
    valid = [(r['mean_s'], i) for i, r in enumerate(rows) if r['mean_s'] is not None]
    if not valid:
        raise RuntimeError('所有候选预演失败，不能声称选出最优')
    return min(valid)[1], rows
