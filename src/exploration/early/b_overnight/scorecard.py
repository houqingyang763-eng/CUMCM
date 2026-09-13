"""按题面逐局 T/清除数重算候选成绩，保留总时间的辅助口径。"""
import json
import math
import statistics
from pathlib import Path
from astra_guard import check_cached

ROOT = Path(__file__).resolve().parent
BATCHES = [
    ("强基础参照", "batch_commitment/independent"),
    ("Q3集中巡查", "q3_sweep_validation"),
    ("Q4网络与联合状态", "q4_integrated_validation"),
    ("Q4集中巡查", "q4_sweep_validation"),
    ("两轮参数的独立核验", "q3_refinement_validation"),
]


def summary(values):
    ordered = sorted(values)
    return dict(mean=statistics.mean(values), median=statistics.median(values), maximum=max(values),
                worst_quarter_mean=statistics.mean(ordered[-math.ceil(len(values) / 4):]))


def evaluate(rows):
    names = list(dict.fromkeys(r["policy"] for r in rows))
    groups = {name: {r["case"]: r for r in rows if r["policy"] == name} for name in names}
    common = sorted(set.intersection(*(set(g) for g in groups.values())))
    if not common:
        raise ValueError("没有共同案例")
    reference = names[0]
    reports = []
    for name in names:
        selected = [groups[name][case] for case in common]
        valid = all(r["success"] and r["cleared"] == r["source_count"] for r in selected)
        report = dict(policy=name, common_cases=len(common), all_cleared=valid)
        if valid:
            values = [r["virtual_time_s"] / r["cleared"] for r in selected]
            report.update(per_source_s=summary(values), total_s=summary([r["virtual_time_s"] for r in selected]),
                          worst_per_source_case=selected[max(range(len(values)), key=lambda i: values[i])]["case"])
        else:
            report.update(per_source_s=None, total_s=None, failures=[r["case"] for r in selected if not r["success"] or r["cleared"] != r["source_count"]])
        reports.append(report)
    return dict(reference=reference, common_cases=len(common), policies=reports)


if __name__ == "__main__":
    check_cached()
    result, lines = [], ["# 按题面平均每源成本重新核对", "",
        "主指标先在每局计算 T/成功清除数，再跨相同案例求均值与本批最慢四分之一。必须全清；不以少清目标换低费用。总时间另列辅助统计，不用总时间的最慢局代替每源时间的最慢局。", "",
        "本文件由 scorecard.py 读取已完成批次生成；不重跑策略、不删除反例。"]
    for title, folder in BATCHES:
        rows = json.loads((ROOT / "runs" / folder / "results.json").read_text(encoding="utf-8"))
        data = evaluate(rows)
        result.append(dict(title=title, directory=folder, **data))
        lines += ["", "## " + title, "", "| 策略 | 全清局 | 每源平均秒 | 每源尾部均值 | 每源最慢秒 | 平均总秒（辅助） |", "|---|---:|---:|---:|---:|---:|"]
        for r in data["policies"]:
            if not r["all_cleared"]:
                lines.append("| " + r["policy"] + " | 未全清 | 不排名 | 不排名 | 不排名 | 不排名 |")
                continue
            p, t = r["per_source_s"], r["total_s"]
            lines.append(f"| {r['policy']} | {r['common_cases']}/{r['common_cases']} | {p['mean']:.2f} | {p['worst_quarter_mean']:.2f} | {p['maximum']:.2f} | {t['mean']:.2f} |")
        lines += ["", "来源：`runs/" + folder + "/results.json`。"]
    lines += ["", "## 影响当前判断的地方", "",
        "- Completion相对强参照的每源均值与尾部更好，但每源最大值略差；不能泛称所有最坏指标改善。",
        "- 联合25点相对原37点的每源均值与尾部明显更好；相对仅25点的每源尾部和最大值略差，尽管失败清除大幅减少。",
        "- 两轮配置历史搜索按总时间优化，不能冒称直接优化了题面每源指标；新筛选入口已显式提供指标选择，历史记录不改。",
        "- 每源平均的平均不是总时间/总源数，二者分别相当于每局等权与每源等权，禁止混写。",
        "- 尾部只是这些自建案例中最慢四分之一，不是总体概率或正式成绩。"]
    (ROOT / "SCORECARD.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (ROOT / "SCORECARD.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(dict(batches=len(result), output="SCORECARD.md", failed_batches=sum(not r["all_cleared"] for b in result for r in b["policies"])) ))
