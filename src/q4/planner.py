"""Q4 共享服务点替代固定发现站；计划证书从不进入真实信息状态。"""
import copy
import math
import time

import common
import geometry as g
from q4_coverage import q4_coverage_certificate


def route_length(start, jobs):
    points = [tuple(start)] + [tuple(job["position"]) for job in jobs]
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def optimize_route(start, jobs):
    """最近邻加2-opt开放路线；只排列任务，不改变任务/状态。"""
    remaining, route, position = list(jobs), [], tuple(start)
    while remaining:
        index = min(range(len(remaining)), key=lambda i: (
            math.dist(position, remaining[i]["position"]), i))
        job = remaining.pop(index)
        route.append(job)
        position = job["position"]
    for _ in range(40):
        changed = False
        for i in range(len(route)):
            before = start if i == 0 else route[i - 1]["position"]
            for j in range(i + 1, len(route)):
                after = route[j + 1]["position"] if j + 1 < len(route) else None
                old = math.dist(before, route[i]["position"])
                new = math.dist(before, route[j]["position"])
                if after is not None:
                    old += math.dist(route[j]["position"], after)
                    new += math.dist(route[i]["position"], after)
                if new < old - 1e-7:
                    route[i:j + 1] = reversed(route[i:j + 1])
                    changed = True
                    break
            if changed:
                break
        if not changed:
            break
    return route


def _best_route(start, jobs, preserved=None):
    greedy = optimize_route(start, jobs)
    if preserved is not None and route_length(start, preserved) < route_length(start, greedy):
        return preserved
    return greedy


def _scan_points(jobs):
    return {tuple(job["position"]) for job in jobs if job.get("scan_unknown", False)}


def _cost(start, route, unknown_count, past):
    stops = len(_scan_points(route) - past)
    travel = route_length(start, route)
    return travel / 5 + 6 * unknown_count * stops, travel, stops


# 必要条件筛选只负责提前拒绝；批准删点仍必须有连续完整证书。
_PROBES = tuple((float(x), float(y)) for x in range(-1500, 1501, 500)
                for y in range(-1500, 1501, 500) if x * x + y * y <= 1800 ** 2) + tuple(
    (1800 * math.cos(math.radians(k * 15)), 1800 * math.sin(math.radians(k * 15))) for k in range(24))


def _passes_necessary_probes(points):
    for p in _PROBES:
        nearby = [q for q in points if math.dist(p, q) < 1000 - 1e-5]
        hull = g.hull(nearby)
        if len(hull) < 3:
            return False
        if not all(g.cross(g.sub(b, a), g.sub(p, a)) > 1e-5 * max(1.0, math.dist(a, b))
                   for a, b in zip(hull, hull[1:] + hull[:1])):
            return False
    return True


def _can_promise_scan(state, job):
    if job["kind"] == "measure":
        return True
    if job["kind"] != "clear":
        return False
    c = state.channels[job["channel"]]
    q = tuple(job["position"])
    if c.near_position is not None and q == tuple(c.near_position):
        return True
    poly = c.support()
    return bool(poly) and all(math.dist(q, p) <= 20 - 1e-6 for p in poly)


