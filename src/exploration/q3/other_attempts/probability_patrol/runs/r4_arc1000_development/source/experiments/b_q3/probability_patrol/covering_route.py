"""把已知源服务停点与未知区域扫描停点放在同一条开放路线。

离散覆盖仅用于构造路线；未来规划的圆不写入真实状态。
完整规划还须通过公共阴性历史加计划扫描圆的连续覆盖检查。
坐标是当前公开状态的估计，路线长度不是已知真实最优完成时间。
"""
import math

import geometry as g
from coverage_state import coverage_certificate


def route_length(start, jobs):
    points = [start] + [job["position"] for job in jobs]
    return sum(g.distance(a, b) for a, b in zip(points, points[1:]))


def insertion(start, jobs, q):
    best = (math.inf, 0)
    before = start
    for i in range(len(jobs) + 1):
        after = jobs[i]["position"] if i < len(jobs) else None
        extra = g.distance(before, q)
        if after is not None:
            extra += g.distance(q, after) - g.distance(before, after)
        best = min(best, (extra, i))
        if after is not None:
            before = after
    return best


def optimize_route(start, jobs):
    """最近邻起解加开放路径2-opt。只声称该有限搜索的可行结果。"""
    remaining, route = list(jobs), []
    current = start
    while remaining:
        k = min(range(len(remaining)), key=lambda i: (g.distance(current, remaining[i]["position"]), i))
        item = remaining.pop(k)
        route.append(item)
        current = item["position"]
    for _ in range(50):
        improved = False
        for i in range(len(route)):
            before = start if i == 0 else route[i-1]["position"]
            for j in range(i + 1, len(route)):
                after = route[j+1]["position"] if j+1 < len(route) else None
                old = g.distance(before, route[i]["position"])
                new = g.distance(before, route[j]["position"])
                if after is not None:
                    old += g.distance(route[j]["position"], after)
                    new += g.distance(route[i]["position"], after)
                if new < old - 1e-7:
                    route[i:j+1] = reversed(route[i:j+1])
                    improved = True
                    break
            if improved:
                break
        if not improved:
            break
    return route


SAMPLE_POINTS = tuple((float(x), float(y)) for x in range(-1800, 1801, 200)
                      for y in range(-1800, 1801, 200) if x*x+y*y <= 1800**2) + tuple(
    g.mul(g.unit(k*3), 1800.0) for k in range(120))
CANDIDATE_POINTS = tuple((float(x), float(y)) for x in range(-1600, 1601, 400)
                         for y in range(-1600, 1601, 400) if x*x+y*y <= 1800**2) + tuple(
    g.mul(g.unit(k*15), radius) for radius in (1000.0, 1200.0, 1450.0, 1700.0) for k in range(24))


def common_negative_circles(state):
    """只共享每一个未知频道都实际得到的阴性观测，不跨频道借证据。"""
    histories = []
    for c in state.channels.values():
        if c.status == "unknown":
            histories.append({(tuple(q), 1000.0) for q, result, _ in c.observations if result == "no_signal"})
    return sorted(set.intersection(*histories)) if histories else []


def planned_certificate(past, jobs):
    # 此证书的含义仅是：若未来这些频道在选定点均为阴性，则覆盖可闭合。
    # 它绝不触发真实 state.status 的任何变化。
    circles = past + [(j["position"], 1000.0) for j in jobs if j.get("scan_unknown")]
    return coverage_certificate(circles)


