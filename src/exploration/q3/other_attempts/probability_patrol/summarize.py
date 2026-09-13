"""从冻结实验日志生成配对统计与可分享图；不运行或修改策略。"""
import csv
import argparse
import json
import math
from pathlib import Path
import random
import statistics as st

HERE = Path(__file__).resolve().parent
OUT = HERE / "analysis"


def read(folder, file="results.json"):
    return json.loads((HERE / "runs" / folder / file).read_text(encoding="utf-8"))


def quantile(xs, p):
    ordered = sorted(xs)
    index = p * (len(xs) - 1)
    lo, hi = math.floor(index), math.ceil(index)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (index - lo)


def compare(base_folder, new_folder, seed=260912101):
    base, new = read(base_folder), read(new_folder)
    b = {x["case"]: x for x in base}
    assert set(b) == {x["case"] for x in new}
    assert all(x["success"] for x in base + new)
    pairs = []
    for x in new:
        y = b[x["case"]]
        pairs.append({"case": x["case"], "layout": x["layout"], "noise": x["noise"],
                      "n": x["real_n"], "baseline_min": y["total_s"] / 60,
                      "new_min": x["total_s"] / 60, "saving_min": (y["total_s"] - x["total_s"]) / 60,
                      "baseline_per_source_s": y["per_source_s"], "new_per_source_s": x["per_source_s"]})
    groups = {}
    for row in pairs:
        groups.setdefault(row["layout"], []).append(row["saving_min"])
    rng = random.Random(seed)
    boot = []
    for _ in range(10000):
        sample = [rng.choice(group) for group in groups.values() for __ in group]
        boot.append(st.mean(sample))
    by_layout = []
    for layout in groups:
        rows = [x for x in pairs if x["layout"] == layout]
        by_layout.append({"layout": layout, "cases": len(rows),
                          **{key: st.mean(r[key] for r in rows) for key in
                             ("baseline_min", "new_min", "saving_min", "baseline_per_source_s", "new_per_source_s")}})
    components = []
    for key in ("move_s", "measure_s", "switch_s", "success_clear_s", "fail_clear_s"):
        a, c = st.mean(x[key] for x in base)/60, st.mean(x[key] for x in new)/60
        components.append({"component": key, "baseline_min": a, "new_min": c, "saving_min": a-c})
    result = {"cases": len(pairs), "baseline": base_folder, "candidate": new_folder,
              "baseline_min": st.mean(p["baseline_min"] for p in pairs),
              "new_min": st.mean(p["new_min"] for p in pairs),
              "saving_min": st.mean(p["saving_min"] for p in pairs),
              "saving_ci95_stratified_bootstrap_min": [quantile(boot, .025), quantile(boot, .975)],
              "bootstrap": {"replicates": 10000, "seed": seed, "strata": "layout", "unit": "paired case",
                            "limitation": "固定实验布局权重下的经验区间，不是官方分布或小概率最坏保证"},
              "wins": sum(p["saving_min"] > 1e-8 for p in pairs),
              "losses": sum(p["saving_min"] < -1e-8 for p in pairs),
              "baseline_per_source_s": st.mean(x["per_source_s"] for x in base),
              "new_per_source_s": st.mean(x["per_source_s"] for x in new),
              "baseline_max_min": max(x["total_s"] for x in base)/60,
              "new_max_min": max(x["total_s"] for x in new)/60,
              "baseline_initial_min": st.mean(x["initial_finish_s"] for x in base)/60,
              "new_initial_min": st.mean(x["initial_finish_s"] for x in new)/60,
              "baseline_scans": st.mean(x["measure_count"] for x in base),
              "new_scans": st.mean(x["measure_count"] for x in new),
              "components": components, "by_layout": by_layout, "pairs": pairs}
    for key in ("baseline", "new"):
        result[key+"_after_initial_min"] = result[key+"_min"] - result[key+"_initial_min"]
    return result


def development_table():
    folders = ["baseline_development_02", "r1_development_01", "r2_coverage_development",
               "r2_short_development", "r2_edge_development", "r3_covering_development",
               "r4_arc1000_development", "r4_arc1200_development", "r4_arc1450_development"]
    result = []
    for folder in folders:
        data = read(folder, "summary.json")
        result.append({"run": folder, "all_clear": data["all_clear"],
                       "mean_min": data["mean_total_min"], "scans": data["mean_measure_count"],
                       "move_min": data["mean_move_s"]/60, "initial_min": data["mean_initial_finish_s"]/60})
    return result


