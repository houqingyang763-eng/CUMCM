"""仅绘制已保存几何与解析反例，不重新搜索候选或执行策略。"""
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
NIGHT = HERE.parents[1]
REPO = NIGHT.parents[1]
CACHE = NIGHT / ".cache" / "matplotlib_q1_q2"
CACHE.mkdir(parents=True, exist_ok=True)
os.environ["MPLCONFIGDIR"] = str(CACHE)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Polygon, Patch
from matplotlib.lines import Line2D
from matplotlib.font_manager import FontProperties
import numpy as np

SOURCE = NIGHT / "runs" / "q2" / "geometry_results.json"
FONT_PATH = Path("C:/Windows/Fonts/msyh.ttc")
FONT = FontProperties(fname=str(FONT_PATH))
plt.rcParams.update({"font.family": "DejaVu Sans", "axes.unicode_minus": False,
                     "font.size": 10, "axes.titlesize": 13, "axes.labelsize": 10,
                     "svg.fonttype": "path", "savefig.dpi": 200,
                     "axes.linewidth": .8, "xtick.direction": "out", "ytick.direction": "out"})
INK, BLUE, ORANGE, PURPLE, GREEN = "#263445", "#2866A3", "#D2772C", "#7950A2", "#31866B"


def text(ax, x, y, label, **kwargs):
    return ax.text(x, y, label, fontproperties=FONT, **kwargs)


def style(ax, xlim, ylim):
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("向东距离 / 米", fontproperties=FONT)
    ax.set_ylabel("向北距离 / 米", fontproperties=FONT)
    ax.grid(True, color="#E7EBEF", linewidth=.65, zorder=0)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_color("#B7C1CB")


def save_figure(fig, name):
    for ext in ("png", "svg"):
        fig.savefig(str(HERE / (name + "." + ext)), bbox_inches="tight", facecolor="white")
    plt.close(fig)


def q1_figure(data):
    side = data["equilateral_example"]["side_m"]
    triangle = np.array([[0., 0.], [side, 0.], [side/2, side*math.sqrt(3)/2]])
    midpoint = np.array([side/2, 0.])
    center = np.array([side/2, side*math.sqrt(3)/6])
    radius = side/math.sqrt(3)
    assert abs(radius-data["equilateral_example"]["minimum_enclosing_radius_m"]) < 1e-10
    assert all(abs(np.linalg.norm(v-center)-radius) < 1e-10 for v in triangle)
    fig, axes = plt.subplots(1, 2, figsize=(11.8, 6.4))
    fig.suptitle("定位区域直径 40 米，仍可能无法用半径 20 米的圆覆盖", fontsize=17,
                 fontproperties=FONT, color=INK, y=.985)
    for ax in axes:
        style(ax, (-7, 47), (-23, 42))
        ax.add_patch(Polygon(triangle, facecolor="#DBE9F4", edgecolor=BLUE, linewidth=1.8, zorder=2))
        ax.scatter(triangle[:, 0], triangle[:, 1], s=35, c=BLUE, zorder=5)
        for label, point, offset in zip(("A", "B", "C"), triangle, ((-3, -4), (1.2, -4), (1.2, 1.2))):
            text(ax, point[0]+offset[0], point[1]+offset[1], label, color=BLUE, fontsize=12)
    left, right = axes
    left.set_title("① 取一条最长边作圆的直径", fontproperties=FONT, pad=12)
    left.add_patch(Circle(midpoint, 20, fill=False, edgecolor=ORANGE, linewidth=2, linestyle="--", zorder=3))
    left.scatter(*midpoint, s=40, c=ORANGE, marker="x", zorder=5)
    left.annotate("第三个顶点落在圆外", xy=triangle[2], xytext=(1.5, 26),
                  color=INK, fontproperties=FONT, fontsize=10,
                  arrowprops={"arrowstyle": "->", "color": INK, "connectionstyle": "arc3,rad=-.2"})
    left.annotate("", xy=(0, -6), xytext=(40, -6),
                  arrowprops={"arrowstyle": "|-|", "color": BLUE, "linewidth": 1.1})
    text(left, 20, -10, "最长点对距离 = 40 米", ha="center", color=BLUE)
    text(left, 20, -18.3, "橙色圆：半径 20 米", ha="center", color=ORANGE)
    right.set_title("② 即使调整圆心，最小半径也超过 20 米", fontproperties=FONT, pad=12)
    right.add_patch(Circle(center, radius, fill=False, edgecolor=BLUE, linewidth=2, zorder=3))
    right.add_patch(Circle(center, 20, fill=False, edgecolor=ORANGE, linewidth=1.7, linestyle="--", zorder=3))
    right.scatter(*center, s=40, c=INK, marker="x", zorder=5)
    text(right, center[0]-1.6, center[1]-4, "最优圆心", ha="right", color=INK, fontsize=10)
    right.plot([center[0], triangle[1, 0]], [center[1], triangle[1, 1]], color=BLUE, linewidth=1.1, zorder=3)
    text(right, 20, -17.5, "最小包围半径 = 40/√3 ≈ 23.09 米", ha="center", color=BLUE, fontsize=11)
    fig.text(.5, .022, "蓝色三角形及圆均按真实坐标绘制；虚线圆半径均为 20 米。两面板横纵比例一致。",
             ha="center", fontproperties=FONT, fontsize=10, color=INK)
    fig.subplots_adjust(left=.065, right=.985, bottom=.17, top=.865, wspace=.2)
    save_figure(fig, "q1_diameter_and_cover")
    return dict(vertices=triangle.tolist(), diameter_midpoint=midpoint.tolist(),
                minimum_circle_center=center.tolist(), minimum_circle_radius_m=radius,
                diameter_m=side, clearing_radius_m=20.)