def covering_route(state, service_jobs):
    unknown_count = sum(c.status == "unknown" for c in state.channels.values())
    jobs = [dict(j, scan_unknown=False) for j in service_jobs]
    if not unknown_count:
        route = optimize_route(state.position, jobs)
        return route, {"planned_unknown_stops": 0, "planned_route_m": route_length(state.position, route),
                       "planned_coverage_complete": True, "plan_has_unknown_channels": False}

    past = common_negative_circles(state)
    actual_cert = coverage_certificate(past)
    # 真实未决见证补入离散集合，避免小缝在粗网格上完全消失。
    points = list(SAMPLE_POINTS) + list(state.discovery_points(limit=24))
    required = list(dict.fromkeys(p for p in points if all(g.distance(p, q) >= r - 1e-7 for q, r in past)))
    if not required and not actual_cert.complete:
        required = [b.point_in_domain(1800) for b in actual_cert.unresolved]
        required = list(dict.fromkeys(p for p in required if p is not None))
    full_mask = (1 << len(required)) - 1
    masks = {}

    def mask(q):
        if q not in masks:
            masks[q] = sum(1 << i for i, p in enumerate(required) if g.distance(p, q) <= 990.0)
        return masks[q]

    candidates = list(dict.fromkeys(list(CANDIDATE_POINTS) + required + [state.position]))
    for q in candidates + [j["position"] for j in jobs]:
        mask(q)

    def construct(mode):
        route = optimize_route(state.position, [dict(j, scan_unknown=True) for j in jobs])
        covered = 0
        for job in route:
            covered |= mask(job["position"])
        remaining = full_mask & ~covered
        for _ in range(16):
            if not remaining:
                break
            options = []
            for q in candidates:
                gain = (mask(q) & remaining).bit_count()
                if not gain:
                    continue
                extra, index = insertion(state.position, route, q)
                # 两个有明确含义的构造器：最大覆盖、每新增覆盖点的插入秒数。
                # 最后只按完整计划的米/秒与必要扫描秒数选可行解，不称后验价值。
                cost = extra / 5 + 6 * unknown_count
                key = (-gain, cost, q) if mode == "coverage" else (cost / gain, -gain, q)
                options.append((key, q, index))
            if not options:
                raise AssertionError("离散覆盖计划存在无法覆盖的合法域内点")
            _, q, index = min(options)
            route.insert(index, {"kind": "scan", "position": q, "scan_unknown": True})
            remaining &= ~mask(q)

        # 删除冗余未知扫描标签，服务任务本身始终保留。
        for i in sorted(range(len(route)), key=lambda i: mask(route[i]["position"]).bit_count()):
            other = 0
            for k, item in enumerate(route):
                if k != i and item.get("scan_unknown"):
                    other |= mask(item["position"])
            if full_mask & ~other == 0:
                route[i]["scan_unknown"] = False
        route = [j for j in route if j["kind"] == "service" or j["scan_unknown"]]
        route = optimize_route(state.position, route)

        # 用真正的连续圆覆盖修补离散计划；不把计划当成已发生的测量。
        for _ in range(12):
            cert = planned_certificate(past, route)
            if cert.complete:
                break
            witnesses = cert.witness_points()
            if not witnesses:
                witnesses = tuple(b.point_in_domain(1800) for b in cert.unresolved)
                witnesses = tuple(p for p in witnesses if p is not None)
            if not witnesses:
                raise AssertionError("连续规划覆盖未闭合且没有可访问的修补位置")
            # 见证点已处于缺口，至少补足一个真实未覆盖位置；优先最小插入代价。
            q = min(witnesses, key=lambda p: insertion(state.position, route, p)[0])
            _, index = insertion(state.position, route, q)
            route.insert(index, {"kind": "scan", "position": q, "scan_unknown": True})
            route = optimize_route(state.position, route)
        cert = planned_certificate(past, route)
        if not cert.complete:
            raise AssertionError("未来扫描覆盖规划未在有界修补内闭合")
        cost = route_length(state.position, route) / 5 + 6 * unknown_count * sum(j["scan_unknown"] for j in route)
        return cost, route, cert

    alternatives = [construct(mode) for mode in ("coverage", "insertion")]
    estimated_s, route, cert = min(alternatives, key=lambda item: item[0])
    return route, {"planned_unknown_stops": sum(j["scan_unknown"] for j in route),
                   "planned_route_m": route_length(state.position, route),
                   "planned_travel_unknown_scan_s": estimated_s,
                   "planned_coverage_complete": cert.complete,
                   "planned_coverage_verified": cert.rational_verified,
                   "plan_has_unknown_channels": True,
                   "planned_jobs": route}
