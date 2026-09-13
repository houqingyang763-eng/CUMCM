"""P1 的公开任务、可能出口、逐频道条件覆盖与有限开放路线。"""
import copy
import itertools
import math
import sys
from pathlib import Path

Q3 = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Q3 / 'refinement'))
from refined import RefinedPolicy, clearing_plans, dominated_negative
from posterior import a
from covering_route import SAMPLE_POINTS, CANDIDATE_POINTS
from coverage_state import coverage_certificate


def task(kind, points, channel=None, certified=False, **extra):
    points = [tuple(p) for p in points]
    internal = sum(math.dist(p, q) for p, q in zip(points, points[1:]))
    radius = 1000. - max(math.dist(points[0], p) for p in points)
    return dict(kind=kind, channel=channel, points=points, entry=points[0],
                nominal_exit=points[-1], possible_exits=points if certified else [points[-1]],
                internal_move_m=internal, certified=certified,
                operation_s=(3 * (len(points)-1)+5) if kind != 'scan' else 0.,
                footprint=(points[0], radius), scan_channels=[], **extra)


def scan_channels(state, job, measuring_channel):
    if 'fixed_scan' in job:
        return list(job['fixed_scan'])
    q = job['nominal_exit']
    priority = job['channel']
    # 一个名义计划内状态固定；避免在每个2-opt交换中重复几何证明。
    if '_known_candidates' not in job:
        known = []
        for j, c in state.channels.items():
            if c.status != 'found' or q in c.measured or (job['certified'] and j == priority):
                continue
            center, radius = c.circle()
            if radius > 20 and math.dist(center, q)-radius <= 1500 and dominated_negative(c, q) is None:
                known.append(j)
        job['_known_candidates'] = known
    active = list(job['_known_candidates']) + [j for j in job['scan_channels']
              if state.channels[j].status == 'unknown' and q not in state.channels[j].measured]
    return sorted(active, key=lambda j: (j != priority, j != measuring_channel, j))


def nominal_cost(state, jobs):
    position, channel = state.position, state.measuring_channel
    movement = operations = scans = switches = 0.
    for job in jobs:
        movement += math.dist(position, job['entry']) + job['internal_move_m']
        operations += job['operation_s']
        for j in scan_channels(state, job, channel):
            scans += 5
            switches += int(j != channel)
            channel = j
        position = job['nominal_exit']
    return dict(total_s=movement/5+operations+scans+switches, move_m=movement,
                operation_s=operations, measure_s=scans, switch_s=switches)


def service_pool(state, policy):
    pool = {}
    for j, c in state.channels.items():
        if c.status != 'found':
            continue
        center, radius = c.circle()
        if radius <= 20-1e-6:
            variants = [task('clear', [center], j, True, geometry_radii=[radius])]
        else:
            plans = clearing_plans(state, c)
            variants = [task('clear', order, j, True, geometry_radii=p['radii'])
                        for p in plans for order in itertools.permutations(p['points'])]
            if not variants:
                if radius <= policy.config['try_radius_m'] and j not in policy.tried_centers:
                    variants = [task('attempt', [center], j, reason='single_center_try')]
                elif policy.local_counts.get(j, 0) >= policy.config['local_action_limit']:
                    cells = c.possible_cells()
                    if not cells:
                        raise ValueError('found source without conservative cells')
                    q = min(cells, key=lambda z: math.dist(state.position, z['position']))['position']
                    variants = [task('attempt', [q], j, reason='finite_cell_clear')]
                else:
                    variants = [task('scan', [policy.local_point(state, c)], j)]
        pool[j] = variants
    return pool


def optimize(state, route, locked, check):
    # 内部点序不变，交换时重算全部任务的有向连接及操作费用。
    route = list(route)
    value = nominal_cost(state, route)['total_s']
    for _ in range(50):
        check()
        improved = False
        for i in range(locked, len(route)):
            for j in range(i+1, len(route)):
                candidate = route[:i] + list(reversed(route[i:j+1])) + route[j+1:]
                cost = nominal_cost(state, candidate)['total_s']
                if cost < value-1e-7:
                    route, value, improved = candidate, cost, True
                    break
            if improved:
                break
        if not improved:
            break
    return route


def insertion(state, route, q, locked):
    # 插入的是单点扫描站；所有现存多圆任务的内部序列保持不变。
    best = (math.inf, locked)
    for i in range(locked, len(route)+1):
        before = state.position if i == 0 else route[i-1]['nominal_exit']
        after = route[i]['entry'] if i < len(route) else None
        extra = math.dist(before, q)
        if after is not None:
            extra += math.dist(q, after)-math.dist(before, after)
        best = min(best, (extra, i))
    return best