def figures(stats):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle
    plt.rcParams.update({"font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
                         "axes.unicode_minus": False, "font.size": 10})
    h = stats["holdout"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4), constrained_layout=True)
    colors = ["#416b91", "#e5a34c", "#88a9ba", "#6c9e75", "#c56b6b"]
    labels = ["移动", "测量", "切频", "成功清除", "失败尝试"]
    bottom = [0., 0.]
    for i, row in enumerate(h["components"]):
        values = [row["baseline_min"], row["new_min"]]
        axes[0].bar([0, 1], values, bottom=bottom, color=colors[i], label=labels[i], width=.55)
        bottom = [a+b for a, b in zip(bottom, values)]
    for i, value in enumerate(bottom):
        axes[0].text(i, value+1, f"{value:.2f} 分钟", ha="center", weight="bold")
    axes[0].set_xticks([0, 1], ["baseline", "冻结第三轮"])
    axes[0].set_ylabel("平均整局分钟数")
    axes[0].set_ylim(0, max(bottom)+9)
    axes[0].legend(frameon=False, ncol=2, fontsize=9)
    axes[0].set_title("24个独立案例：移动省下，扫描仍更多")
    translated = {"uniform": "均匀位置", "edge": "边缘集中", "cluster": "聚集", "line": "近共线"}
    rows = h["by_layout"]
    values = [r["saving_min"] for r in rows]
    axes[1].bar(range(len(rows)), values, color=["#527e65" if v>=0 else "#bc6961" for v in values])
    axes[1].axhline(0, color="#666", lw=.8)
    axes[1].axhline(10, color="#a87822", ls="--", label="本轮总体改善门槛10分钟")
    axes[1].set_xticks(range(len(rows)), [translated[r["layout"]] for r in rows])
    axes[1].set_ylabel("baseline减新策略：正值表示节省分钟")
    for i, value in enumerate(values):
        axes[1].text(i, value + (.5 if value>=0 else -.8), f"{value:.2f}", ha="center")
    axes[1].set_ylim(min(-2, min(values)-2), max(13, max(values)+3))
    axes[1].legend(frameon=False, fontsize=8)
    axes[1].set_title("相同策略对不同布局的效果差异")
    fig.savefig(OUT / "holdout_comparison.png", dpi=170)
    fig.savefig(OUT / "holdout_comparison.svg")
    plt.close(fig)

    # 固定一个开发案例演示前后轨迹，不据图中案例选择策略。
    case = "uniform_smooth_170100"
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.5), constrained_layout=True)
    for ax, folder, title in zip(axes, ("r1_development_01", "r3_covering_development"),
                                  ("第一轮：每处整扫，最后追缺口", "第三轮：查漏与清除共用路线")):
        rows = [json.loads(s) for s in (HERE/"runs"/folder/"cases"/case/"actions.jsonl").read_text(encoding="utf-8").splitlines()]
        cases = read(folder, "cases.json")
        truth = next(c for c in cases if c["name"] == case)
        path = [(0., 0.)]
        for row in rows:
            q = tuple(row["position"])
            if q != path[-1]:
                path.append(q)
        ax.add_patch(Circle((0, 0), 1800, fill=False, color="#888", lw=1))
        ax.plot(*zip(*path), color="#577d9c", lw=1.2, alpha=.8)
        scans = list(dict.fromkeys(tuple(r["position"]) for r in rows if r["kind"] == "measure"))
        ax.scatter(*zip(*scans), s=18, facecolors="white", edgecolors="#577d9c", zorder=3, label="实际测量位置")
        ax.scatter(*zip(*(s["position"] for s in truth["sources"])), s=35, marker="x", color="#b05247", zorder=4, label="真源（仅评估可见）")
        for i, q in enumerate(path[1:]):
            if i % 2 == 0:
                ax.annotate(str(i+1), q, xytext=(3,3), textcoords="offset points", fontsize=7, color="#566")
        ax.scatter([0], [0], marker="*", s=65, color="black", label="出发点")
        minutes = rows[-1]["response"]["virtual_time_s"] / 60
        ax.set_title(f"{title}\n{minutes:.2f} 分钟；{len(scans)}个实际测量位置")
        ax.set_aspect("equal")
        ax.set_xlim(-2000, 2000); ax.set_ylim(-2000, 2000)
        ax.set_xlabel("东向 / 米"); ax.set_ylabel("北向 / 米")
        ax.legend(loc="lower left", frameon=True, fontsize=8)
    fig.savefig(OUT / "route_diagnosis.png", dpi=170)
    fig.savefig(OUT / "route_diagnosis.svg")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-figures", action="store_true", help="只生成标准库可复现的统计与CSV")
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    result = {"development": development_table(),
              "holdout": compare("baseline_holdout_final", "r3_holdout_final"),
              "stress": compare("baseline_stress_final", "r3_stress_final", 260912102)}
    (OUT/"comparison.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    for stage in ("holdout", "stress"):
        with (OUT/f"{stage}_paired.csv").open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(result[stage]["pairs"][0]))
            writer.writeheader(); writer.writerows(result[stage]["pairs"])
    if not args.no_figures:
        figures(result)
    print(json.dumps({k: {s:v for s,v in result[k].items() if s not in ("pairs", "components", "by_layout")}
                      for k in ("holdout", "stress")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