def build_plan(state, service_jobs, anchors, prune_limit=4, max_certificate_checks=12):
    """返回(route, metadata)，仅 scan_unknown=True 的点承诺扫描未知频道。

    调用方必须落实标签：measure在本站扫描，认证clear成功后在清除点扫描。
    multi/try/cell不作为计划覆盖点。证书条件为剩余未知频道在所有标记点均
    返回阴性；真实不存在判定仍由真实state.update中的公开检测完成。
    """
    began = time.perf_counter()
    unknown = [c for c in state.channels.values() if c.status == "unknown"]
    count = len(unknown)
    service = copy.deepcopy(list(service_jobs))
    for job in service:
        job["position"] = tuple(job["position"])
        job["scan_unknown"] = False
    metadata = dict(unknown_count=count, removed_anchors=[], service_scans=[],
                    certificate_checks=0, necessary_rejections=0, anchor_candidates_checked=0,
                    conditional_only=True, adopted_substitution=False)
    if not unknown:
        route = optimize_route(state.position, service)
        metadata.update(estimated_cost_s=route_length(state.position, route) / 5,
                        route_m=route_length(state.position, route), scan_stops=0,
                        base_estimated_cost_s=route_length(state.position, route) / 5,
                        coverage_complete=True, wall_s=time.perf_counter() - began)
        return route, metadata

    past = set.intersection(*[{tuple(q) for q, result, _ in c.observations if result == "no_signal"}
                             for c in unknown])
    anchors = tuple(dict.fromkeys(tuple(q) for q in anchors))
    scans = [dict(kind="scan", position=q, scan_unknown=True) for q in anchors if q not in past]
    baseline = optimize_route(state.position, copy.deepcopy(service + scans))
    base_cost, base_travel, base_stops = _cost(state.position, baseline, count, past)
    # 原始全锚点证书可复用缓存；past补回已经真实检测过的锚点。
    base_certificate = q4_coverage_certificate(anchors)
    if not base_certificate.complete:
        base_certificate = q4_coverage_certificate(sorted(past | _scan_points(baseline)))
    metadata["coverage_complete"] = base_certificate.complete
    metadata["base_estimated_cost_s"] = base_cost
    if prune_limit <= 0 or not base_certificate.complete:
        metadata.update(estimated_cost_s=base_cost, route_m=base_travel,
                        scan_stops=base_stops, wall_s=time.perf_counter() - began)
        return baseline, metadata

    for job in service:
        job["scan_unknown"] = (_can_promise_scan(state, job)
                               and tuple(job["position"]) not in past)
    route = optimize_route(state.position, service + scans)

    def approved(trial, screened=False):
        points = tuple(sorted(past | _scan_points(trial)))
        if not screened and not _passes_necessary_probes(points):
            metadata["necessary_rejections"] += 1
            return False
        if metadata["certificate_checks"] >= max_certificate_checks:
            return False
        metadata["certificate_checks"] += 1
        certificate = q4_coverage_certificate(points)
        return certificate.complete and certificate.rational_verified

    ranked = []
    for index, job in enumerate(route):
        if job["kind"] != "scan":
            continue
        before = state.position if index == 0 else route[index - 1]["position"]
        after = route[index + 1]["position"] if index + 1 < len(route) else None
        saving = math.dist(before, job["position"])
        if after is not None:
            saving += math.dist(job["position"], after) - math.dist(before, after)
        replacements = past | {tuple(item["position"]) for item in service if item["scan_unknown"]}
        close_replacement = any(math.dist(job["position"], p) <= 200 for p in replacements)
        ranked.append((close_replacement, saving, tuple(job["position"])))
    removed = []
    for _, _, q in sorted(ranked, reverse=True):
        if len(removed) >= prune_limit or metadata["anchor_candidates_checked"] >= 6:
            break
        trial = [job for job in route if not (job["kind"] == "scan" and job["position"] == q)]
        # 粗必要条件可快速筛掉无替代的点；最多六个候选进入完整证书阶段。
        if not _passes_necessary_probes(tuple(sorted(past | _scan_points(trial)))):
            metadata["necessary_rejections"] += 1
            continue
        metadata["anchor_candidates_checked"] += 1
        if approved(trial, screened=True):
            removed.append(q)
            route = _best_route(state.position, trial, trial)

    if removed:
        # 删除不必要的服务扫描标签，不删除服务动作本身。
        for index, job in enumerate(route):
            if job["kind"] == "scan" or not job.get("scan_unknown", False):
                continue
            trial = copy.deepcopy(route)
            trial[index]["scan_unknown"] = False
            if _scan_points(trial) == _scan_points(route) or approved(trial):
                route = trial
    else:
        route = baseline

    cost, travel, stops = _cost(state.position, route, count, past)
    if cost >= base_cost - 1e-8:
        route, cost, travel, stops = baseline, base_cost, base_travel, base_stops
        removed = []
    metadata.update(removed_anchors=removed,
                    service_scans=[dict(kind=job["kind"], channel=job.get("channel"),
                                        position=job["position"]) for job in route
                                   if job["kind"] != "scan" and job.get("scan_unknown", False)],
                    estimated_cost_s=cost, route_m=travel, scan_stops=stops,
                    adopted_substitution=bool(removed), wall_s=time.perf_counter() - began)
    return route, metadata