def plan_route(state, pool, prefix=None, check=lambda: None):
    """强制首任务替换目标服务槽；条件覆盖只存在返回的计划中。"""
    check()
    locked = int(prefix is not None)
    route = [copy.deepcopy(prefix)] if prefix is not None else []
    if route:
        route[0].pop('_known_candidates', None)
    remaining_jobs = {j: variants for j, variants in pool.items()
                      if prefix is None or j != prefix['channel']}
    current = route[-1]['nominal_exit'] if route else state.position
    while remaining_jobs:
        check()
        choices = [(math.dist(current, job['entry'])/5+job['internal_move_m']/5+job['operation_s'],
                    j, i, job) for j, variants in remaining_jobs.items() for i, job in enumerate(variants)]
        _, j, _, job = min(choices, key=lambda x: x[:3])
        selected = copy.deepcopy(job); selected.pop('_known_candidates', None)
        route.append(selected); current = job['nominal_exit']
        del remaining_jobs[j]
    route = optimize(state, route, locked, check)
    unknown = [j for j, c in state.channels.items() if c.status == 'unknown']
    past = {j: [(tuple(q), 1000.) for q, r, _ in state.channels[j].observations if r == 'no_signal']
            for j in unknown}
    if not unknown:
        return route, dict(nominal_cost(state, route), per_channel={})
    points = list(dict.fromkeys(list(SAMPLE_POINTS)+list(state.discovery_points(limit=24))))
    required = {j: sum(1 << i for i, p in enumerate(points)
                       if all(math.dist(p, q) >= r-1e-7 for q, r in past[j])) for j in unknown}
    masks = {}

    def mask(q, radius):
        key = (tuple(q), radius)
        if key not in masks:
            masks[key] = sum(1 << i for i, p in enumerate(points)
                             if radius > 10 and math.dist(p, q) <= radius-10)
        return masks[key]

    remaining = required.copy()
    for i, job in enumerate(route):
        q, radius = job['footprint']; m = mask(q, radius)
        for j in unknown:
            if i < locked:
                if j in job['scan_channels']:
                    remaining[j] &= ~m
            elif remaining[j] & m:
                job['scan_channels'].append(j); remaining[j] &= ~m
    candidates = list(dict.fromkeys(list(CANDIDATE_POINTS)+[tuple(state.position)]
                                   + [job['entry'] for job in route]))

    def add_scan(q, js, index):
        # 多圆首点的缩小足迹不是固定1000米扫描站，不能错误合并。
        same = next((job for i, job in enumerate(route) if i >= locked and
                     len(job['points']) == 1 and math.dist(job['entry'], q) < 1e-6), None)
        if same is None:
            job = task('scan', [q]); job['scan_channels'] = list(js)
            route.insert(index, job)
        else:
            same['scan_channels'] = sorted(set(same['scan_channels']) | set(js))

    for _ in range(30):
        check()
        if not any(remaining.values()):
            break
        choices = []
        for q in candidates:
            m = mask(q, 1000.)
            js = [j for j in unknown if remaining[j] & m]
            if js:
                gain = sum((remaining[j] & m).bit_count() for j in js)
                extra, index = insertion(state, route, q, locked)
                choices.append(((extra/5+6*len(js))/gain, extra, q, index, js))
        if not choices:
            raise ValueError('no candidate for uncovered channel witnesses')
        _, _, q, index, js = min(choices)
        add_scan(q, js, index)
        for j in js:
            remaining[j] &= ~mask(q, 1000.)

    # 同一计划内按圆集合缓存，历史相同的频道不重复计算相同证书。
    cert_cache = {}

    def cert(j, omit=None):
        circles = past[j]+[(q, r) for i, job in enumerate(route) for q, r in [job['footprint']]
                           if i != omit and j in job['scan_channels'] and r > 0]
        key = tuple(sorted(set(circles)))
        if key not in cert_cache:
            check(); cert_cache[key] = coverage_certificate(key)
        return cert_cache[key]

    for j in unknown:
        for _ in range(20):
            proof = cert(j)
            if proof.complete:
                break
            witnesses = proof.witness_points() or tuple(b.point_in_domain(1800) for b in proof.unresolved)
            witnesses = [p for p in witnesses if p is not None]
            if not witnesses:
                raise ValueError('continuous gap without witness')
            q = min(witnesses, key=lambda p: insertion(state, route, p, locked)[0])
            _, index = insertion(state, route, q, locked)
            add_scan(q, [j], index)
        if not cert(j).complete:
            raise ValueError('continuous channel repair exhausted')
    for i, job in enumerate(route):
        if i < locked:
            continue
        for j in list(job['scan_channels']):
            if cert(j, omit=i).complete:
                job['scan_channels'].remove(j)
    route = [job for i, job in enumerate(route) if i < locked or job['channel'] is not None or job['scan_channels']]
    route = optimize(state, route, locked, check)
    proofs = {j: cert(j) for j in unknown}
    assert all(p.complete and p.rational_verified for p in proofs.values())
    info = dict(nominal_cost(state, route), per_channel={j: {
        'actual_negative_scans': len(past[j]),
        'planned_scans': sum(j in t['scan_channels'] for t in route),
        'conditional_coverage_complete': True} for j in unknown})
    return route, info
