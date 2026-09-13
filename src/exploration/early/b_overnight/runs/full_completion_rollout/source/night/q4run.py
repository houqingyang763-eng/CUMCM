"""Q4 自建混合场景完整评估；无网络、无官方模拟器入口。"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import sys
import time
import traceback

from q4 import Q4Config, Q4DirectionalPolicy, Q4InformationState, Q4Policy, Q4ReferencePolicy, orientation_model
from simulation import LocalEnvironment, Scenario, Source, generate
from state import audit_state
from astra_guard import check_cached

ROOT = Path(__file__).resolve().parent


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def generate_q4(seed, layout, noise, direction_mode):
    original = generate(seed, layout, noise)
    rng = random.Random(seed + 970000)
    sources = []
    for i, source in enumerate(original.sources):
        orientation = None
        if i % 3:
            radial = math.degrees(math.atan2(source.position[1], source.position[0]))
            if direction_mode == "random":
                orientation = rng.uniform(0, 360)
            elif direction_mode == "outward":
                orientation = radial % 360
            elif direction_mode == "tangent":
                orientation = (radial + 90) % 360
            elif direction_mode == "aligned":
                orientation = 0.0 if i % 2 else 180.0
            else:
                raise ValueError(direction_mode)
        radius = source.radius if direction_mode == "random" else 1000.0
        sources.append(Source(source.channel, source.position, radius, orientation))
    return Scenario(f"q4_{layout}_{direction_mode}_{noise}_{seed}", seed, f"{layout}_{direction_mode}", noise, tuple(sources))


def audit_orientation(state, env):
    """只在审计器里读取源类型/朝向，策略不能访问这些真值。"""
    for j, source in env.sources.items():
        c = state.channels[j]
        if c.status != "found":
            continue
        omni, intervals = orientation_model(c, source.position)
        if source.orientation is None:
            assert omni, (j, "真实全向源被评分模型判为不可行")
        else:
            angle = source.orientation % 360
            assert any(a - 1e-6 <= theta <= b + 1e-6 for a, b in intervals for theta in (angle, angle - 360, angle + 360)), (j, "真实方向被评分模型排除")


def factory(name):
    classes = {"reference": Q4ReferencePolicy, "q4": Q4Policy, "directional": Q4DirectionalPolicy}
    return classes[name]


def run_case(scene, policy_name, trace_path=None, config=None, policy_factory=None, state_factory=Q4InformationState):
    check_cached()
    if not 10 <= len(scene.sources) <= 16:
        raise ValueError("整局场景要求 10—16 源")
    if not any(s.orientation is None for s in scene.sources) or not any(s.orientation is not None for s in scene.sources):
        raise ValueError("Q4 整局实验使用全向与定向混合源")
    policy, state, env = (policy_factory or factory(policy_name))(config or Q4Config()), state_factory(), LocalEnvironment(scene)
    rows, error = [], None
    ledger = dict(move_s=0.0, switch_s=0.0, measure_s=0.0, clear_s=0.0)
    previous, channel = (0, 0), 1
    started, planning, checking = time.perf_counter(), 0.0, 0.0
    try:
        while not state.complete:
            if len(rows) % 10 == 0:
                check_cached()
            if len(rows) >= 5000 or time.perf_counter() - started > 1200:
                raise TimeoutError("整局动作或现实耗时上限")
            stamp = time.perf_counter()
            action = policy.choose(state)
            planning += time.perf_counter() - stamp
            assert action is not None and math.hypot(*action["position"]) <= policy.config.domain_radius_m + 1e-6
            response = env.act(action)
            rows.append(dict(step=len(rows) + 1, **action, response=response))
            q, j = action["position"], action["channel"]
            ledger["move_s"] += math.hypot(q[0] - previous[0], q[1] - previous[1]) / 5
            if action["kind"] == "measure":
                ledger["switch_s"] += int(j != channel)
                ledger["measure_s"] += 5
                channel = j
            else:
                ledger["clear_s"] += 5 if response["clear_result"] == "success" else 3
            previous = q
            assert abs(sum(ledger.values()) - env.virtual_time_s) < 1e-5
            stamp = time.perf_counter()
            state.update(action, response)
            audit_state(state, env)
            audit_orientation(state, env)
            checking += time.perf_counter() - stamp
            assert env.virtual_time_s <= 100 * 3600
    except Exception:
        error = traceback.format_exc()
    if trace_path:
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        trace_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    measures = [row for row in rows if row["kind"] == "measure"]
    return dict(case=scene.name, seed=scene.seed, layout=scene.layout, noise=scene.noise, policy=policy_name,
                source_count=len(scene.sources), directional_count=sum(s.orientation is not None for s in scene.sources),
                cleared=len(env.cleared), success=error is None and state.complete, error=error,
                cleared_ratio=len(env.cleared) / len(scene.sources),
                average_localization_clear_s=env.virtual_time_s / len(env.cleared) if env.cleared else None,
                virtual_time_s=env.virtual_time_s, wall_time_s=time.perf_counter() - started,
                planning_s=planning, checking_s=checking, actions=len(rows), measure_count=len(measures),
                scan_position_count=len({tuple(row["position"]) for row in measures}),
                failed_clears=sum(row["kind"] == "clear" and row["response"]["clear_result"] != "success" for row in rows),
                no_signal_count=sum(row["response"]["measure_result"] == "no_signal" for row in measures),
                fallback=policy.fallback_started, absence_proofs=state.absence_proofs, **ledger)


def report(results, out):
    lines = ["# 第四问本地开发结果", "", "自建混合源场景；不是官方成绩或未见数据保证。失败局保留。", "",
             "| 场景 | 策略 | 完成/源数 | 虚拟秒 | 移动秒 | 检测数 | 清除失败 | 现实秒 |", "|---|---|---:|---:|---:|---:|---:|---:|"]
    for r in results:
        lines.append(f"| {r['case']} | {r['policy']} | {r['cleared']}/{r['source_count']} ({r['success']}) | {r['virtual_time_s']:.2f} | {r['move_s']:.2f} | {r['measure_count']} | {r['failed_clears']} | {r['wall_time_s']:.2f} |")
    (out / "RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--policies", nargs="+", default=["reference", "q4", "directional"])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--cases", type=Path)
    args = parser.parse_args()
    check_cached()
    out = args.output.resolve()
    if ROOT / "runs" / "q4" not in out.parents:
        raise ValueError("产物只放 runs/q4 子目录")
    out.mkdir(parents=True, exist_ok=False)
    scenes = [Scenario.from_dict(row) for row in json.loads(args.cases.read_text(encoding="utf-8"))] if args.cases else [
        generate_q4(31000, "uniform", "smooth", "random"),
        generate_q4(31001, "edge", "biased", "outward"),
        generate_q4(31002, "edge", "hashed", "tangent"),
        generate_q4(31003, "line", "hashed", "aligned")]
    scenes = scenes[:args.limit] if args.limit else scenes
    dump(out / "cases.json", [scene.to_dict() for scene in scenes])
    dump(out / "config.json", Q4Config().to_dict())
    hashes = {}
    for path in [ROOT / name for name in ("q4.py", "q4run.py", "test_q4.py", "task_cost.py")] + list((ROOT.parent / "b_adaptive_q3").glob("*.py")):
        key = str(path.relative_to(ROOT.parent))
        hashes[key] = hashlib.sha256(path.read_bytes()).hexdigest()
        dest = out / "source" / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(path.read_bytes())
    dump(out / "manifest.json", {"code_sha256": hashes, "policies": args.policies, "python": sys.version,
                                "created_at": time.time(), "purpose": "第四问本地开发完整对照"})
    results = []
    for scene in scenes:
        for name in args.policies:
            check_cached()
            result = run_case(scene, name, out / "actions" / f"{scene.name}_{name}.jsonl")
            results.append(result)
            dump(out / "results.json", results)
            report(results, out)
            print(json.dumps(result, ensure_ascii=False), flush=True)
            if result["error"] and "ASTRA_STOP" in result["error"]:
                raise SystemExit(3)
    if not all(row["success"] for row in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
