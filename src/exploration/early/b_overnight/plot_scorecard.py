"""从已完成共同案例生成逐源成绩图；只读取结果，不重跑策略。"""
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import subprocess

ROOT = Path(__file__).resolve().parent
subprocess.run(["py", "-3.13", str(ROOT / "astra_guard.py"), "check"], check=True,
               stdout=subprocess.DEVNULL)
os.environ["MPLCONFIGDIR"] = str(ROOT / ".cache" / "matplotlib_scorecard")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

font = font_manager.FontProperties(fname="C:/Windows/Fonts/msyh.ttc")
plt.rcParams["svg.fonttype"] = "path"
plt.rcParams["axes.unicode_minus"] = False


def draw(ax, folder, specs, title):
    path = ROOT / "runs" / folder / "results.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    all_cases = [set(r["case"] for r in rows if r["policy"] == name) for name, _ in specs]
    assert all(c == all_cases[0] for c in all_cases)
    assert len(all_cases[0]) == 12
    colors = ["#9CA8B6", "#477EA9", "#167C82"]
    values = []
    for i, (name, label) in enumerate(specs):
        selected = [r for r in rows if r["policy"] == name]
        assert all(r["success"] and r["cleared"] == r["source_count"] for r in selected)
        v = sorted(r["virtual_time_s"] / r["cleared"] for r in selected)
        mean, tail, worst = statistics.mean(v), statistics.mean(v[-3:]), max(v)
        ax.bar(i, mean, width=.55, color=colors[i], alpha=.9, zorder=2)
        ax.plot([i-.19, i+.19], [tail, tail], color="#142B45", linewidth=2.8, zorder=4)
        ax.plot(i, worst, marker="^", markerfacecolor="white", markeredgecolor="#142B45", markersize=7, zorder=5)
        ax.text(i, mean-25, "均值 %.1f" % mean, ha="center", va="top", color="white", fontsize=10, fontproperties=font)
        ax.text(i, worst+20, "最差 %.1f" % worst, ha="center", fontsize=9, color="#142B45", fontproperties=font)
        values.append(dict(policy=name, values=v, mean=mean, tail=tail, maximum=worst))
    ax.set_xticks(range(len(specs)))
    ax.set_xticklabels([label for _, label in specs], fontsize=11, fontproperties=font)
    ax.set_title(title, loc="left", fontsize=14, pad=18, fontproperties=font)
    ax.set_ylabel("秒 / 源（越低越好）", fontproperties=font)
    ax.set_ylim(0, max(d["maximum"] for d in values) * 1.16)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_axisbelow(True)
    ax.grid(axis="y", color="#E4EAF0", linewidth=.7)
    return dict(input=path.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(path.read_bytes()).hexdigest(), data=values)


if __name__ == "__main__":
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 6.8))
    evidence = []
    evidence.append(draw(axes[0], "q3_sweep_validation", [
        ("committed_baseline", "承诺批次基础策略"), ("completion", "预计完成成本"), ("sweep", "集中巡查后清除")],
        "第三问：巡查时机的比较"))
    evidence.append(draw(axes[1], "q4_integrated_validation", [
        ("directional", "37点方向策略"), ("anchors25", "25点方向策略"), ("joint25", "25点＋联合状态")],
        "第四问：覆盖几何与联合状态的比较"))
    fig.suptitle("按题面指标核对：每局总时间 ÷ 该局成功清除数", fontproperties=font, fontsize=20, x=.07, ha="left", y=.97)
    fig.text(.07, .87, "每组各12个共同自建案例，全部全清。柱：均值　横线：最慢四分之一均值　空心三角：最大值", fontproperties=font, fontsize=11, color="#4D6075")
    fig.text(.07, .075, "两组案例不同，不跨问比较速度。图示为自建场景观察，不能推断总体罕见失败概率，也不是正式成绩。", fontproperties=font, fontsize=11, color="#4D6075")
    fig.subplots_adjust(left=.07, right=.97, bottom=.19, top=.76, wspace=.24)
    out = ROOT / "figures" / "scorecard"
    out.mkdir(parents=True, exist_ok=True)
    for extension in ("png", "svg"):
        fig.savefig(str(out / ("per_source_comparison." + extension)), dpi=180, facecolor="white")
    plt.close(fig)
    (out / "manifest.json").write_text(json.dumps(dict(inputs=evidence, script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), matplotlib=matplotlib.__version__), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Generated per-source comparison from completed paired cases.")
