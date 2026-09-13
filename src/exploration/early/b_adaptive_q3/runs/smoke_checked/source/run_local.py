"""可复现的本地整局实验。没有网络接口或官方模拟器入口。"""
import argparse
import csv
import hashlib
import json
import math
import platform
import time
import traceback
from pathlib import Path

import geometry as g
from policy import BasePolicy, Config
from simulation import LocalEnvironment, Scenario, generate
from state import InformationState, audit_state

ROOT = Path(__file__).resolve().parent


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_case(scenario, config=None, reference_only=False, trace_path=None):
    if any(s.orientation is not None for s in scenario.sources):
        raise ValueError("Q3 策略拒绝定向源：不能用 Q3 的阴性圆盘规则处理 Q4")
    if not 10 <= len(scenario.sources) <= 16:
        raise ValueError("整局实验要求题面规定的 10—16 个源")
    env, state = LocalEnvironment(scenario), InformationState()
    policy = BasePolicy(config, reference_only=reference_only)
    started = time.perf_counter()
    ledger = dict(move_s=0.0, switch_s=0.0, measure_s=0.0, clear_s=0.0)
    rows, error = [], None
    planning_s, checks_s = 0.0, 0.0
    previous, channel = (0.0, 0.0), 1
    try:
        while not state.complete:
            if len(rows) >= 3000:
                raise TimeoutError("动作保护上限，不能当全清成功")
            if time.perf_counter() - started > 1200:
                raise TimeoutError("本地整局现实耗时超过 20 分钟")
            stamp = time.perf_counter()
            action = policy.choose(state)
            planning_s += time.perf_counter() - stamp
            if action is None:
                raise AssertionError("未证明完成却无动作")
            assert g.distance(action["position"], (0, 0)) <= policy.config.domain_radius_m + 1e-6
            response = env.act(action)
            row = dict(step=len(rows) + 1, **action, response=response)
            rows.append(row)
            # 独立按动作流水重算计费，不从 response.costs 累加。
            x, y = action["position"]
            ledger["move_s"] += math.hypot(x - previous[0], y - previous[1]) / 5
            if action["kind"] == "measure":
                ledger["switch_s"] += int(channel != action["channel"])
                ledger["measure_s"] += 5
                channel = action["channel"]
            else:
                ledger["clear_s"] += 5 if response["clear_result"] == "success" else 3
            previous = (x, y)
            assert abs(sum(ledger.values()) - env.virtual_time_s) < 1e-5, "独立计时账不一致"
            stamp = time.perf_counter()
            state.update(action, response)
            audit_state(state, env)
            checks_s += time.perf_counter() - stamp
            if env.virtual_time_s > 100 * 3600:
                raise TimeoutError("超出 100 小时虚拟上限")
    except Exception:
        error = traceback.format_exc()
    elapsed = time.perf_counter() - started
    if trace_path:
        with trace_path.open("w", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    measures = [r for r in rows if r["kind"] == "measure"]
    clears = [r for r in rows if r["kind"] == "clear"]
    result = dict(case=scenario.name, layout=scenario.layout, noise=scenario.noise, seed=scenario.seed,
                  policy="reference" if reference_only else "adaptive", source_count=len(scenario.sources),
                  cleared=len(env.cleared), success=error is None and state.complete,
                  virtual_time_s=env.virtual_time_s, wall_time_s=elapsed,
                  planning_s=planning_s, checks_s=checks_s, actions=len(rows),
                  measure_count=len(measures), scan_position_count=len({tuple(r["position"]) for r in measures}),
                  clear_attempts=len(clears), failed_clears=sum(r["response"]["clear_result"] != "success" for r in clears),
                  fallback=policy.fallback_started,
                  fallback_actions=sum(r["reason"].startswith("fallback") for r in rows),
                  no_signal_count=sum(r["response"]["measure_result"] == "no_signal" for r in measures),
                  error=error, **ledger)
    return result


def percentile(values, fraction):
    xs = sorted(values)
    k = (len(xs) - 1) * fraction
    a, b = math.floor(k), math.ceil(k)
    return xs[a] + (xs[b] - xs[a]) * (k - a)


def report(results, output):
    lines = ["# 第三问本地原型结果", "", "本文件由 run_local.py 生成。自建案例和自建误差场，不是官方成绩；没有稀有失败概率保证。", "",
             "| 策略 | 局数 | 完成且审计通过 | 虚拟均值/秒 | P95/秒 | 最慢/秒 | 现实总耗时/秒 |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for policy in sorted({r["policy"] for r in results}):
        rs = [r for r in results if r["policy"] == policy]
        ts = [r["virtual_time_s"] for r in rs]
        lines.append(f"| {policy} | {len(rs)} | {sum(r['success'] for r in rs)} | {sum(ts)/len(ts):.2f} | {percentile(ts, .95):.2f} | {max(ts):.2f} | {sum(r['wall_time_s'] for r in rs):.2f} |")
    lines += ["", "P95 使用样本分位数线性插值。失败局的时间也保留，失败不能靠缩短时间获益。", "",
              "| 案例 | 策略 | 完成 | 虚拟/秒 | 检测次数 | 检测位置数 | 清除失败次数 | 启用参考完成 | 现实/秒 |",
              "|---|---|---|---:|---:|---:|---:|---|---:|"]
    for r in results:
        lines.append(f"| {r['case']} | {r['policy']} | {r['success']} | {r['virtual_time_s']:.2f} | {r['measure_count']} | {r['scan_position_count']} | {r['failed_clears']} | {r['fallback']} | {r['wall_time_s']:.2f} |")
    lines += ["", "详情见 results.json、results.csv、cases.json、manifest.json 和每局 actions/*.jsonl。",
              "每一步检查真实源仍在保守区域和保留清除格中；检查程序使用真值，策略不接触它。", ""]
    (output / "RESULTS.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["smoke", "development", "holdout"], default="smoke")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--paired-reference", action="store_true")
    parser.add_argument("--reference-only", action="store_true")
    parser.add_argument("--cases", type=Path, help="重放已保存的案例清单")
    parser.add_argument("--config", type=Path, help="重放已保存的策略参数")
    args = parser.parse_args()
    output = args.output.resolve()
    if ROOT not in output.parents:
        raise ValueError("实验产物必须放在本实验目录内")
    output.mkdir(parents=True, exist_ok=False)
    (output / "actions").mkdir()
    (output / "source").mkdir()
    for path in ROOT.glob("*.py"):
        (output / "source" / path.name).write_bytes(path.read_bytes())
    if args.cases:
        scenarios = [Scenario.from_dict(d) for d in json.loads(args.cases.read_text(encoding="utf-8"))]
    elif args.stage == "smoke":
        scenarios = [generate(100 + i, layout, noise) for i, (layout, noise) in enumerate(
            [("uniform", "zero"), ("edge", "biased"), ("cluster", "smooth"), ("line", "hashed")])]
    else:
        base, repeats = (110, 1) if args.stage == "development" else (10010, 2)
        combinations = [(layout, noise) for layout in ("uniform", "edge", "cluster", "line")
                        for noise in ("smooth", "biased", "hashed") for _ in range(repeats)]
        scenarios = [generate(base + i, layout, noise) for i, (layout, noise) in enumerate(combinations)]
    config = Config(**json.loads(args.config.read_text(encoding="utf-8"))) if args.config else Config()
    write_json(output / "cases.json", [s.to_dict() for s in scenarios])
    write_json(output / "config.json", config.to_dict())
    manifest = dict(stage=args.stage, python=platform.python_version(),
                    code_sha256={p.name: digest(p) for p in ROOT.glob("*.py")},
                    case_sha256=digest(output / "cases.json"), config_sha256=digest(output / "config.json"),
                    created_local=time.strftime("%Y-%m-%d %H:%M:%S %z"),
                    assumptions=["自建 Q3 全向源", "空间误差场同点固定", "方向角四舍五入到两位小数",
                                 "smooth/biased/hashed 是测试假设而非官方噪声分布"],
                    paired_reference=args.paired_reference, reference_only=args.reference_only)
    write_json(output / "manifest.json", manifest)
    results = []
    for scenario in scenarios:
        modes = [True] if args.reference_only else ([False, True] if args.paired_reference else [False])
        for reference in modes:
            label = "reference" if reference else "adaptive"
            result = run_case(scenario, config, reference, output / "actions" / f"{scenario.name}_{label}.jsonl")
            results.append(result)
            write_json(output / "results.json", results)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    with (output / "results.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)
    report(results, output)
    if not all(r["success"] for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
