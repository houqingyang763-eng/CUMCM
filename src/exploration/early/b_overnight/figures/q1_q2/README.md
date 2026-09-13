# 前两问数学图

- `q1_diameter_and_cover.png/.svg`：真实边长 40 米等边三角形、最长边直径圆，以及半径 40/√3 米的最小包围圆。
- `q2_reliable_region_and_ambiguity.png/.svg`：已保存的首次位置外包、可靠第二点候选内包、三个候选点及 50 米不可区分反例。绿色不表示历史可靠域的完整边界；放大图中的 20 米圆是各环境允许的清除点域。
- `plot_q1_q2.py`：唯一绘图脚本；不运行策略、不重新搜索候选。
- `plot_values.json`：实际使用的全部几何数值，含候选证书和反例原始坐标。
- `manifest.json`：源数值、脚本、数值副本和 PNG/SVG 的 SHA256；Python、matplotlib 与字体信息。

输入是 `../../runs/q2/geometry_results.json`。画图时核对等边三角形包围半径、内包每个顶点距位置外包每个顶点不超过 1000 米，以及反例源相距 50 米、第二点看两源共射线、首次误差在 1° 内。图中圈和线按解析几何绘制，各面板横纵使用相同长度比例；第二幅右面板另标为局部放大。

本次环境使用 Python 3.7.0 / matplotlib 2.2.3，通过显式 Windows 微软雅黑字体绘制中文；SVG 文字转为路径。脚本在导入 matplotlib 前把 `MPLCONFIGDIR` 放到仓库已忽略的 `.cache/matplotlib_q1_q2/`。

从仓库根目录执行：

```powershell
py -3.13 experiments/b_overnight/astra_guard.py check
& D:/anaconda/python.exe experiments/b_overnight/figures/q1_q2/plot_q1_q2.py
```

属于本地模型说明图，不是官方模拟器结果。已在 `MODEL_Q1_Q2.md` 对应结论后嵌入并写明内外包边界。
