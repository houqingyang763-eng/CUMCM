"""F3在Q4的适配：共享任务路线、定向条件模型、认证多圆清除。

候选几何不改变保守状态；最终查漏仍由真实阴性覆盖证书完成。
可选同场景完整续行比较，有限抽样失败时回退当前确定性控制器。
"""
import copy
from dataclasses import asdict, dataclass
import itertools
import math
import random
import statistics
import time

import common
from common import Joint25Policy, Q4_SYMMETRIC25_ANCHORS
import geometry as g
from q4 import Q4Config
from q4_coverage import q4_coverage_certificate
from belief import ConditionalEnvironment, history_seed, make_pool, reception_mass, sample_worlds


def major_axis(poly):
    if len(poly) < 2:
        return (1., 0.)
    a, b = max(itertools.combinations(poly, 2), key=lambda pair: math.dist(*pair))
    d = math.dist(a, b)
    return ((b[0]-a[0])/d, (b[1]-a[1])/d) if d > 1e-9 else (1., 0.)


def route_length(start, jobs):
    points = [start] + [j['position'] for j in jobs]
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def optimize_route(start, jobs):
    remaining, route, position = list(jobs), [], start
    while remaining:
        k = min(range(len(remaining)), key=lambda i: (math.dist(position, remaining[i]['position']), i))
        job = remaining.pop(k)
        route.append(job)
        position = job['position']
    for _ in range(30):
        changed = False
        for i in range(len(route)):
            before = start if i == 0 else route[i-1]['position']
            for j in range(i+1, len(route)):
                after = route[j+1]['position'] if j+1 < len(route) else None
                old, new = math.dist(before, route[i]['position']), math.dist(before, route[j]['position'])
                if after is not None:
                    old += math.dist(route[j]['position'], after)
                    new += math.dist(route[i]['position'], after)
                if new < old-1e-7:
                    route[i:j+1] = reversed(route[i:j+1])
                    changed = True
                    break
            if changed:
                break
        if not changed:
            break
    return route


def clearing_plans(state, c):
    """复用F3分片思路，实际复算每片全部顶点，证明最多2/3次能清除。"""
    poly = c.support()
    if not poly:
        return []
    axis = major_axis(poly)
    values = [g.dot(p, axis) for p in poly]
    lo, hi = min(values), max(values)
    plans = []
    for k in (2, 3):
        centers, radii = [], []
        for i in range(k):
            left, right = lo+(hi-lo)*i/k, lo+(hi-lo)*(i+1)/k
            part = g.clip(g.clip(poly, axis, right), g.mul(axis, -1), -left)
            if not part:
                break
            center, _ = g.enclosing_circle(part)
            centers.append(center)
            radii.append(max(math.dist(center, p) for p in part))
        if len(centers) != k or max(radii) > 20-1e-6:
            continue
        order = min(itertools.permutations(range(k)), key=lambda ix:
                    math.dist(state.position, centers[ix[0]]) +
                    sum(math.dist(centers[a], centers[b]) for a, b in zip(ix, ix[1:])))
        points = [centers[i] for i in order]
        cost = (math.dist(state.position, points[0]) + sum(math.dist(a, b) for a, b in zip(points, points[1:]))) / 5 + 3*(k-1)+5
        plans.append(dict(kind='multi', position=points[0], channel=c.channel,
                          points=points, radii=[radii[i] for i in order], local_cost_s=cost))
    return plans


@dataclass(frozen=True)
class CandidateConfig(Q4Config):
    initial_points: tuple = ((0., 0.), (944., 0.))
    discovery_points: tuple = ()
    local_action_limit: int = 12
    use_belief: bool = True
    use_multiclear: bool = True
    opportunistic_scan_from_known: int = 17
    prune_planned_stops: bool = False
    prune_limit: int = 4
    pool_size: int = 32
    omni_prior: float = .5
    rollout_samples: int = 0
    rollout_pool_size: int = 96
    rollout_base: str = 'joint25'
    rollout_decision_limit: int = 12
    rollout_wall_budget_s: float = 600.


