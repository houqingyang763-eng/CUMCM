"""两自由初始测点：离线概率与保守反馈几何研究。

真值仅用于离线设计/检验；不由在线策略导入。概率分布均为工作假设。
运行：python initial_design.py --stage all --samples 50000 --geometry-samples 1200
依赖 numpy；几何与公开反馈语义复用本仓库的自建模拟器。
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "experiments" / "b_adaptive_q3"))
import geometry as g
from simulation import LocalEnvironment, Scenario, Source
from state import InformationState

OUTPUT = Path(__file__).resolve().parent / "geometry_results"
DOMAIN_RADIUS = 1800.0
SEED = 260912041


def sources(n, layout="uniform", seed=SEED, radius_mode="uniform"):
    rng = np.random.default_rng(seed)
    angle = rng.uniform(0, 2 * np.pi, n)
    radial = DOMAIN_RADIUS * np.sqrt(rng.random(n))
    if layout == "edge":
        radial = rng.uniform(1790, 1800, n)
    xy = np.column_stack((radial * np.cos(angle), radial * np.sin(angle)))
    if layout == "cluster":
        xy[:, 0] = rng.choice([-1100.0, 0.0, 1100.0], n) + rng.uniform(-80, 80, n)
        xy[:, 1] = rng.uniform(-80, 80, n)
    elif layout == "line":
        xy[:, 0] = rng.uniform(-1790, 1790, n)
        xy[:, 1] = rng.uniform(-3, 3, n)
    elif layout not in ("uniform", "edge"):
        raise ValueError(layout)
    radii = rng.uniform(1000, 1500, n)
    if radius_mode != "uniform":
        radii.fill(float(radius_mode))
    return xy, radii


def probability_stats(points, radii, pair, integrate_uniform_radius=False):
    a, b = [np.asarray(p) for p in pair]
    da, db = points - a, points - b
    ra, rb = np.linalg.norm(da, axis=1), np.linalg.norm(db, axis=1)
    ca, cb = ra <= radii, rb <= radii
    seen, both = ca | cb, ca & cb
    if integrate_uniform_radius:
        # 同一个源只有一个R：先对R解析积分，不能给两次观测重抽R。
        seen = np.clip((1500 - np.minimum(ra, rb)) / 500, 0, 1)
        both = np.clip((1500 - np.maximum(ra, rb)) / 500, 0, 1)
    cross = np.abs(da[:, 0] * db[:, 1] - da[:, 1] * db[:, 0])
    sine = cross / np.maximum(ra * rb, 1e-12)
    # 仅描述交会角，不能据此宣布定位半径达标。
    double_good_angle = both * (sine >= math.sin(math.radians(30)))
    travel = (np.linalg.norm(a) + np.linalg.norm(b - a)) / 5
    p = float(seen.mean())
    return {
        "points": [list(map(float, a)), list(map(float, b))],
        "p_discovered": p,
        "radius_integrated_analytically": integrate_uniform_radius,
        "p_two_detected": float(both.mean()),
        "p_two_directions_angle_30_150": float(double_good_angle.mean()),
        "initial_move_s": float(travel),
        "initial_20_channel_scan_s": 239.0,
        "initial_full_scan_time_min": float((travel + 239) / 60),
        "per_n": {str(n): {"expected_discovered": n * p,
                             "expected_undiscovered": n * (1 - p),
                             "p_all_discovered_iid": p ** n}
                  for n in range(10, 17)},
    }


def candidate_pairs():
    pairs = []
    for a in range(100, 1001, 50):
        pairs.append((f"symmetric_{a}", ((-float(a), 0.0), (float(a), 0.0))))
    radii = (150, 300, 450, 600, 750, 900, 1050, 1200)
    for a in radii:
        for b in radii:
            for theta in (0, 30, 60, 90, 120):
                if a == b and theta == 0:
                    continue
                q = (b * math.cos(math.radians(theta)), b * math.sin(math.radians(theta)))
                pairs.append((f"r{a}_{b}_turn{theta}", ((-float(a), 0.0), q)))
    return pairs


def coarse(n):
    xy, radii = sources(n)
    rows = [{"name": name, **probability_stats(xy, radii, pair, True)}
            for name, pair in candidate_pairs()]
    rows.sort(key=lambda r: -r["p_discovered"])
    # 三种不同目的的入口；不是宣称某个多目标加权值最优。
    coverage = rows[0]
    angle = max(rows, key=lambda r: r["p_two_directions_angle_30_150"])
    # 低行程方案的明确筛选约束：初始移动<=3min，保证与其余方案有差别。
    short = max((r for r in rows if r["initial_move_s"] <= 180.00001),
                key=lambda r: r["p_discovered"])
    selected = []
    for role, row in (("coverage", coverage), ("cross_angle", angle), ("short_start", short)):
        selected.append({"role": role, **row})
    convergence = []
    for sample_n in (10000, n, 200000):
        cx, cr = sources(sample_n, seed=SEED + 7)
        convergence.append({"n": sample_n,
                            "statistics": [{"role": r["role"],
                                            **probability_stats(cx, cr, r["points"], True)}
                                           for r in selected]})
    result = {"seed": SEED, "samples": n, "domain_radius_m": DOMAIN_RADIUS,
              "model": "iid area-uniform source positions; iid per-source R~U[1000,1500] fixed across both observations",
              "candidate_count": len(rows), "selected": selected,
              "convergence_independent_seed": convergence, "all_candidates": rows}
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "coarse.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"coarse_selected": selected}, ensure_ascii=False), flush=True)
    return result


def geometry_stats(pair, points, radii, noise="hashed", seed=SEED):
    seen_radii, double_radii = [], []
    seen_count = double_count = radius20 = radius60 = two_direction_count = 0
    truth_failures = []
    for i, (point, radius) in enumerate(zip(points, radii)):
        source = Source(1, tuple(map(float, point)), float(radius))
        env = LocalEnvironment(Scenario(f"offline_{i}", seed + 104729 * i, "offline", noise, (source,)))
        state = InformationState()
        responses = []
        for q in pair:
            action = {"kind": "measure", "channel": 1, "position": tuple(q)}
            response = env.act(action)
            responses.append(response["measure_result"])
            state.update(action, response)
        c = state.channels[1]
        if c.status != "found":
            continue
        seen_count += 1
        center, r = c.circle()
        seen_radii.append(r)
        if not c.compatible(source.position) or g.distance(center, source.position) > r + 1e-5:
            truth_failures.append(i)
        if responses.count("direction") == 2:
            two_direction_count += 1
        if "no_signal" not in responses:
            double_count += 1
            double_radii.append(r)
        radius20 += r <= 20
        radius60 += r <= 60
    n = len(points)
    def quantiles(values):
        return {str(q): float(np.quantile(values, q)) for q in (0.1, 0.25, 0.5, 0.75, 0.9, 0.99)} if values else {}
    return {"n": n, "noise": noise, "p_discovered": seen_count / n,
            "p_two_detected": double_count / n, "p_two_direction_feedbacks": two_direction_count / n,
            "p_conservative_radius_le_20": radius20 / n,
            "p_conservative_radius_le_60": radius60 / n,
            "radius_m_quantiles_given_discovered": quantiles(seen_radii),
            "radius_m_quantiles_given_two_detected": quantiles(double_radii),
            "truth_preservation_failures": truth_failures}


def fine(n):
    raw = json.loads((OUTPUT / "coarse.json").read_text(encoding="utf-8"))
    result = {"seed": SEED + 11, "n_per_geometry_case": n, "cases": []}
    # 200k用于发现概率；n用于较慢的真实保守反馈几何。
    for layout, radius_mode in (("uniform", "uniform"), ("uniform", "1000"),
                                 ("uniform", "1500"), ("edge", "1000"),
                                 ("cluster", "uniform"), ("line", "1000")):
        xy, radii = sources(n, layout, SEED + 11, radius_mode)
        px, pr = sources(200000, layout, SEED + 17, radius_mode)
        for selected in raw["selected"]:
            pair = selected["points"]
            for noise in (("hashed", "biased", "zero") if layout == "uniform" and radius_mode == "uniform" else ("hashed",)):
                started = time.monotonic()
                row = {"role": selected["role"], "name": selected["name"],
                       "points": pair, "layout": layout, "radius_mode": radius_mode,
                       "probability_200k": probability_stats(px, pr, pair, radius_mode == "uniform"),
                       "geometry": geometry_stats(pair, xy, radii, noise, SEED + 11)}
                row["wall_s"] = time.monotonic() - started
                result["cases"].append(row)
                (OUTPUT / "fine.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps(row, ensure_ascii=False), flush=True)
    return result


def refine(n):
    """少量候选做实际几何细筛；有意义的定位概率，不用交会角代理代替。"""
    raw = json.loads((OUTPUT / "coarse.json").read_text(encoding="utf-8"))
    top = sorted(raw["all_candidates"], key=lambda r: -r["p_two_directions_angle_30_150"])[:24]
    extra = [r for r in raw["all_candidates"] if r["name"].startswith("symmetric")]
    candidates = {r["name"]: r for r in top + extra + raw["selected"]}
    xy, radii = sources(n, seed=SEED + 31)
    rows = []
    for row in candidates.values():
        result = {**row, "geometry": geometry_stats(row["points"], xy, radii, "hashed", SEED + 31)}
        rows.append(result)
    rows.sort(key=lambda r: (-r["geometry"]["p_conservative_radius_le_20"],
                              -r["geometry"]["p_conservative_radius_le_60"], r["initial_move_s"]))
    # 局部细化覆盖最大候选，以独立200k X和R解析积分减少粗筛方差。
    px, pr = sources(200000, seed=SEED + 37)
    center = raw["selected"][0]["points"]
    cover_rows = []
    for a in np.arange(abs(center[0][0]) - 100, abs(center[0][0]) + 101, 20):
        for b in np.arange(abs(center[1][0]) - 100, abs(center[1][0]) + 101, 20):
            pair = ((-float(a), 0.0), (float(b), 0.0))
            cover_rows.append({"name": f"refined_{a:g}_{b:g}", **probability_stats(px, pr, pair, True)})
    coverage = max(cover_rows, key=lambda r: r["p_discovered"])
    coverage["geometry"] = geometry_stats(coverage["points"], xy, radii, "hashed", SEED + 31)
    localization = rows[0]
    short = next(r for r in raw["selected"] if r["role"] == "short_start")
    short["geometry"] = geometry_stats(short["points"], xy, radii, "hashed", SEED + 31)
    selected = [{"role": "coverage", **coverage}, {"role": "localization", **localization},
                {**short, "role": "short_start"}]
    for row in selected:
        row["initial_move_min"] = row["initial_move_s"] / 60
    result = {"n_per_geometric_layout": n, "source_seed": SEED + 31,
              "geometry_candidates": len(rows), "coverage_fine_candidates": len(cover_rows),
              "selection": "coverage=max p(discovered); localization=max p(radius<=20), then p(radius<=60); short=max p(discovered) subject to initial movement<=180s",
              "selected": selected, "geometry_all": rows, "coverage_fine_all": cover_rows}
    (OUTPUT / "refined.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    # 最终fine阶段改为使用这三组；保留粗筛原始结果。
    print(json.dumps({"refined_selected": selected}, ensure_ascii=False), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("coarse", "fine", "refine", "all"), default="all")
    parser.add_argument("--samples", type=int, default=50000)
    parser.add_argument("--geometry-samples", type=int, default=1200)
    args = parser.parse_args()
    if args.stage in ("coarse", "all"):
        coarse(args.samples)
    if args.stage in ("refine", "all"):
        refine(args.geometry_samples)
    if args.stage in ("fine", "all"):
        fine(args.geometry_samples)


if __name__ == "__main__":
    main()
