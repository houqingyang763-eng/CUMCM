"""汇总同案例完整试验，失败局保留，效率比较仅使用双方全清配对。"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics


def summarize(results):
    grouped = defaultdict(list)
    for row in results:
        grouped[row["policy"]].append(row)
    summaries = {}
    for policy, rows in sorted(grouped.items()):
        complete = [r for r in rows if r["success"]]
        summaries[policy] = dict(cases=len(rows), all_clear_cases=len(complete),
            cleared=sum(r["cleared"] for r in rows), source_count=sum(r["source_count"] for r in rows),
            mean_seconds_per_source=(statistics.mean(r["average_localization_clear_s"] for r in complete) if complete else None),
            mean_virtual_s=(statistics.mean(r["virtual_time_s"] for r in complete) if complete else None),
            max_virtual_s=max((r["virtual_time_s"] for r in rows), default=0),
            max_seconds_per_source=max((r["average_localization_clear_s"] for r in complete), default=None),
            mean_move_s=statistics.mean(r["move_s"] for r in rows),
            mean_measure_s=statistics.mean(r["measure_s"] for r in rows),
            mean_switch_s=statistics.mean(r["switch_s"] for r in rows),
            mean_success_clear_s=statistics.mean(r["ledger"]["success_clear_s"] for r in rows),
            mean_failed_clear_s=statistics.mean(r["ledger"]["failed_clear_s"] for r in rows),
            total_failed_clears=sum(r["failed_clears"] for r in rows),
            mean_wall_s=statistics.mean(r["wall_time_s"] for r in rows),
            max_wall_s=max(r["wall_time_s"] for r in rows),
            mean_planning_s=statistics.mean(r["planning_s"] for r in rows),
            failure_cases=[r["case"] for r in rows if not r["success"]])
    pairs = []
    references = [p for p in ("baseline", "joint25") if p in grouped]
    for reference in references:
        reference_rows = {r["case"]: r for r in grouped[reference]}
        for policy, rows in sorted(grouped.items()):
            if policy == reference:
                continue
            compared = []
            for r in rows:
                base = reference_rows.get(r["case"])
                if base and base["success"] and r["success"]:
                    delta = base["virtual_time_s"] - r["virtual_time_s"]
                    compared.append(dict(case=r["case"], saved_s=delta,
                        saved_fraction=delta / base["virtual_time_s"],
                        baseline_s=base["virtual_time_s"], candidate_s=r["virtual_time_s"]))
            pairs.append(dict(reference=reference, policy=policy, paired_all_clear_cases=len(compared),
                mean_saved_s=statistics.mean(r["saved_s"] for r in compared) if compared else None,
                mean_saved_fraction=statistics.mean(r["saved_fraction"] for r in compared) if compared else None,
                regressions=[r for r in compared if r["saved_s"] < -1e-6], cases=compared))
    return dict(policies=summaries, comparisons=pairs,
                metric_note="主指标为每个全清案例的T/N，再跨案例取均值；不以总T/总N替代。任何失败阻止整体更优结论。")


def number(value, digits=2):
    return "—" if value is None else f"{value:.{digits}f}"


def write_report(output):
    output = Path(output)
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    summary = summarize(results)
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# 第四问完整本地试验结果", "",
        "以下是自建混合源案例，布局、源比例、朝向与误差场为团队假设；不是官方成绩或隐藏测试保证。",
        "独立审计逐步检查可见性、示向度误差包络、20米清除、清除不切频、累计计费与真值保留。", "",
        "主指标先要求全清，再计算每局虚拟总秒数/源数，最后跨案例取均值。失败案例保留，不参与速度排名。", "",
        "| 策略 | 全清局/总局 | 清除源/总源 | 平均秒/源 | 平均整局分钟 | 最慢整局分钟 | 平均现实秒 | 最长现实秒 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name, s in summary["policies"].items():
        lines.append(f"| {name} | {s['all_clear_cases']}/{s['cases']} | {s['cleared']}/{s['source_count']} | {number(s['mean_seconds_per_source'])} | {number(s['mean_virtual_s'] / 60 if s['mean_virtual_s'] is not None else None)} | {s['max_virtual_s'] / 60:.2f} | {s['mean_wall_s']:.2f} | {s['max_wall_s']:.2f} |")
    lines += ["", "## 平均成本分解", "", "单位秒/局，移动、检测、切频和清除互不重复。", "",
              "| 策略 | 移动 | 检测 | 切频 | 成功清除 | 失败清除 | 失败清除总次数 |", "|---|---:|---:|---:|---:|---:|---:|"]
    for name, s in summary["policies"].items():
        lines.append(f"| {name} | {s['mean_move_s']:.2f} | {s['mean_measure_s']:.2f} | {s['mean_switch_s']:.2f} | {s['mean_success_clear_s']:.2f} | {s['mean_failed_clear_s']:.2f} | {s['total_failed_clears']} |")
    lines += ["", "## 同案例比较", "", "正数代表相对参照节省；只在双方全清的共同案例上计算。", "",
              "| 参照 | 策略 | 配对全清局 | 平均节省秒 | 平均节省比例 | 退步局 |", "|---|---|---:|---:|---:|---:|"]
    for p in summary["comparisons"]:
        lines.append(f"| {p['reference']} | {p['policy']} | {p['paired_all_clear_cases']} | {number(p['mean_saved_s'])} | {number(100 * p['mean_saved_fraction'] if p['mean_saved_fraction'] is not None else None)}% | {len(p['regressions'])} |")
    lines += ["", "## 逐局结果", "", "| 案例 | 策略 | 全清 | 清除/源数 | 虚拟秒 | 秒/已清源 | 现实秒 | 检测 | 失败清除 |", "|---|---|---|---:|---:|---:|---:|---:|---:|"]
    for r in results:
        lines.append(f"| {r['case']} | {r['policy']} | {r['success']} | {r['cleared']}/{r['source_count']} | {r['virtual_time_s']:.2f} | {number(r['average_localization_clear_s'])} | {r['wall_time_s']:.2f} | {r['measure_count']} | {r['failed_clears']} |")
    failures = [r for r in results if not r["success"]]
    if failures:
        lines += ["", "## 失败记录", ""]
        for r in failures:
            lines += [f"### {r['case']} / {r['policy']}", "", f"失败阶段：{r['error_phase']}", "", "```text", r["error"] or "未全清", "```", ""]
    (output / "RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    print(json.dumps(write_report(parser.parse_args().output), ensure_ascii=False, indent=2))
