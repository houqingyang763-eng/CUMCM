"""独立有界搜索更紧凑Q4发现点集：筛选不作证明，连续证书才批准。"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import time

import numpy as np

import common
from common import PROJECT, Q4_SYMMETRIC25_ANCHORS
from planner import optimize_route, route_length
from q4_coverage import (Q4CoverageCertificate, Q4CoverageLeaf, q4_coverage_certificate,
                         verify_q4_certificate)
from coverage import Box


def make_points(spec):
    def ring(n, radius, phase):
        return [(radius * math.cos(math.radians(phase) + 2 * math.pi * i / n),
                 radius * math.sin(math.radians(phase) + 2 * math.pi * i / n)) for i in range(n)]
    if spec["family"] == "two_rings":
        points = ring(spec["outer_n"], spec["outer_r"], 0.0)
        points += ring(spec["inner_n"], spec["inner_r"], spec["phase"])
    elif spec["family"] == "triangular_shell":
        points = ring(spec["outer_n"], spec["outer_r"], spec["phase"])
        points += ring(6, spec["middle_r"], 30.0)
        points += ring(6, spec["inner_r"], 0.0)
    else:
        raise ValueError(spec["family"])
    return points + ([(0.0, 0.0)] if spec["center"] else [])


def polar_probes(radii, angles):
    return np.asarray([(0.0, 0.0)] + [
        (r * math.cos(2 * math.pi * i / angles), r * math.sin(2 * math.pi * i / angles))
        for r in radii for i in range(angles)], dtype=float)


def maximum_gap(points, probes):
    """近邻方向最大空隙<180度等价于测点严格包围源；这里只测有限探针。"""
    delta = np.asarray(points, dtype=float)[None, :, :] - probes[:, None, :]
    squared = np.sum(delta * delta, axis=2)
    nearby = (squared < (1000.0 - 1e-5) ** 2) & (squared > 1e-16)
    angles = np.where(nearby, np.arctan2(delta[:, :, 1], delta[:, :, 0]), 4 * math.pi)
    angles.sort(axis=1)
    counts = np.sum(nearby, axis=1)
    widths = np.diff(angles, axis=1)
    widths = np.where(np.arange(angles.shape[1] - 1)[None, :] < counts[:, None] - 1, widths, 0)
    last = angles[np.arange(len(probes)), np.maximum(0, counts - 1)]
    gaps = np.maximum(np.max(widths, axis=1), angles[:, 0] + 2 * math.pi - last)
    gaps[counts < 3] = 2 * math.pi
    index = int(np.argmax(gaps))
    return float(gaps[index]), tuple(float(x) for x in probes[index])


def specs():
    # 双环包含用户指定的n=10..14、m=6..12、中心0/1；相位只遍历对称基本域。
    for center in (0, 1):
        for n in range(10, 15):
            min_outer = 1800.0 / math.cos(math.pi / n)
            for m in range(6, 13):
                if not 19 <= n + m + center <= 24:
                    continue
                period = 360.0 / math.lcm(n, m)
                for extra in (2.0, 10.0, 25.0, 50.0, 80.0, 120.0, 180.0):
                    outer = min_outer + extra
                    if outer > 2100:
                        continue
                    # 内环R>1000时原点附近只有中心或无测点，不能严格包围。
                    for inner in list(range(500, 1000, 25)) + [995.0]:
                        for fraction in (0.0, 0.125, 0.25, 0.375, 0.5):
                            yield dict(family="two_rings", center=center, outer_n=n, inner_n=m,
                                       outer_r=outer, inner_r=float(inner), phase=period * fraction)
    # 三角壳层保持六重内对称，允许删除中心后以更紧内层弥补；不改原25点。
    for center in (0, 1):
        for n in range(10, 13):
            if n + 12 + center > 24:
                continue
            min_outer = 1800.0 / math.cos(math.pi / n)
            for extra in (2.0, 10.0, 25.0, 50.0, 80.0):
                for inner in (550.0, 600.0, 650.0, 700.0, 750.0, 800.0, 850.0, 900.0):
                    for middle in (1100.0, 1200.0, 1300.0, 1400.0, 1500.0, 1600.0, 1650.0):
                        for fraction in (0.0, 0.25, 0.5):
                            yield dict(family="triangular_shell", center=center, outer_n=n,
                                       outer_r=min_outer + extra, inner_r=inner, middle_r=middle,
                                       phase=360.0 / math.lcm(n, 6) * fraction)


def cost_record(points):
    route = optimize_route((0.0, 0.0), [dict(position=tuple(q)) for q in points])
    length = route_length((0.0, 0.0), route)
    return dict(point_count=len(points), route_m=length,
                route=[job["position"] for job in route],
                discovery_cost_s={str(u): length / 5 + 6 * u * len(points) for u in (5, 10, 20)})


def refinement_specs():
    # 优先检验能直接用默认深度运行的整参数22点；兼查小规模21点邻域。
    for outer in (1850., 1852., 1855., 1856., 1858., 1860., 1865., 1870.):
        for inner in (985., 990., 992., 995., 997.):
            for phase in (0., 1., 2., 3., 4., 5.):
                yield dict(family="two_rings", center=1, outer_n=14, inner_n=7,
                           outer_r=outer, inner_r=inner, phase=phase)
    for n, m in ((12, 8), (13, 7), (14, 6)):
        for extra in (2., 5., 10., 15.):
            for inner in (990., 995., 997., 999.):
                for fraction in (0., 0.25, 0.5):
                    yield dict(family="two_rings", center=1, outer_n=n, inner_n=m,
                               outer_r=1800/math.cos(math.pi/n)+extra, inner_r=inner,
                               phase=360/math.lcm(n,m)*fraction)


def verify_saved_certificate(path):
    """仅从归档叶格重建证书，使用Fraction逐叶复核，不重新生成结论。"""
    raw = json.loads(path.read_text(encoding="utf-8"))
    leaves = tuple(Q4CoverageLeaf(Box(*leaf["bounds"], depth=leaf["depth"], code=leaf["code"]),
                                 leaf["kind"], tuple(leaf["hull_indices"])) for leaf in raw["leaves"])
    cert = Q4CoverageCertificate(raw["domain_radius_m"], raw["reception_radius_m"],
                                tuple(tuple(q) for q in raw["measurements"]), leaves,
                                raw["boxes_visited"], raw["requested_depth"], raw["safety_margin_m"])
    verify_q4_certificate(cert, require_complete=True)
    return dict(path=str(path), verified=True, point_count=len(cert.measurements),
                leaf_count=len(leaves), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def run(output, seconds, max_certificates, refine=False):
    output.mkdir(parents=True, exist_ok=False)
    began = time.perf_counter()
    budget_end = began + seconds
    coarse = polar_probes((200, 450, 700, 950, 1200, 1450, 1700, 1800), 36)
    fine = polar_probes(tuple(range(100, 1801, 100)), 180)
    counters = dict(generated=0, coarse_pass=0, fine_pass=0, full_certificates=0, approved=0)
    qualified, failed_full, nearest = [], [], []

    def dump(name, data):
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    baseline = cost_record(Q4_SYMMETRIC25_ANCHORS)
    baseline["certificate"] = q4_coverage_certificate(Q4_SYMMETRIC25_ANCHORS).to_dict()
    dump("baseline25.json", baseline)
    candidates = list(refinement_specs() if refine else specs())
    # 固定随机次序避免时间上限只覆盖某一种点数/环形；种子和全配置可复现。
    random.Random(2026091305).shuffle(candidates)
    dump("manifest.json", dict(seed=2026091305, seconds=seconds, max_certificates=max_certificates,
                               search_space_size=len(candidates), script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                               refine=refine,
                               numpy_version=np.__version__, coarse_probes=len(coarse), fine_probes=len(fine),
                               note="有限筛选不批准，完整连续覆盖和有理复核才批准"))
    (output / "source_snapshot.py").write_bytes(Path(__file__).read_bytes())
    for spec in candidates:
        if time.perf_counter() >= budget_end or counters["full_certificates"] >= max_certificates:
            break
        counters["generated"] += 1
        points = make_points(spec)
        gap, witness = maximum_gap(points, coarse)
        if gap >= math.pi - 1e-9:
            if len(nearest) < 12 or gap < nearest[-1][0]:
                nearest.append((gap, spec, witness))
                nearest.sort(key=lambda row: row[0])
                nearest = nearest[:12]
            continue
        counters["coarse_pass"] += 1
        gap, witness = maximum_gap(points, fine)
        if gap >= math.pi - 1e-9:
            continue
        counters["fine_pass"] += 1
        counters["full_certificates"] += 1
        cert = q4_coverage_certificate(points)
        record = dict(spec=spec, **cost_record(points), certificate=cert.to_dict(), points=points)
        if cert.complete and cert.rational_verified:
            index = len(qualified)
            record["certificate_file"] = f"certificates/design_{index:03d}.json"
            dump(record["certificate_file"], cert.to_dict(include_leaves=True))
            qualified.append(record)
            counters["approved"] += 1
            dump("qualified.json", qualified)
            print(json.dumps(dict(event="approved", **spec, **{k: record[k] for k in ("point_count", "route_m", "discovery_cost_s")}), ensure_ascii=False), flush=True)
        else:
            record["witness_points"] = cert.witness_points()[:10]
            failed_full.append(record)
    dump("qualified.json", qualified)
    dump("failed_full.json", failed_full)
    dump("nearest_rejections.json", [dict(gap_deg=math.degrees(gap), spec=spec, witness=witness)
                                         for gap, spec, witness in nearest])
    best = {str(u): min(qualified, key=lambda row: row["discovery_cost_s"][str(u)]) if qualified else None
            for u in (5, 10, 20)}
    summary = dict(counters=counters, wall_s=time.perf_counter() - began,
                   search_space_size=len(candidates), exhausted=counters["generated"] == len(candidates),
                   baseline25=baseline, best=best)
    dump("summary.json", summary)
    print(json.dumps(dict(event="complete", counters=counters, wall_s=summary["wall_s"],
                          best_counts={u: record["point_count"] if record else None for u, record in best.items()})), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=PROJECT / "outputs/experiments/q4/discovery_design")
    parser.add_argument("--seconds", type=float, default=900)
    parser.add_argument("--max-certificates", type=int, default=80)
    parser.add_argument("--refine", action="store_true")
    parser.add_argument("--verify", nargs="+", type=Path)
    args = parser.parse_args()
    if args.verify:
        print(json.dumps(dict(certificates=[verify_saved_certificate(path) for path in args.verify]),
                         ensure_ascii=False, indent=2))
    else:
        run(args.output, args.seconds, args.max_certificates, args.refine)