class CandidatePolicy:
    def __init__(self, config=None):
        if isinstance(config, dict):
            config = CandidateConfig(**config)
        self.config = config or CandidateConfig()
        self.anchors = tuple(tuple(q) for q in self.config.discovery_points) or Q4_SYMMETRIC25_ANCHORS
        if self.config.discovery_points:
            if any(len(q) != 2 or any(not math.isfinite(v) or abs(v) > 2000000 for v in q) for q in self.anchors):
                raise ValueError('发现点坐标非法')
            certificate = q4_coverage_certificate(self.anchors)
            if not (certificate.complete and certificate.rational_verified):
                raise ValueError('自定义发现点集没有完整连续覆盖证书')
        self.initial_index = 0
        self.station = None
        self.queue = []
        self.station_reason = None
        self.multi = None
        self.after_clear_scan = False
        self.clear_scan_commitment = None
        self.local_counts = {}
        self.tried_centers = set()
        self.seen_cleared = set()
        self.fallback = Joint25Policy()
        self.fallback_started = False
        self.pools = {}
        self.pool_stamps = {}
        self.decisions = []
        self.plans = []
        self.rollout_wall_s = 0.
        self.rollout_attempts = 0
        self._in_rollout = False

    @staticmethod
    def action(kind, q, j, reason, **extra):
        return dict(kind=kind, position=tuple(q), channel=j, reason=reason, **extra)

    def metadata(self):
        return dict(config=asdict(self.config), decisions=self.decisions, plans=self.plans,
                    local_counts=self.local_counts, rollout_wall_s=self.rollout_wall_s,
                    rollout_attempts=self.rollout_attempts, fallback_started=self.fallback_started)

    def _pool(self, state, c):
        stamp = (len(c.observations), len(c.exclusions), c.status)
        if self.pool_stamps.get(c.channel) != stamp:
            rng = random.Random(history_seed(state, 2026091331+c.channel))
            self.pools[c.channel] = make_pool(state, c, rng, self.config.pool_size, self.config.omni_prior)
            self.pool_stamps[c.channel] = stamp
        return self.pools[c.channel]

    def _opportunistic_scan(self, state):
        # 17表示关闭。此规则只增加已到达服务点的检测，不作概率判空。
        # 目的为利用题面16源上界，争取由阳性发现取消整个剩余查漏阶段。
        return len(state.ever_seen) >= self.config.opportunistic_scan_from_known

    def _station(self, state, q, reason, priority=None, scan_unknown=True):
        self.station, self.station_reason = tuple(q), reason
        eligible = []
        for j, c in state.channels.items():
            if c.status in ('absent', 'cleared') or tuple(q) in c.measured:
                continue
            if c.status == 'unknown' and not scan_unknown:
                continue
            if c.status == 'found':
                center, radius = c.circle()
                if radius <= 20-1e-5 or math.dist(center, q)-radius > 1500:
                    continue
            eligible.append(j)
        self.queue = sorted(eligible, key=lambda j: (j != priority, j != state.measuring_channel, j))
        return self._station_action(state)

    def _station_action(self, state):
        while self.queue:
            j = self.queue.pop(0)
            c = state.channels[j]
            if c.status in ('absent', 'cleared') or self.station in c.measured:
                continue
            if c.status == 'found' and c.circle()[1] <= 20-1e-5:
                continue
            return self.action('measure', self.station, j, self.station_reason)
        self.station = None
        return None

    def _multi_action(self, state):
        if self.multi is None:
            return None
        c = state.channels[self.multi['channel']]
        if c.status == 'cleared':
            self.multi = None
            return None
        if not self.multi['points']:
            raise AssertionError('认证多圆全部用尽但尚未清除')
        return self.action('clear', self.multi['points'].pop(0), c.channel, 'q4_certified_multiclear')

    def _measure_options(self, state, c):
        center, radius = c.circle()
        axis = major_axis(c.support())
        normal = (-axis[1], axis[0])
        offset = min(300., max(30., radius/2))
        points = [g.add(center, g.mul(normal, sign*offset)) for sign in (-1, 1)]
        positives = [q for q, r, _ in c.observations if r in ('direction', 'near')][-2:]
        # 已接收侧的接近点与横向点共同竞争；估计中心插值只作候选。
        for p in positives:
            for t in (.1, .3):
                q = g.add(center, g.mul(g.sub(p, center), t))
                points.extend([q, g.add(q, g.mul(normal, 30)), g.add(q, g.mul(normal, -30))])
        points.append(state.position)
        points = list(dict.fromkeys(tuple(q) for q in points if tuple(q) not in c.measured))
        pool = None
        if self.config.use_belief:
            try:
                pool = self._pool(state, c)
            except ValueError:
                pass
        # 本地尾项只为基策略构造；可选外层rollout才比较完整剩余费用。
        work = 5 + max(0., 2*radius-40)/5 + 3*max(0., math.ceil(radius/20)-1)
        options = []
        for q in points:
            if pool:
                total, future = sum(pool['weights']), 0.
                for x, slices, weight in zip(pool['points'], pool['slices'], pool['weights']):
                    if weight <= 0:
                        continue
                    probability = reception_mass(x, slices, q)
                    bearing = math.degrees(math.atan2(x[1]-q[1], x[0]-q[0]))
                    poly = g.wedge(c.support(), q, bearing)
                    if not poly:
                        remaining = work
                    else:
                        _, rnew = g.enclosing_circle(poly)
                        remaining = 5 + max(0., 2*rnew-40)/5 + 3*max(0., math.ceil(rnew/20)-1)
                    future += weight * ((1-probability)*work + probability*remaining)
                future /= total
            else:
                # 回退F3几何次序，仍使用Q4保守状态保证完成。
                future = 5 + min(work-5, math.dist(q, center)*math.tan(math.radians(1.005))*2/5)
            cost = math.dist(state.position, q)/5 + 5 + int(c.channel != state.measuring_channel) + math.dist(q, center)/5 + future
            options.append(dict(kind='measure', position=q, channel=c.channel, local_cost_s=cost))
        return sorted(options, key=lambda p: (p['local_cost_s'], p['position']))

    def _job(self, state, c):
        center, radius = c.circle()
        if c.near_position is not None:
            return dict(kind='clear', position=c.near_position, channel=c.channel)
        if radius <= 20-1e-5:
            return dict(kind='clear', position=center, channel=c.channel)
        if radius <= 30 and c.channel not in self.tried_centers and c.compatible(center):
            return dict(kind='try', position=center, channel=c.channel)
        if self.local_counts.get(c.channel, 0) >= self.config.local_action_limit:
            cell = min(c.possible_cells(), key=lambda x: (x['index'][0], x['index'][1] if x['index'][0] == 0 else -x['index'][1]))
            return dict(kind='cell', position=cell['position'], channel=c.channel)
        options = self._measure_options(state, c)
        if self.config.use_multiclear:
            options.extend(clearing_plans(state, c))
        if not options:
            cell = min(c.possible_cells(), key=lambda x: math.dist(state.position, x['position']))
            return dict(kind='cell', position=cell['position'], channel=c.channel)
        return min(options, key=lambda p: p['local_cost_s'])

    def _plan(self, state):
        jobs = [self._job(state, c) for c in state.channels.values() if c.status == 'found']
        if self.config.prune_planned_stops:
            from planner import build_plan
            route, record = build_plan(state, jobs, self.anchors,
                                       prune_limit=self.config.prune_limit)
            self.plans.append(dict(at_action=state.actions, jobs=route, **record))
            return route
        unknown = [c for c in state.channels.values() if c.status == 'unknown']
        past = set.intersection(*[{tuple(q) for q, r, _ in c.observations if r == 'no_signal'} for c in unknown]) if unknown else set()
        if unknown:
            jobs.extend(dict(kind='scan', position=q) for q in self.anchors if q not in past)
        route = optimize_route(state.position, jobs)
        self.plans.append(dict(at_action=state.actions, route_m=route_length(state.position, route),
                               scan_stops=sum(j['kind'] == 'scan' for j in route), removed=[],
                               jobs=route))
        return route

    def _install(self, state, job):
        kind, q = job['kind'], job['position']
        self.station, self.queue = None, []
        if kind == 'scan':
            return self._station(state, q, 'q4_joint_discovery_scan')
        j = job['channel']
        if kind == 'multi':
            self.multi = dict(channel=j, points=list(job['points']))
            return self._multi_action(state)
        if kind == 'measure':
            self.local_counts[j] = self.local_counts.get(j, 0)+1
            return self._station(state, q, 'q4_joint_local_scan', priority=j,
                                 scan_unknown=(job.get('scan_unknown', not self.config.prune_planned_stops)
                                               or self._opportunistic_scan(state)))
        if kind == 'try':
            self.tried_centers.add(j)
        if kind == 'clear' and (job.get('scan_unknown', not self.config.prune_planned_stops)
                                or self._opportunistic_scan(state)):
            self.clear_scan_commitment = (j, tuple(q))
        return self.action('clear', q, j, 'q4_'+kind+'_clear')

    def _rollout(self, state, job, worlds, deadline=float('inf')):
        values = []
        for world in worlds:
            s, p = copy.deepcopy(state), copy.deepcopy(self)
            p._in_rollout = True
            p.decisions, p.plans = [], []
            env = ConditionalEnvironment(world, s)
            continuation = None
            action = p._install(s, job)
            for step in range(3000):
                if time.perf_counter() >= deadline:
                    raise ValueError('整局续行现实预算用尽，保留基策略动作')
                if action is None:
                    raise ValueError('续行候选未产生动作')
                reply = env.act(action)
                s.update(action, reply)
                if s.complete:
                    if len(env.cleared) != len(world.sources):
                        raise AssertionError('试算提前结束')
                    values.append(env.virtual_time_s-state.virtual_time_s)
                    break
                if env.virtual_time_s-state.virtual_time_s > 30000:
                    raise ValueError('试算超过预算')
                if self.config.rollout_base == 'same':
                    action = p.choose(s)
                    continue
                if self.config.rollout_base != 'joint25':
                    raise ValueError('未知续行基策略')
                # 当前候选作为一组实际要执行的动作：多圆直到成功，或本站频道队列。
                # 完成后由快速、可靠的旧Q4基策略续行到整个任务结束。
                if continuation is None:
                    action = p._multi_action(s)
                    if action is None and p.station is not None:
                        action = p._station_action(s)
                    if action is None and p.clear_scan_commitment is not None:
                        j, q = p.clear_scan_commitment
                        p.clear_scan_commitment = None
                        if s.channels[j].status == 'cleared' and math.dist(s.position, q) <= 1e-8:
                            action = p._station(s, q, 'q4_rollout_committed_scan')
                    if action is not None:
                        continue
                    continuation = Joint25Policy()
                action = continuation.choose(s)
            else:
                raise ValueError('试算动作超过预算')
        return values

    def choose(self, state):
        if state.complete:
            return None
        if (self.fallback_started or state.virtual_time_s >= self.config.adaptive_virtual_budget_s
                or state.actions >= self.config.adaptive_action_limit
                or time.perf_counter() >= getattr(self, 'wall_deadline', float('inf'))-30.):
            self.fallback_started = True
            return self.fallback.fallback(state)
        for c in state.channels.values():
            if c.status == 'found' and c.support() and all(math.dist(state.position, p) <= 20-1e-6 for p in c.support()):
                return self.action('clear', state.position, c.channel, 'q4_certain_here')
        action = self._multi_action(state)
        if action:
            return action
        if self.station is not None:
            action = self._station_action(state)
            if action:
                return action
        while self.initial_index < len(self.config.initial_points):
            q = self.config.initial_points[self.initial_index]
            self.initial_index += 1
            action = self._station(state, q, 'q4_initial_scan')
            if action:
                return action
        cleared = {j for j, c in state.channels.items() if c.status == 'cleared'}
        new_cleared = cleared-self.seen_cleared
        self.seen_cleared = cleared
        if new_cleared or self.after_clear_scan:
            self.after_clear_scan = False
            commitment = self.clear_scan_commitment
            scan_unknown = (not self.config.prune_planned_stops or self._opportunistic_scan(state) or
                (commitment is not None and commitment[0] in new_cleared and
                 math.dist(commitment[1], state.position) <= 1e-8))
            self.clear_scan_commitment = None
            action = self._station(state, state.position, 'q4_clearance_shared_scan',
                                   scan_unknown=scan_unknown)
            if action:
                return action
        route = self._plan(state)
        if not route:
            self.fallback_started = True
            return self.fallback.fallback(state)
        chosen = route[0]
        if (not self._in_rollout and self.config.rollout_samples > 0
                and self.rollout_attempts < self.config.rollout_decision_limit
                and self.rollout_wall_s < self.config.rollout_wall_budget_s):
            options = [chosen]
            if 'channel' in chosen:
                c = state.channels[chosen['channel']]
                if c.circle()[1] > 20:
                    options.extend(self._measure_options(state, c)[:2])
                    options.extend(clearing_plans(state, c))
            if chosen['kind'] == 'scan':
                options.extend(j for j in route[1:4] if j['kind'] != 'scan')
            unique = {}
            for job in options:
                unique.setdefault((job['kind'], tuple(job['position']), job.get('channel')), job)
            options = list(unique.values())
            if len(options) > 1:
                self.rollout_attempts += 1
                stamp = time.perf_counter()
                record = dict(at_action=state.actions, original=chosen)
                try:
                    worlds, info = sample_worlds(state, self.config.rollout_samples, self.config.rollout_pool_size, self.config.omni_prior)
                    deadline = min(stamp + max(0., self.config.rollout_wall_budget_s-self.rollout_wall_s),
                                   getattr(self, 'wall_deadline', float('inf'))-30.)
                    costs = [self._rollout(state, job, worlds, deadline) for job in options]
                    means = [statistics.mean(v) for v in costs]
                    ix = min(range(len(options)), key=lambda i: means[i])
                    chosen = options[ix]
                    record.update(options=options, costs_s=costs, mean_s=means, chosen_index=ix, posterior=info)
                except (ValueError, RuntimeError, AssertionError) as exc:
                    record['fallback'] = str(exc)
                record['wall_s'] = time.perf_counter()-stamp
                self.rollout_wall_s += record['wall_s']
                self.decisions.append(record)
        action = self._install(state, chosen)
        if action is None:
            self.fallback_started = True
            return self.fallback.fallback(state)
        return action
