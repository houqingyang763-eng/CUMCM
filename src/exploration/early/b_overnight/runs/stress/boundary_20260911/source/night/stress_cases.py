"""少量有区分力的困难场景；真值只传给已审计 runner/q4run 驱动。"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent / "b_adaptive_q3"
sys.path.insert(0, str(BASE))
from simulation import Source, Scenario, noise_deg
from astra_guard import check_cached
from runner import run_case as run_q3, dump
from q4run import run_case as run_q4


def polar(radius, angle):
    a = math.radians(angle)
    p = (radius * math.cos(a), radius * math.sin(a))
    # 只修正三角函数的最后一位舍入，保留半径边界至 1e-9 米。
    norm = math.hypot(*p)
    return tuple(x * radius / max(radius, norm) for x in p)


CIRCLE_1000 = [(1000, 0), (600, 800), (0, 1000), (-600, 800), (-1000, 0),
               (-600, -800), (0, -1000), (600, -800), (800, 600), (-800, 600),
               (-800, -600), (800, -600), (280, 960), (-280, 960),
               (280, -960), (-280, -960)]
SPARSE_10 = [1, 3, 5, 7, 9, 11, 13, 15, 17, 20]


def scene(name, seed, points, noise="biased", orientation=None, radii=None, purpose=""):
    channels = SPARSE_10 if len(points) == 10 else list(range(1, len(points) + 1))
    sources = []
    for i, (channel, p) in enumerate(zip(channels, points)):
        r = 1000.0 if radii is None else radii[i]
        direction = None if orientation is None or i == 0 else orientation(i, p)
        sources.append(Source(channel, tuple(map(float, p)), float(r), direction))
    return Scenario(name, seed, purpose, noise, tuple(sources))


def make_cases():
    boundary16 = [polar(1800, 30 + 360 * i / 16) for i in range(16)]
    boundary10 = [polar(1800, 30 + 36 * i) for i in range(10)]
    ray16 = [(6 + 1793 * i / 15, (-1) ** i * .001) for i in range(16)]
    line10 = [(-1799 + 3598 * i / 9, (-1) ** i * .002) for i in range(10)]
    line16 = [(-1799 + 3598 * i / 15, (-1) ** i * .002) for i in range(16)]
    tight10 = [(-1750 + .01 * math.cos(i), .01 * math.sin(i)) for i in range(10)]
    wrap16 = [polar(100 + 1650 * i / 15, (-1) ** i * .0001) for i in range(16)]
    wrap10 = [polar(900 + 850 * i / 9, (-1) ** i * .0001) for i in range(10)]
    near10 = [(5, 0), (-5, 0), (0, 5), (0, -5), (20, 0), (-20, 0),
              (20.00001, 0), (-20.00001, 0), (5.00001, 0), (-5.00001, 0)]
    radial = lambda i, p: math.degrees(math.atan2(p[1], p[0])) % 360
    q3 = [
        scene("stress_q3_domain1800_16", 71000, boundary16,
              purpose="16源全部在1800米圆周，最小接收半径，角误差取端点"),
        scene("stress_q3_reception1000_10", 71001, CIRCLE_1000[:10], "hashed",
              purpose="10源恰在原点1000米接收边界，覆盖频道20与缺失频道"),
        scene("stress_q3_long_ray_16", 71002, ray16,
              radii=[1000 if i % 2 else 1500 for i in range(16)],
              purpose="16源几乎同方向长串，接收上下界交错，重复角几何"),
        scene("stress_q3_collinear_10", 71003, line10, "hashed",
              purpose="跨原点近共线，10源和逐位置固定散列误差"),
        scene("stress_q3_colocated_16", 71004, [(1750, 0)] * 16,
              purpose="16频道共用完全相同远端位置，各频道误差正负交错"),
        scene("stress_q3_tight_cluster_10", 71005, tight10, "hashed",
              purpose="10源在圆边附近0.02米簇中，各频道独立清除"),
        scene("stress_q3_wrap_zero_16", 71006, wrap16,
              radii=[1500] * 16, purpose="首次方位跨0度且接近舍入边界，上限1500米接收"),
        scene("stress_q3_near_clear_edges_10", 71007, near10, "hashed",
              purpose="5米near与20米清除边界两侧，源数10仍须排除缺失频道"),
    ]
    q4 = [
        scene("stress_q4_outward_boundary_16", 72000, boundary16, orientation=radial,
              purpose="16源中15定向朝外，仅1全向，全部1800边界与最小半径"),
        scene("stress_q4_outward_boundary_10", 72001, boundary10, "hashed", radial,
              purpose="10源中9定向朝外，仅1全向，更多不存在频道需验证"),
        scene("stress_q4_beam_edge_in_16", 72002, CIRCLE_1000, orientation=lambda i, p: (radial(i, p) + 270) % 360,
              purpose="原点恰在15个定向源发射半圆边界且恰为1000米，边界应接收"),
        scene("stress_q4_beam_edge_out_10", 72003, CIRCLE_1000[:10], "hashed",
              lambda i, p: (radial(i, p) + 270.000001) % 360,
              purpose="原点越出发射半圆边界0.000001度，近距离阴性不能删源"),
        scene("stress_q4_colocated_directions_16", 72004, [(1750, 0)] * 16,
              orientation=lambda i, p: (0.0, 90.0, 180.0, 270.0)[i % 4],
              purpose="同一远端位置16频道，15个方向在四个朝向，1全向"),
        scene("stress_q4_collinear_opposite_16", 72005, line16, "hashed",
              lambda i, p: 0.0 if i % 2 else 180.0,
              purpose="近共线长串，15源交错向东/向西，仅1全向"),
        scene("stress_q4_wrap_outward_10", 72006, wrap10,
              orientation=radial, purpose="0度两侧长串、9定向近东向，最小接收半径"),
        scene("stress_q4_near_invisible_10", 72007, near10, "hashed", radial,
              purpose="距离5米仍可因背面无信号；仅1全向，清除不依赖朝向"),
    ]
    return q3, q4


def validate_inputs(scenes):
    checks = []
    for s in scenes:
        assert 10 <= len(s.sources) <= 16
        assert len({x.channel for x in s.sources}) == len(s.sources)
        assert all(1 <= x.channel <= 20 and 1000 <= x.radius <= 1500 for x in s.sources)
        assert all(math.hypot(*x.position) <= 1800 + 1e-8 for x in s.sources)
        for source in s.sources:
            for q in [(0, 0), (1200, 0), (2700, 0), source.position]:
                a = noise_deg(s.seed, s.noise, q, source.channel)
                b = noise_deg(s.seed, s.noise, q, source.channel)
                assert a == b and -1 <= a <= 1
        checks.append(dict(case=s.name, source_count=len(s.sources),
                           directional_count=sum(x.orientation is not None for x in s.sources),
                           max_source_radius_m=max(math.hypot(*x.position) for x in s.sources),
                           input_valid=True, fixed_bounded_noise_checked=True))
    return checks


def summarize(rows):
    groups = {}
    for row in rows:
        groups.setdefault(row["policy"], []).append(row)
    result = {}
    for name, values in groups.items():
        worst = max(values, key=lambda x: x["virtual_time_s"])
        result[name] = dict(runs=len(values), successes=sum(x["success"] for x in values),
                            total_sources=sum(x["source_count"] for x in values),
                            total_cleared=sum(x["cleared"] for x in values),
                            mean_virtual_s=sum(x["virtual_time_s"] for x in values) / len(values),
                            worst_case=worst["case"], worst_virtual_s=worst["virtual_time_s"],
                            max_wall_s=max(x["wall_time_s"] for x in values),
                            fallback_runs=sum(x["fallback"] for x in values),
                            failed_clears=sum(x["failed_clears"] for x in values))
    pairs = []
    cases = {row["case"] for row in rows if row["policy"] in ("completion", "configured")}
    for case in sorted(cases):
        pair = {row["policy"]: row for row in rows if row["case"] == case}
        if "completion" in pair and "configured" in pair:
            a, b = pair["completion"], pair["configured"]
            pairs.append(dict(case=case, completion_s=a["virtual_time_s"], configured_s=b["virtual_time_s"],
                              configured_relative_change=b["virtual_time_s"] / a["virtual_time_s"] - 1))
    return dict(groups=result, paired_q3=pairs,
                failures=[row for row in rows if not row["success"]],
                evidence_scope="预先构造的机制压力检查，不是独立随机样本或失败概率估计")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "runs" / "stress" / "boundary_20260911")
    parser.add_argument("--config", type=Path, default=ROOT / "validation_configs.json")
    args = parser.parse_args()
    check_cached()
    out = args.output.resolve()
    if ROOT / "runs" / "stress" not in out.parents:
        raise ValueError("压力结果必须位于 runs/stress 的新子目录")
    out.mkdir(parents=True, exist_ok=False)
    configs = json.loads(args.config.read_text(encoding="utf-8"))
    q3, q4 = make_cases()
    dump(out / "cases.json", {"q3": [s.to_dict() for s in q3], "q4": [s.to_dict() for s in q4]})
    dump(out / "input_checks.json", validate_inputs(q3 + q4))
    dump(out / "configs.json", configs)
    versions = {}
    for folder, prefix in ((BASE, "base"), (ROOT, "night")):
        for path in folder.glob("*.py"):
            if path.name == "astra_guard.py":
                continue
            data = path.read_bytes()
            relative = f"{prefix}/{path.name}"
            versions[relative] = hashlib.sha256(data).hexdigest()
            target = out / "source" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    manifest = dict(created_at=time.time(), python=sys.version, code_sha256=versions,
                    case_sha256=hashlib.sha256((out / "cases.json").read_bytes()).hexdigest(),
                    policy_protocol={"q3": ["completion", "configured"], "q4": ["directional"]},
                    planned_runs=24, status="running")
    dump(out / "manifest.json", manifest)
    results = []
    try:
        for problem, scenes, policies in [("q3", q3, ["completion", "configured"]), ("q4", q4, ["directional"])]:
            for s in scenes:
                for name in policies:
                    check_cached()
                    trace = out / "actions" / f"{s.name}_{name}.jsonl"
                    result = run_q3(s, name, configs.get(name), trace) if problem == "q3" else run_q4(s, name, trace)
                    results.append(result)
                    dump(out / "results.json", results)
                    dump(out / "summary.json", summarize(results))
                    print(json.dumps({k: result[k] for k in ("case", "policy", "success", "cleared", "source_count",
                                                             "virtual_time_s", "wall_time_s", "fallback", "failed_clears", "error")},
                                     ensure_ascii=False), flush=True)
                    check_cached()
        manifest["status"] = "completed"
    except Exception as exc:
        manifest.update(status="interrupted", exception=str(exc))
        raise
    finally:
        manifest.update(finished_at=time.time(), completed_runs=len(results))
        dump(out / "manifest.json", manifest)


if __name__ == "__main__":
    main()
