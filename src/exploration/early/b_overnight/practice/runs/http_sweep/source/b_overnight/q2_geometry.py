"""Q1/Q2 的可复算几何；只读冻结底座，不接模拟器、不读取真值。"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time

BASE = Path(__file__).resolve().parents[1] / "b_adaptive_q3"
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
import geometry as g


def wedge_with_error(poly, position, bearing, error_deg=g.ANGLE_ERROR):
    """误差角小于 90 度时，以两个半平面表示有向射线扇形。"""
    if not 0 <= error_deg < 90:
        raise ValueError("只支持 [0,90) 度的半张角")
    lo, hi = g.unit(bearing - error_deg), g.unit(bearing + error_deg)
    nlo, nhi = (lo[1], -lo[0]), (-hi[1], hi[0])
    result = g.clip(g.clip(poly, nlo, g.dot(nlo, position)),
                    nhi, g.dot(nhi, position))
    if error_deg == 0:
        front = g.mul(g.unit(bearing), -1)
        result = g.clip(result, front, g.dot(front, position))
    return result


def bearing_halfplanes(position, bearing, error_deg=1.0):
    if not 0 <= error_deg < 90:
        raise ValueError("只支持 [0,90) 度的半张角")
    lo, hi = g.unit(bearing - error_deg), g.unit(bearing + error_deg)
    rows = [(n, g.dot(n, position)) for n in ((lo[1], -lo[0]), (-hi[1], hi[0]))]
    if error_deg == 0:
        front = g.mul(g.unit(bearing), -1)
        rows.append((front, g.dot(front, position)))
    return rows


def halfplane_region(halfplanes, tolerance=1e-7):
    """小规模 O(m^3) 枚举；区分空、无界、点、线段、多边形。

    不用任意大边框把无界区域伪装成有限区域。浮点退化判别受 tolerance
    和 1e-12 平行阈值限制；其用途是说明 Q1 算法与核验正常尺度案例。
    """
    rows = []
    for normal, bound in halfplanes:
        norm = math.hypot(*normal)
        if norm == 0:
            if bound < -tolerance:
                return {"kind": "empty", "vertices": [], "witness": None}
            continue
        rows.append((g.mul(normal, 1 / norm), bound / norm))
    feasible = lambda p: all(g.dot(n, p) <= b + tolerance for n, b in rows)
    trials = [(0.0, 0.0)] + [g.mul(n, b) for n, b in rows]
    vertices = []
    for i, (a, ba) in enumerate(rows):
        for b, bb in rows[i + 1:]:
            det = g.cross(a, b)
            if abs(det) <= 1e-12:
                continue
            p = ((ba * b[1] - bb * a[1]) / det,
                 (a[0] * bb - b[0] * ba) / det)
            if feasible(p):
                vertices.append(p)
    trials += vertices
    witness = next((p for p in trials if feasible(p)), None)
    if witness is None:
        return {"kind": "empty", "vertices": [], "witness": None}
    directions = [(1.0, 0.0)] if not rows else [
        v for n, _ in rows for v in ((n[1], -n[0]), (-n[1], n[0]))]
    ray = next((d for d in directions
                if all(g.dot(n, d) <= 1e-12 for n, _ in rows)), None)
    if ray is not None:
        return {"kind": "unbounded", "vertices": g.hull(vertices),
                "witness": witness, "recession_direction": ray}
    unique = []
    for p in sorted(vertices):
        if not any(g.distance(p, q) <= tolerance for q in unique):
            unique.append(p)
    vertices = g.hull(unique)
    kind = "point" if len(vertices) == 1 else "segment" if len(vertices) == 2 else "polygon"
    return {"kind": kind, "vertices": vertices, "witness": witness}


def polygon_diameter(vertices):
    if not vertices:
        raise ValueError("空集合不定义定位区域直径")
    pairs = [(a, b) for i, a in enumerate(vertices) for b in vertices[i:]]
    pair = max(pairs, key=lambda ab: g.distance(*ab))
    return g.distance(*pair), pair


def first_region(position, bearing, sides=360, error_deg=g.ANGLE_ERROR):
    """首次 direction 反馈的凸外包；不扣除 5 米近场孔，属于保守外包。"""
    poly = wedge_with_error(g.outer_disk((0, 0), 1800, sides),
                            position, bearing, error_deg)
    return g.intersect_disk_outer(poly, position, 1500, sides)


def candidate_region_1000(poly, radius=1000.0, sides=128):
    """交圆盘的内近似，便于显示候选域；最终仍逐点验真实圆盘约束。"""
    if not poly:
        raise ValueError("候选区域依赖非空可能源区域")
    apothem = radius * math.cos(math.pi / sides) - 1e-5
    region = g.outer_disk(poly[0], apothem, sides)
    for p in poly:
        for i in range(sides):
            n = g.unit(i * 360 / sides)
            region = g.clip(region, n, g.dot(n, p) + apothem)
            if not region:
                return []
    return region


def reception_certificate(poly, q, successful_positions=(), min_radius=1000.0):
    """全向源的可靠接收证明，利用所有既往成功接收点。

    R >= max(1000, max_i ||s-p_i||)。将不能由历史距离支配的残余区域
    K ∩ {||q-s|| >= ||p_i-s||, all i} 保守裁剪出来；它若完全位于
    B(q,1000) 内，则 K 中每个源均保证被 q 接收。方向/near 都算成功。
    poly 必须是包含所有相容源位置的凸多边形（点和线段也可）。
    本函数对第四问只证明距离条件；不能证明未知定向角覆盖。
    """
    if not poly:
        raise ValueError("不能用空几何状态证明接收")
    q = tuple(q)
    successful_positions = [tuple(p) for p in successful_positions]
    if q in successful_positions:
        return {"guaranteed": True, "reason": "previous_success_position",
                "residual_vertices": [], "residual_radius_m": 0.0}
    # 以 q 为局部原点，避免大坐标平方差消去；clip 额外向外扩张 EPS。
    residual = [g.sub(s, q) for s in poly]
    for p in successful_positions:
        n = g.sub(q, p)
        residual = g.clip(residual, n, -0.5 * g.dot(n, n))
        if not residual:
            return {"guaranteed": True, "reason": "history_dominates_everywhere",
                    "residual_vertices": [], "residual_radius_m": 0.0}
    residual_radius = max(math.hypot(*s) for s in residual)
    return {"guaranteed": residual_radius <= min_radius - 1e-6,
            "reason": "residual_inside_minimum_radius" if residual_radius <= min_radius - 1e-6
                      else "no_certificate",
            "residual_vertices": [g.add(s, q) for s in residual],
            "residual_radius_m": residual_radius}


def guaranteed_reception(poly, q, successful_positions=(), min_radius=1000.0):
    """适合 Q3 选点调用的布尔入口；False 仅指本外包未能证明。"""
    return reception_certificate(poly, q, successful_positions, min_radius)["guaranteed"]


def posterior_radius_bound(poly, q, bin_width_deg=1.0, error_deg=g.ANGLE_ERROR):
    """覆盖连续第二次读数的保守上界，非仅取几个噪声值。

    把 [0,360) 分成等宽箱；箱内任一读数的误差扇形包含于中心的
    ±(error+半箱宽) 扇形。每个非空交集计算包围圆，最大半径构成
    方向分支上界；near 分支由 q 的 5 米圆覆盖。调用者负责可靠接收。
    未利用第二次接收的 1500 米约束，故依旧保守。
    """
    if not 0 < bin_width_deg < 2 * (90 - error_deg):
        raise ValueError("分箱宽度须为正，且扩张后的扇形半张角小于90度")
    count = math.ceil(360 / bin_width_deg)
    width = 360 / count
    worst = {"radius_m": 5.0, "bin_center_deg": None, "center": tuple(q),
             "vertices": []}
    nonempty = 0
    for k in range(count):
        beta = (k + 0.5) * width
        post = wedge_with_error(poly, q, beta, error_deg + width / 2)
        if not post:
            continue
        nonempty += 1
        center, radius = g.enclosing_circle(post)
        if radius > worst["radius_m"]:
            worst = {"radius_m": radius, "bin_center_deg": beta,
                     "center": center, "vertices": post}
    worst.update(bin_width_deg=width, nonempty_bins=nonempty)
    return worst


def indistinguishable_pair(q, center=(1450.0, 0.0), length=50.0):
    """可靠二次接收策略类的反例：两点位于同一条第二测点射线上。"""
    d = g.sub(center, q)
    norm = math.hypot(*d)
    if norm == 0:
        raise ValueError("反例中心不能等于第二测点")
    u = g.mul(d, 1 / norm)
    pair = [g.add(center, g.mul(u, t)) for t in (-length / 2, length / 2)]
    first_angles = [math.degrees(math.atan2(s[1], s[0])) for s in pair]
    beta = math.degrees(math.atan2(d[1], d[0])) % 360
    return {"q": tuple(q), "sources": pair, "separation_m": g.distance(*pair),
            "first_reading_deg": 0.0, "first_true_angles_deg": first_angles,
            "second_true_angle_deg": beta, "second_reading_deg": round(beta, 2) % 360,
            "first_distances_m": [math.hypot(*s) for s in pair],
            "second_distances_m": [g.distance(q, s) for s in pair],
            "witness_radius_m": 1500.0}


def universal_two_measurement_counterexample(q):
    """任意第二点的不可区分世界：首次原点读 0 度，不能保证一次清除。

    这不是对 q 网格的结论；公式涵盖任意有限 q。详见 Q1_Q2.md 的证明。
    两个世界可以有不同的未知接收半径，这是题目允许的环境不确定性。
    """
    if not all(math.isfinite(v) for v in q):
        raise ValueError("坐标必须有限")
    if g.distance(q, (50.0, 0.0)) > 1000:
        sources = [(6.0, 0.0), (50.0, 0.0)] if q[0] >= 50 else [(50.0, 0.0), (100.0, 0.0)]
        return {"q": tuple(q), "sources": sources, "radii_m": [1000.0, 1000.0],
                "separation_m": g.distance(*sources), "first_reading_deg": 0.0,
                "first_true_angles_deg": [0.0, 0.0], "second_outcome": "no_signal",
                "first_distances_m": [math.hypot(*s) for s in sources],
                "second_distances_m": [g.distance(s, q) for s in sources],
                "case": "outside_near_source_reception_disk"}
    result = indistinguishable_pair(q)
    d = g.distance(q, (1450.0, 0.0))
    if d <= 1475:
        result.update(second_outcome="direction", radii_m=[1500.0, 1500.0],
                      case="same_second_ray")
    else:
        result.update(second_outcome="no_signal", radii_m=result["first_distances_m"],
                      case="range_ambiguity_after_first_reception")
        # 无信号分支不返回第二次示向度，删除避免把未测量量误当反馈。
        result.pop("second_reading_deg")
        result.pop("second_true_angle_deg")
    result.pop("witness_radius_m")
    return result


def _guard():
    import subprocess
    subprocess.run([sys.executable, str(Path(__file__).with_name("astra_guard.py")), "check"],
                   cwd=Path(__file__).resolve().parents[2], check=True,
                   stdout=subprocess.DEVNULL)


def run_demo(output, bin_width_deg=1.0):
    _guard()
    start = time.perf_counter()
    p = (0.0, 0.0)
    poly = first_region(p, 0.0)
    c1000 = candidate_region_1000(poly)
    candidates = [(float(x), float(y)) for x in range(100, 1001, 100)
                  for y in range(100, 901, 100)]
    candidates += [(750.0, 600.0), (500.0, 800.0), (650.0, 750.0)]
    candidates = list(dict.fromkeys(candidates))
    rows = []
    for q in candidates:
        certificate = reception_certificate(poly, q, [p])
        if not certificate["guaranteed"]:
            continue
        _guard()
        bound = posterior_radius_bound(poly, q, bin_width_deg)
        rows.append({"q": q, "in_C1000": max(g.distance(q, s) for s in poly) <= 1000,
                     "history_reception_certificate": certificate,
                     "worst_radius_upper_m": bound["radius_m"],
                     "worst_bin_center_deg": bound["bin_center_deg"],
                     "move_and_measure_s": g.distance(p, q) / 5 + 5,
                     "bin_width_deg": bound["bin_width_deg"]})
    # 保留移动与几何的非支配候选，不擅自给秒与米加固定权重。
    rows.sort(key=lambda row: row["worst_radius_upper_m"])
    best = rows[0]
    pareto = [row for row in rows if not any(
        other["worst_radius_upper_m"] <= row["worst_radius_upper_m"]
        and other["move_and_measure_s"] <= row["move_and_measure_s"]
        and (other["worst_radius_upper_m"] < row["worst_radius_upper_m"]
             or other["move_and_measure_s"] < row["move_and_measure_s"])
        for other in rows)]
    fine = []
    for q in dict.fromkeys([tuple(best["q"]), (750.0, 600.0), (500.0, 800.0)]):
        _guard()
        bound = posterior_radius_bound(poly, q, 0.25)
        fine.append({"q": q, "worst_radius_upper_m": bound["radius_m"],
                     "bin_width_deg": bound["bin_width_deg"],
                     "counterexample": indistinguishable_pair(q)})
    result = {"schema": "q1_q2_geometry_v1", "units": "m,degree,s",
              "input": {"first_position": p, "first_bearing_deg": 0.0,
                        "error_half_width_deg": g.ANGLE_ERROR, "disk_sides": 360,
                        "candidate_inner_sides": 128},
              "source_outer_polygon": poly, "C1000_inner_polygon": c1000,
              "candidates": rows, "best_geometry": best, "move_geometry_pareto": pareto,
              "fine_bounds": fine,
              "universal_counterexample_examples": [universal_two_measurement_counterexample(q)
                    for q in [(900, 400), (1500, 0), (-1000, 0), (0, 500)]],
              "equilateral_example": {"side_m": 40, "diameter_circle_radius_m": 20,
                                      "minimum_enclosing_radius_m": 40 / math.sqrt(3)},
              "elapsed_s": time.perf_counter() - start,
              "source_sha256": {str(path.resolve().relative_to(Path(__file__).resolve().parents[2])):
                  hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in (Path(__file__), Path(__file__).with_name("test_q2_geometry.py"),
                               BASE / "geometry.py", Path("problem/B题.md"), Path("problem/附件2.md"))},
              "limitations": ["自主推导和本地几何计算，非官方模拟器结果",
                               "离散第二测点候选，不声明全局最优",
                               "角度分箱给连续读数上界，未把噪声设为随机分布",
                               "移动与定位尺度分别列出，不声明时间最优"]}
    output.mkdir(parents=True, exist_ok=True)
    (output / "geometry_results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"candidate_count": len(rows), "best_q": best["q"],
                      "best_upper_m": best["worst_radius_upper_m"],
                      "pareto_count": len(pareto), "fine": fine,
                      "elapsed_s": result["elapsed_s"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("experiments/b_overnight/runs/q2"))
    parser.add_argument("--bin-width", type=float, default=1.0)
    args = parser.parse_args()
    run_demo(args.output, args.bin_width)
