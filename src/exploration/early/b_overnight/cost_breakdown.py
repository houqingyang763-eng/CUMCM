"""仅分析已有完整记录的费用组成；不创建环境或运行策略。"""
import hashlib
import json
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parent
KEYS = ("move_s", "measure_s", "switch_s", "clear_s")
INPUTS = {"q3": ROOT / "runs/q3_sweep_validation/results.json",
          "q4": ROOT / "runs/q4_integrated_validation/results.json",
          "official": ROOT / "runs/official_practice/verified_results.json"}


def normalize(row, official=False):
    n = row["official_source_count"] if official else row["cleared"]
    assert n > 0
    assert row["all_cleared_verified"] if official else row["success"]
    assert abs(sum(row[k] for k in KEYS)-row["virtual_time_s"]) < .001
    assert abs(row["measure_s"]-5*row["measure_count"]) < 1e-8
    assert abs(row["clear_s"]-5*n-3*row["failed_clears"]) < 1e-8
    return dict(case=row.get("case", row.get("case_code")), policy=row["policy"], cleared=n,
                total_s=row["virtual_time_s"], per_source_s=row["virtual_time_s"]/n,
                components_s={k: row[k] for k in KEYS},
                components_per_source_s={k: row[k]/n for k in KEYS},
                shares={k: row[k]/row["virtual_time_s"] for k in KEYS},
                move_distance_m=row["move_s"]*5, measure_count=row["measure_count"],
                scan_position_count=row["scan_position_count"], failed_clears=row["failed_clears"])


def aggregate(rows):
    total = sum(r["total_s"] for r in rows)
    return dict(cases=len(rows), sources=sum(r["cleared"] for r in rows),
                mean_total_s=statistics.mean(r["total_s"] for r in rows),
                mean_per_source_s=statistics.mean(r["per_source_s"] for r in rows),
                mean_components_s={k: statistics.mean(r["components_s"][k] for r in rows) for k in KEYS},
                mean_components_per_source_s={k: statistics.mean(r["components_per_source_s"][k] for r in rows) for k in KEYS},
                pooled_cost_shares={k: sum(r["components_s"][k] for r in rows)/total for k in KEYS},
                mean_measure_count=statistics.mean(r["measure_count"] for r in rows),
                mean_scan_position_count=statistics.mean(r["scan_position_count"] for r in rows),
                failed_clears=sum(r["failed_clears"] for r in rows))


def pairs(rows, first, second):
    cases = sorted({r["case"] for r in rows})
    result = []
    for case in cases:
        group = {r["policy"]: r for r in rows if r["case"] == case}
        a, b = group[first], group[second]
        assert a["cleared"] == b["cleared"]
        result.append(dict(case=case, first=first, second=second, cleared=a["cleared"],
             total_delta_s=b["total_s"]-a["total_s"], per_source_delta_s=b["per_source_s"]-a["per_source_s"],
             component_delta_s={k: b["components_s"][k]-a["components_s"][k] for k in KEYS},
             component_per_source_delta_s={k: b["components_per_source_s"][k]-a["components_per_source_s"][k] for k in KEYS},
             measure_delta=b["measure_count"]-a["measure_count"],
             scan_position_delta=b["scan_position_count"]-a["scan_position_count"]))
    return result


def main():
    from astra_guard import check_cached
    check_cached()
    report = dict(source_sha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in INPUTS.values()})
    for problem in ("q3", "q4"):
        rows = [normalize(r) for r in json.loads(INPUTS[problem].read_text(encoding="utf-8"))]
        groups = {p: aggregate([r for r in rows if r["policy"] == p]) for p in sorted({r["policy"] for r in rows})}
        report[problem] = dict(cases=rows, groups=groups)
    report["q3"]["completion_to_sweep"] = pairs(report["q3"]["cases"], "completion", "sweep")
    report["q4"]["directional_to_joint25"] = pairs(report["q4"]["cases"], "directional", "joint25")
    report["q4"]["anchors25_to_joint25"] = pairs(report["q4"]["cases"], "anchors25", "joint25")
    report["official"] = [normalize(r, True) for r in json.loads(INPUTS["official"].read_text(encoding="utf-8"))["cases"]]
    report["metric_definition"] = "primary: equal-weight mean of each case T/cleared; shares: pooled component seconds/pooled total seconds; pair delta: second-first"
    report["script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    out = ROOT / "runs/cost_breakdown"
    out.mkdir(parents=True, exist_ok=True)
    (out / "cost_breakdown.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(dict(q3=report["q3"]["groups"],q4=report["q4"]["groups"],
        worst_q3=max(report["q3"]["completion_to_sweep"],key=lambda r:r["total_delta_s"]),
        official=report["official"]),ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
