"""从完整落盘局生成配对表；保留所有失败，不混合不同比较案例集。"""
import argparse
import json
import math
from pathlib import Path
import statistics


def summarize(directory, reference=None):
    rows = json.loads((directory / "results.json").read_text(encoding="utf-8"))
    names = list(dict.fromkeys(r["policy"] for r in rows))
    reference = reference or names[0]
    groups = {name: {r["case"]: r for r in rows if r["policy"] == name} for name in names}
    all_cases = set.union(*(set(g) for g in groups.values()))
    common = set.intersection(*(set(g) for g in groups.values()))
    records = []
    for name, group in groups.items():
        selected = [group[c] for c in sorted(common)]
        times = sorted(r["virtual_time_s"] for r in selected)
        if not times:
            continue
        deltas = [group[c]["virtual_time_s"] - groups[reference][c]["virtual_time_s"] for c in sorted(common)]
        record = dict(policy=name, paired_cases=len(common), recorded_cases=len(group),
            all_success=all(r["success"] for r in selected), failures=sum(not r["success"] for r in selected),
            source_count=sum(r["source_count"] for r in selected), cleared=sum(r["cleared"] for r in selected),
            mean_s=statistics.mean(times), median_s=statistics.median(times), max_s=max(times),
            worst_quarter_mean_s=statistics.mean(times[-math.ceil(len(times) / 4):]),
            mean_per_source_s=statistics.mean(r["average_localization_clear_s"] for r in selected if r["average_localization_clear_s"] is not None),
            total_per_source_s=sum(times) / max(1, sum(r["cleared"] for r in selected)),
            mean_scan_positions=statistics.mean(r["scan_position_count"] for r in selected),
            mean_measures=statistics.mean(r["measure_count"] for r in selected),
            movement_fraction=sum(r["move_s"] for r in selected) / sum(times),
            max_wall_s=max(r["wall_time_s"] for r in selected),
            wins_reference=sum(d < -1e-6 for d in deltas), losses_reference=sum(d > 1e-6 for d in deltas),
            mean_delta_s=statistics.mean(deltas), failed_clears=sum(r["failed_clears"] for r in selected))
        records.append(record)
    result = dict(reference=reference, common_cases=len(common), union_cases=len(all_cases), policies=records,
        interpretation="自建案例的观察结果；尾部为本批最慢四分之一均值，不是总体稀有失败率保证。失败局费用不代表成功完成成本。")
    (directory / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# 配对运行汇总", "", f"参照：{reference}；共同案例 {len(common)} 个，已落盘案例并集 {len(all_cases)} 个。仅共同案例参与比较。", "",
             "| 策略 | 全清局/局数 | 平均总秒 | 最慢总秒 | 最慢四分之一均值 | 逐局平均每源秒 | 快/慢于参照 | 平均扫描点 | 最慢现实秒 |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in records:
        lines.append(f"| {r['policy']} | {r['paired_cases']-r['failures']}/{r['paired_cases']} | {r['mean_s']:.2f} | {r['max_s']:.2f} | {r['worst_quarter_mean_s']:.2f} | {r['mean_per_source_s']:.2f} | {r['wins_reference']}/{r['losses_reference']} | {r['mean_scan_positions']:.2f} | {r['max_wall_s']:.2f} |")
    lines += ["", result["interpretation"], "", "本表的平均总时间不是题面要求的每源平均时间；两者分别列出。位置数量也不等于检测次数。", "", "## 反例及失败", ""]
    for name in names:
        if name == reference:
            continue
        worse = sorted((groups[name][c]["virtual_time_s"] - groups[reference][c]["virtual_time_s"], c) for c in common)
        for delta, c in reversed(worse[-3:]):
            if delta > 1e-6:
                lines.append(f"- {name} / {c}：比参照多 {delta:.2f} 秒。")
        for r in groups[name].values():
            if not r["success"]:
                lines.append(f"- 失败 {name} / {r['case']}：{r['error']}")
    (directory / "COMPARISON.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--reference")
    args = parser.parse_args()
    summarize(args.directory, args.reference)
