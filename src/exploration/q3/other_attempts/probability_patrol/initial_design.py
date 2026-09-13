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
    source_file = OUTPUT / "handoff.json"
    if not source_file.exists():
        source_file = OUTPUT / "coarse.json"
    raw = json.loads(source_file.read_text(encoding="utf-8"))
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


def rotate(pair, angle):
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    return [[float(c * x - s * y), float(s * x + c * y)] for x, y in pair]


def handoff():
    # 均匀先验下任意固定整体旋转等价；30度事先固定，不按开发成绩挑角度。
    # edge组是最小R边缘失配对照，替换近似重复的另一个短基线候选。
    definitions = (("coverage", "coverage30", ((-800, 0), (800, 0))),
                   ("short_start", "short30", ((-150, 0), (600, 0))),
                   ("edge_robustness", "edge30", ((-1100, 0), (1100, 0))))
    xy, radii = sources(200000, seed=SEED + 41)
    selected = []
    for role, name, pair in definitions:
        stats = probability_stats(xy, radii, rotate(pair, 30), True)
        selected.append({"role": role, "name": name, **stats,
                         "initial_move_min": stats["initial_move_s"] / 60})
    result = {"seed": SEED + 41, "samples": 200000, "rotation_deg": 30,
              "basis": "coverage/short candidates from coarse study; third candidate deliberately protects against minimum-R edge prior mismatch; no whole-task time claim",
              "selected": selected}
    (OUTPUT / "handoff.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def sensitivity(n):
    rows = []
    for layout in ("edge", "cluster", "line"):
        xy, radii = sources(n, layout, SEED + 43, "1000")
        px, pr = sources(200000, layout, SEED + 47, "1000")
        for role, pair in (("coverage", ((-800, 0), (800, 0))),
                          ("short_start", ((-150, 0), (600, 0))),
                          ("edge_robustness", ((-1100, 0), (1100, 0)))):
            for angle in (0, 30, 90):
                rp = rotate(pair, angle)
                rows.append({"layout": layout, "role": role, "rotation_deg": angle,
                             "probability": probability_stats(px, pr, rp),
                             "geometry": geometry_stats(rp, xy, radii, "hashed", SEED + 43)})
    result = {"n_per_geometry_case": n, "source_seed": SEED + 43,
              "radius_m": 1000, "rows": rows}
    (OUTPUT / "rotation_sensitivity.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def deterministic_integral(pair, radius=1000, x_steps=100000):
    """独立竖截面中点积分：固定R的圆域内两圆并集/交集面积比例。"""
    x = -1800 + (np.arange(x_steps) + 0.5) * (3600 / x_steps)
    domain_half = np.sqrt(np.maximum(0, 1800 ** 2 - x ** 2))
    intervals = []
    for q in pair:
        dx2 = (x - q[0]) ** 2
        h = np.sqrt(np.maximum(0, radius ** 2 - dx2))
        lo, hi = np.maximum(-domain_half, q[1] - h), np.minimum(domain_half, q[1] + h)
        valid = (dx2 <= radius ** 2) & (hi >= lo)
        intervals.append((lo, hi, valid))
    (a, b, va), (c, d, vb) = intervals
    la, lb = np.where(va, b - a, 0), np.where(vb, d - c, 0)
    both = np.where(va & vb, np.maximum(0, np.minimum(b, d) - np.maximum(a, c)), 0)
    scale = 3600 / x_steps / (math.pi * 1800 ** 2)
    return {"p_discovered": float((la + lb - both).sum() * scale),
            "p_two_detected": float(both.sum() * scale)}


def validate():
    raw = json.loads((OUTPUT / "handoff.json").read_text(encoding="utf-8"))
    results = []
    px, pr = sources(200000, seed=SEED + 53)
    for row in raw["selected"]:
        pair = row["points"]
        # 对R做Gauss-Legendre积分，X做独立竖截面积分。
        nodes, weights = np.polynomial.legendre.leggauss(24)
        ds, bs = [], []
        for node in nodes:
            q = deterministic_integral(pair, 1250 + 250 * node, 20000)
            ds.append(q["p_discovered"])
            bs.append(q["p_two_detected"])
        independent = {"p_discovered": float(np.dot(weights, ds) / 2),
                       "p_two_detected": float(np.dot(weights, bs) / 2)}
        fine_nodes, fine_weights = np.polynomial.legendre.leggauss(48)
        fine_values = [deterministic_integral(pair, 1250 + 250 * node, 40000)
                       for node in fine_nodes]
        fine_integral = {key: float(np.dot(fine_weights, [v[key] for v in fine_values]) / 2)
                         for key in ("p_discovered", "p_two_detected")}
        mc = probability_stats(px, pr, pair, True)
        reversed_stats = probability_stats(px, pr, pair[::-1], True)
        assert abs(mc["p_discovered"] - reversed_stats["p_discovered"]) < 1e-12
        minimum_r = deterministic_integral(pair, 1000)
        assert minimum_r["p_discovered"] <= 2 * (1000 / 1800) ** 2 + 1e-6
        results.append({"role": row["role"], "independent_integral": independent,
                        "finer_integral": fine_integral,
                        "quadrature_refinement_difference": fine_integral["p_discovered"] - independent["p_discovered"],
                        "mc_200k": mc, "minimum_R1000": minimum_r,
                        "mc_minus_integral": mc["p_discovered"] - independent["p_discovered"],
                        "reverse_order_initial_move_min": reversed_stats["initial_move_s"] / 60})
    # 固定位置固定环境，重复读数不改善误差。
    source = Source(1, (300.0, 400.0), 1000.0)
    env = LocalEnvironment(Scenario("repeat_test", SEED, "uniform", "hashed", (source,)))
    action = {"kind": "measure", "channel": 1, "position": (100.0, 0.0)}
    first, second = env.act(action), env.act(action)
    assert first["svd_deg"] == second["svd_deg"]
    result = {"rows": results, "repeat_same_position_same_bearing": True,
              "visit_reverse_same_probabilities": True,
              "R1000_area_upper_bound": 2 * (1000 / 1800) ** 2,
              "all_discovered_upper_bound_N10": (2 * (1000 / 1800) ** 2) ** 10,
              "all_discovered_upper_bound_N16": (2 * (1000 / 1800) ** 2) ** 16}
    (OUTPUT / "validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def figure(selected):
    # 科学示意图：固定R=1250，不把随机半径混画成两个确定圆。
    xy, radii = sources(230, seed=SEED + 71, radius_mode="1250")
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="500" viewBox="0 0 1200 500">',
             '<rect width="1200" height="500" fill="#f8fafc"/>',
             '<style>text{font-family:Arial,"Microsoft YaHei",sans-serif;fill:#172033}</style>',
             '<text x="32" y="30" font-size="19">Two initial locations: discovery and double observation differ</text>',
             '<text x="32" y="54" font-size="13">Illustration only: fixed reception radius 1250 m; source domain radius 1800 m</text>']
    for i, row in enumerate(selected):
        cx, cy, scale = 200 + i * 400, 255, 160 / 1800
        pair = row["points"]
        parts += [f'<defs><clipPath id="clip{i}"><circle cx="{cx}" cy="{cy}" r="160"/></clipPath></defs>',
                  f'<text x="{cx}" y="86" text-anchor="middle" font-size="17">{row["name"]}</text>',
                  f'<circle cx="{cx}" cy="{cy}" r="160" fill="white" stroke="#4b5563"/>',
                  f'<g clip-path="url(#clip{i})">']
        for q in pair:
            parts.append(f'<circle cx="{cx+q[0]*scale:.3f}" cy="{cy-q[1]*scale:.3f}" r="{1250*scale:.3f}" fill="#4f46e5" fill-opacity="0.08" stroke="#6366f1" stroke-dasharray="4 3"/>')
        for p, radius in zip(xy, radii):
            count = sum(math.dist(p, q) <= radius for q in pair)
            color = ("#d97706", "#2563eb", "#7c3aed")[count]
            parts.append(f'<circle cx="{cx+p[0]*scale:.3f}" cy="{cy-p[1]*scale:.3f}" r="2.5" fill="{color}"/>')
        parts.append('</g>')
        route = [(0, 0)] + pair
        points = ' '.join(f'{cx+q[0]*scale:.3f},{cy-q[1]*scale:.3f}' for q in route)
        parts.append(f'<polyline points="{points}" fill="none" stroke="#dc2626" stroke-width="2"/>')
        for j, q in enumerate(pair):
            parts.append(f'<circle cx="{cx+q[0]*scale:.3f}" cy="{cy-q[1]*scale:.3f}" r="5" fill="#111827"/>')
            parts.append(f'<text x="{cx+q[0]*scale+7:.3f}" y="{cy-q[1]*scale-7:.3f}" font-size="13">P{j+1}</text>')
        parts.append(f'<text x="{cx}" y="440" text-anchor="middle" font-size="14">Initial travel: {row["initial_move_min"]:.1f} min + scans: 3.98 min</text>')
    parts.append('<text x="32" y="480" font-size="14">Orange: missed   Blue: one observation   Purple: two observations   Red: initial travel</text></svg>')
    (OUTPUT / "initial_layouts.svg").write_text('\n'.join(parts), encoding="utf-8")


def report():
    h = json.loads((OUTPUT / "handoff.json").read_text(encoding="utf-8"))
    f = json.loads((OUTPUT / "fine.json").read_text(encoding="utf-8"))
    v = json.loads((OUTPUT / "validation.json").read_text(encoding="utf-8"))
    s = json.loads((OUTPUT / "rotation_sensitivity.json").read_text(encoding="utf-8"))
    labels = {"coverage": "覆盖较多", "short_start": "起步较短", "edge_robustness": "边缘失配对照"}
    body = ["# 两个自由初始测点：概率与几何研究", "",
            "本报告只评价初始信息，不代表整局用时或最终策略推荐。真值只在离线采样与核验中使用。", "",
            "## 结论", "",
            "两点起搜可以作为尽早进入清除的开局，但“覆盖较多”不能推出“多数源已精确定位”。大间距两点发现更多、双测少；小间距两点更容易给少数源形成有用交会，但会漏掉边缘。必须依靠沿途补测和有证据的最终查漏闭环。", "",
            "保留三组有区分力的候选交主实验，全部不在原点测量。第三组专门检验最小接收半径和边缘分布失配，替换细筛中与短行程组近似重复的布局。整体30°旋转固定使用，没有根据开发案例成绩挑选角度。", "",
            "## 参数、假设与计算", "",
            "题面事实：目标圆半径1800m；接收半径1000—1500m；移动5m/s；示向误差在±1°内，同地点误差固定；接口保留两位小数。每点20频道全部扫描、按1至20顺序，两次操作200s，切频39s，共239s；这里不跳过已达标频道。", "",
            "工作假设：源位置在圆域内按面积独立均匀分布；各源R独立服从U[1000,1500]，但同一源两次检测共用同一个R。误差比较hashed、固定±1°、zero；不把这些工作误差场称为官方分布。", "",
            "令d₁、d₂为源到两测点的距离，S(d)=clip((1500−d)/500,0,1)，则发现概率p₁=Eₓ[S(min(d₁,d₂))]，双见概率p₂=Eₓ[S(max(d₁,d₂))]。这里先对R解析积分，降低采样方差；不是把两次接收当作独立事件。", "",
            "条件于N个独立同分布源，发现数服从Binomial(N,p₁)，其均值Np₁，全发现概率p₁ᴺ。未知N不强行设为一个值，JSON逐个给出10—16。若空间分布带相关性，p₁ᴺ不再适用，不能照搬。", "",
            "“可直接清除”按公开反馈构造的整个可能区域最小包围圆半径≤20m判断；≤60m只代表中等定位，不保证清除。区域采用±1.00500001°扇区、1500m接收上界、无信号1000m排除，及现有保守外接多边形/网格。所有比例的分母都是全部真源，而非已发现源。", "",
            "## 三组候选", "",
            "发现及双见概率取独立确定性积分；20/60m比例取4000独立真源与真实state反馈交集（hashed误差）。", "",
            "|候选|P₁→P₂坐标/m|初始移动/min|发现概率|双见概率|半径≤20m|半径≤60m|", "|---|---|---:|---:|---:|---:|---:|"]
    for row in h["selected"]:
        role = row["role"]
        geo = next(x["geometry"] for x in f["cases"] if x["role"] == role and x["layout"] == "uniform" and x["radius_mode"] == "uniform" and x["geometry"]["noise"] == "hashed")
        p = next(x["finer_integral"] for x in v["rows"] if x["role"] == role)
        coords = " → ".join(f"({q[0]:.2f},{q[1]:.2f})" for q in row["points"])
        body.append(f"|{row['name']}（{labels[role]}）|{coords}|{row['initial_move_min']:.2f}|{p['p_discovered']:.2%}|{p['p_two_detected']:.2%}|{geo['p_conservative_radius_le_20']:.2%}|{geo['p_conservative_radius_le_60']:.2%}|")
    p = next(x["finer_integral"]["p_discovered"] for x in v["rows"] if x["role"] == "coverage")
    body += ["", "各组均另加3.983分钟双扫；这是初始开销，后续补测、服务和查漏还没有计入。", "",
             f"以coverage30为例，N=13时平均发现{13*p:.2f}个，仍漏{13*(1-p):.2f}个；全发现概率N=10约{p**10:.2%}、N=16约{p**16:.2%}。这直接否定在均匀假设下“两点通常找全”的强猜想，但不否定沿路补测后较快完成整局的可能性。", "",
             "## 先验失配与方向敏感性", "",
             "若所有源恰在1800m边界且R=1000m，测点到原点距离a<800m时一个源也发现不了；a=800m只相切于零面积位置。半径1100m测点对应两个可见边缘弧约占周长32.6%。这不是调参失败，而是几何可达性的限制。", "",
             "|R1000压力情形|布局角度|候选|发现概率|半径≤20m|半径≤60m|", "|---|---:|---|---:|---:|---:|"]
    for row in s["rows"]:
        if row["layout"] == "edge" and row["rotation_deg"] == 30 or row["layout"] == "line" and row["role"] == "short_start":
            body.append(f"|{row['layout']}|{row['rotation_deg']}°|{labels[row['role']]}|{row['probability']['p_discovered']:.2%}|{row['geometry']['p_conservative_radius_le_20']:.2%}|{row['geometry']['p_conservative_radius_le_60']:.2%}|")
    failures = sum(len(x["geometry"]["truth_preservation_failures"]) for x in f["cases"] + s["rows"])
    total = sum(x["geometry"]["n"] for x in f["cases"] + s["rows"])
    body += ["", "edge压力采用半径1790—1800m薄环内随机方向；line为x∈[−1790,1790]、y∈[−3,3]；cluster为x=−1100/0/1100附近三个80m半宽方块的独立混合。它们是明确的敏感性假设，不等同于正式环境或完整实验生成器中的全部情形。", "",
             "纯x轴两测点面对x轴线状目标时可能发现很多，却因接近共线无法定位。固定30°改善该类交会，但代价是某些区域覆盖减少；90°在若干聚集布局上会严重漏检，所以不能称某个角度普遍稳健。", "",
             "## 搜索、验证与边界", "",
             "先以50,000共同X样本筛331组对称/不对称布局；另外对少量候选做真实几何细筛，覆盖附近作局部细化。细筛±780相对±800的概率差很小，主实验保留易解释的±800。有限网格与样本最优不等于数学上的全局最优，也不等于整局最快。", "",
             f"最终几何与旋转检查合计{total:,}个源级双反馈案例，真源被可能区域或包围圆错误排除的记录为{failures}。独立竖截面面积积分与200,000源蒙特卡洛的发现概率偏差最大{100*max(abs(x['mc_minus_integral']) for x in v['rows']):.3f}个百分点；积分分辨率加倍的变化最大{100*max(abs(x['quadrature_refinement_difference']) for x in v['rows']):.4f}个百分点。", "",
             "另核验了交换访问顺序不改变发现/双见概率，改变的是原点到首点的移动时间；同地点重复测量返回相同方向；R1000时任意两圆发现比例不超过2(1000/1800)²≈61.73%的面积上界。", "",
             "小概率事件采用4000样本仍有抽样误差。例如0/4000不是理论零概率证明，单事件95%上界约0.075%；不同布局的不足1个百分点差异不能据此宣称确定胜负。", "",
             "## 文件与复现", "",
             "- `geometry_results/handoff.json`：主实验应读取的三个布局，包含精确坐标、初始移动和N分层。", "- `geometry_results/coarse.json`、`refined.json`：粗筛与真实几何细筛，属于离线诊断记录。", "- `geometry_results/fine.json`：最终三组24种先验/误差组合，含包围圆半径分位数。", "- `geometry_results/rotation_sensitivity.json`：27种非均匀位置与旋转组合。", "- `geometry_results/validation.json`：独立积分、访问顺序、重复测量和面积上界检查。", "- `geometry_results/initial_layouts.svg`：固定R=1250m时的三组几何示意。", "",
             "运行环境需要Python 3.10+及numpy；本次使用Codex bundled Python。可按以下命令复现，除geometry_results与本报告外不修改文件：", "", "```text", "python experiments/b_q3/probability_patrol/initial_design.py --stage all --samples 50000 --geometry-samples 4000", "python experiments/b_q3/probability_patrol/initial_design.py --stage sensitivity --geometry-samples 1200", "python experiments/b_q3/probability_patrol/initial_design.py --stage report", "```", "",
             "事实依据：`problem/B题.md`和`problem/附件2.md`；几何依据：`experiments/b_adaptive_q3/geometry.py`与`state.py`；工作误差场来自`simulation.py`。没有运行官方模拟器。"]
    (OUTPUT.parent / "INITIAL_DESIGN.md").write_text('\n'.join(body) + '\n', encoding="utf-8")
    figure(h["selected"])
    return {"report": "INITIAL_DESIGN.md", "truth_checks": total, "failures": failures}


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
    selected = [{**coverage, "role": "coverage"}, {**localization, "role": "localization"},
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
    parser.add_argument("--stage", choices=("coarse", "fine", "refine", "handoff", "sensitivity", "validate", "report", "all"), default="all")
    parser.add_argument("--samples", type=int, default=50000)
    parser.add_argument("--geometry-samples", type=int, default=1200)
    args = parser.parse_args()
    if args.stage in ("coarse", "all"):
        coarse(args.samples)
    if args.stage in ("refine", "all"):
        refine(args.geometry_samples)
    if args.stage in ("handoff", "all"):
        handoff()
    if args.stage in ("fine", "all"):
        fine(args.geometry_samples)
    if args.stage in ("sensitivity", "all"):
        sensitivity(args.geometry_samples)
    if args.stage in ("validate", "all"):
        validate()
    if args.stage in ("report", "all"):
        report()


if __name__ == "__main__":
    main()