def q2_figure(data):
    source_poly = np.array(data["source_outer_polygon"])
    inner = np.array(data["C1000_inner_polygon"])
    qs = [(900., 400.), (750., 600.), (500., 800.)]
    rows = {tuple(row["q"]): row for row in data["candidates"]}
    assert all(rows[q]["history_reception_certificate"]["guaranteed"] for q in qs)
    assert [rows[q]["in_C1000"] for q in qs] == [True, True, False]
    # 验证绿色域确实是所存位置外包的1000米可靠域内包。
    assert max(np.linalg.norm(q-s) for q in inner for s in source_poly) <= 1000 + 1e-6
    witness = next(r for r in data["universal_counterexample_examples"] if r["q"] == [900, 400])
    sources = np.array(witness["sources"])
    q = np.array(qs[0])
    assert abs(np.linalg.norm(sources[0]-sources[1])-50) < 1e-8
    direction = sources-q
    assert abs(direction[0, 0]*direction[1, 1]-direction[0, 1]*direction[1, 0]) < 1e-7
    assert all(abs(v) < 1 for v in witness["first_true_angles_deg"])
    fig, axes = plt.subplots(1, 2, figsize=(13.1, 7.1))
    fig.suptitle("第二检测点要兼顾可靠接收；两次反馈仍可能留下相距 50 米的两个位置",
                 fontproperties=FONT, color=INK, fontsize=16, y=.988)
    left, right = axes
    style(left, (-140, 1680), (-840, 1010))
    left.set_title("① 绿色内包中的点保证接收；紫色点靠历史信息获证", fontproperties=FONT, pad=14)
    left.add_patch(Polygon(inner, facecolor="#D7EDE5", edgecolor=GREEN, linewidth=1.5, zorder=1))
    left.add_patch(Polygon(source_poly, facecolor="#BBA1D3", edgecolor=PURPLE, linewidth=1.3, zorder=3))
    left.scatter([0], [0], marker="*", s=120, c=INK, zorder=6)
    text(left, 0, -115, "首次检测点\n(0,0)，读数 0°", ha="center", color=INK, fontsize=9)
    for point, name, color, marker in zip(qs, ("A", "B", "C"), (BLUE, BLUE, PURPLE), ("o", "s", "^")):
        left.scatter([point[0]], [point[1]], c=color, s=60, marker=marker, zorder=6)
        if name == "A":
            text(left, point[0]+48, point[1]-12, "A (900,400)", color=color, va="center", fontsize=10)
        elif name == "B":
            text(left, point[0]+48, point[1]+12, "B (750,600)", color=color, va="center", fontsize=10)
        else:
            text(left, point[0]+45, point[1]+65, "C (500,800)\n历史接收半径证书通过", color=color, fontsize=10)
    left.annotate("首次源位置的保守外包", xy=(1200, 12), xytext=(1140, -260),
                  color=PURPLE, fontproperties=FONT, fontsize=10,
                  arrowprops={"arrowstyle": "->", "color": PURPLE})
    left.legend(handles=[Patch(facecolor="#D7EDE5", edgecolor=GREEN, label="1000 米交圆盘域的内包"),
                         Patch(facecolor="#BBA1D3", edgecolor=PURPLE, label="首次源位置的外包")],
                prop=FONT, loc="lower left", frameon=True, framealpha=.95, fontsize=9)

    style(right, (1390, 1510), (-53, 53))
    right.set_title("② 远端局部放大：两个可能源，相同两次读数", fontproperties=FONT, pad=14)
    right.add_patch(Polygon(source_poly, facecolor="#EEE6F5", edgecolor=PURPLE, linewidth=1.2, zorder=1))
    colors = (BLUE, ORANGE)
    for i, (s, color) in enumerate(zip(sources, colors)):
        right.add_patch(Circle(s, 20, facecolor=color, alpha=.09, edgecolor="none", zorder=2))
        right.add_patch(Circle(s, 20, fill=False, edgecolor=color, linewidth=1.2, linestyle="--", zorder=3))
        right.scatter([s[0]], [s[1]], c=color, s=55, zorder=6)
        text(right, s[0]+3, s[1]+4, "可能源 " + str(i+1), color=color, fontsize=10)
    # 只显示经过两个源的共同真实射线；不是画未经计算的后验多边形。
    slope = (sources[1, 1]-q[1])/(sources[1, 0]-q[0])
    xx = np.array([1388., 1512.])
    yy = q[1]+slope*(xx-q[0])
    right.plot(xx, yy, color=INK, linewidth=1.3, zorder=4)
    midpoint = sources.mean(axis=0)
    normal = np.array([-slope, 1.]); normal /= np.linalg.norm(normal)
    a, b = sources[0]-normal*8, sources[1]-normal*8
    right.annotate("", xy=a, xytext=b, arrowprops={"arrowstyle": "|-|", "color": INK, "linewidth": 1.1})
    text(right, midpoint[0]-normal[0]*17, midpoint[1]-normal[1]*17, "50 米", color=INK, fontsize=12,
         ha="center", va="center", rotation=math.degrees(math.atan2(slope, 1)))
    text(right, 1450, 42, "从检测点 A 看，两源在同一条射线上", ha="center", fontsize=10, color=INK,
         bbox={"facecolor": "white", "edgecolor": "none", "alpha": .9})
    text(right, 1450, -44, "虚线圆：分别能清除该源的点（半径 20 米）\n两圆不相交，因此不存在同时可靠的清除点",
         ha="center", va="center", fontsize=9, color=INK,
         bbox={"facecolor": "white", "edgecolor": "none", "alpha": .92})
    fig.text(.5, .041, "两种环境均可返回：首次 0.00°，第二次 323.97°；两源接收半径均取 1500 米。",
             ha="center", fontproperties=FONT, color=INK, fontsize=10)
    fig.text(.5, .012, "紫色域采用已保存的 1.00500001° 实现外包；绿色只表示可靠域内包。未绘制更大的历史可靠域全部边界。",
             ha="center", fontproperties=FONT, color="#566574", fontsize=9)
    fig.subplots_adjust(left=.065, right=.985, bottom=.14, top=.87, wspace=.27)
    save_figure(fig, "q2_reliable_region_and_ambiguity")
    return dict(first_position=data["input"]["first_position"], first_bearing_deg=0.,
                source_outer_polygon=source_poly.tolist(), C1000_inner_polygon=inner.tolist(),
                selected_candidates=[rows[p] for p in qs], counterexample=witness,
                rendering_note="region polygons are stored outer/inner approximations; circles and ray are analytic")


def main():
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    evidence = dict(q1=q1_figure(data), q2=q2_figure(data))
    values = HERE / "plot_values.json"
    values.write_text(json.dumps(evidence, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
              for p in [Path(__file__), values] + sorted(HERE.glob("*.png")) + sorted(HERE.glob("*.svg"))}
    manifest = dict(created_at_utc=datetime.datetime.utcnow().isoformat()+"Z", python=sys.version,
                    matplotlib_version=matplotlib.__version__, source_path=str(SOURCE.relative_to(REPO)),
                    source_geometry_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                    font_name=FONT.get_name(), artifacts_sha256=hashes,
                    no_new_candidate_search=True, axis_aspect="equal within each panel",
                    checks="equilateral radius; all inner-domain vertices within 1000m of all source outer vertices; witness 50m/common ray/legal first angles")
    (HERE / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(dict(output=str(HERE), source_sha256=manifest["source_geometry_sha256"],
                          artifacts=list(hashes)), ensure_ascii=False))


if __name__ == "__main__":
    main()
