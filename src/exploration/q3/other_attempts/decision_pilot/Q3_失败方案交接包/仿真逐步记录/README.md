# 仿真逐步记录

本目录由export_stepwise.py在本次交付时重新逐动作调用自建LocalEnvironment生成；全部反馈与原实验日志逐项一致，并重新检查计费、位置保留和全清。属于原案例的确定性回放，不是新增独立案例，也不是官方模拟器记录。

共12案例×4种运行方式＝48条完整记录，7497个动作。默认与预演恰好选择同一动作时仍分别提供记录，不能按文件数算不同案例。

建议先读edge_biased_161104的center_default.md与scan7_r60.md：前者服务步6—9的近共线补测，可与后者总步139的原地交会测量比较。再看rollout_selected.md，这是最终选中原型的完整轨迹，不能只用default说明其整局表现。

每个案例附四份MD（逐步阅读）、四份CSV（筛选费用和状态）、四份JSONL（原精度与原始动作反馈），另有候选比较.md。Sweep的阶段标签由每步后是否还有未知频道标注，仅为阅读辅助，不代表新增了该策略的显式阶段控制。

| 案例 | 方法 | 步数 | 整局/分 | 记录 |
|---|---|---:|---:|---|
| uniform_smooth_161100 | 原两阶段基线 | 134 | 70.12 | [逐步记录](uniform_smooth_161100/scan7_r60.md) |
| uniform_smooth_161100 | 已有Sweep | 137 | 74.06 | [逐步记录](uniform_smooth_161100/sweep.md) |
| uniform_smooth_161100 | 新续行默认行动 | 136 | 70.89 | [逐步记录](uniform_smooth_161100/center_default.md) |
| uniform_smooth_161100 | 新续行加预演选择 | 136 | 70.72 | [逐步记录](uniform_smooth_161100/rollout_selected.md) |
| uniform_biased_161101 | 原两阶段基线 | 134 | 62.97 | [逐步记录](uniform_biased_161101/scan7_r60.md) |
| uniform_biased_161101 | 已有Sweep | 113 | 64.21 | [逐步记录](uniform_biased_161101/sweep.md) |
| uniform_biased_161101 | 新续行默认行动 | 143 | 64.79 | [逐步记录](uniform_biased_161101/center_default.md) |
| uniform_biased_161101 | 新续行加预演选择 | 143 | 64.74 | [逐步记录](uniform_biased_161101/rollout_selected.md) |
| uniform_hashed_161102 | 原两阶段基线 | 135 | 69.65 | [逐步记录](uniform_hashed_161102/scan7_r60.md) |
| uniform_hashed_161102 | 已有Sweep | 120 | 77.79 | [逐步记录](uniform_hashed_161102/sweep.md) |
| uniform_hashed_161102 | 新续行默认行动 | 137 | 70.19 | [逐步记录](uniform_hashed_161102/center_default.md) |
| uniform_hashed_161102 | 新续行加预演选择 | 137 | 70.19 | [逐步记录](uniform_hashed_161102/rollout_selected.md) |
| edge_smooth_161103 | 原两阶段基线 | 171 | 78.46 | [逐步记录](edge_smooth_161103/scan7_r60.md) |
| edge_smooth_161103 | 已有Sweep | 142 | 74.91 | [逐步记录](edge_smooth_161103/sweep.md) |
| edge_smooth_161103 | 新续行默认行动 | 221 | 97.56 | [逐步记录](edge_smooth_161103/center_default.md) |
| edge_smooth_161103 | 新续行加预演选择 | 214 | 94.67 | [逐步记录](edge_smooth_161103/rollout_selected.md) |
| edge_biased_161104 | 原两阶段基线 | 172 | 78.36 | [逐步记录](edge_biased_161104/scan7_r60.md) |
| edge_biased_161104 | 已有Sweep | 146 | 75.40 | [逐步记录](edge_biased_161104/sweep.md) |
| edge_biased_161104 | 新续行默认行动 | 219 | 96.15 | [逐步记录](edge_biased_161104/center_default.md) |
| edge_biased_161104 | 新续行加预演选择 | 213 | 94.24 | [逐步记录](edge_biased_161104/rollout_selected.md) |
| edge_hashed_161105 | 原两阶段基线 | 159 | 76.10 | [逐步记录](edge_hashed_161105/scan7_r60.md) |
| edge_hashed_161105 | 已有Sweep | 146 | 75.16 | [逐步记录](edge_hashed_161105/sweep.md) |
| edge_hashed_161105 | 新续行默认行动 | 179 | 82.50 | [逐步记录](edge_hashed_161105/center_default.md) |
| edge_hashed_161105 | 新续行加预演选择 | 179 | 82.50 | [逐步记录](edge_hashed_161105/rollout_selected.md) |
| cluster_smooth_161106 | 原两阶段基线 | 127 | 49.60 | [逐步记录](cluster_smooth_161106/scan7_r60.md) |
| cluster_smooth_161106 | 已有Sweep | 120 | 48.01 | [逐步记录](cluster_smooth_161106/sweep.md) |
| cluster_smooth_161106 | 新续行默认行动 | 128 | 50.04 | [逐步记录](cluster_smooth_161106/center_default.md) |
| cluster_smooth_161106 | 新续行加预演选择 | 129 | 49.72 | [逐步记录](cluster_smooth_161106/rollout_selected.md) |
| cluster_biased_161107 | 原两阶段基线 | 134 | 50.84 | [逐步记录](cluster_biased_161107/scan7_r60.md) |
| cluster_biased_161107 | 已有Sweep | 111 | 47.52 | [逐步记录](cluster_biased_161107/sweep.md) |
| cluster_biased_161107 | 新续行默认行动 | 135 | 50.84 | [逐步记录](cluster_biased_161107/center_default.md) |
| cluster_biased_161107 | 新续行加预演选择 | 134 | 50.57 | [逐步记录](cluster_biased_161107/rollout_selected.md) |
| cluster_hashed_161108 | 原两阶段基线 | 130 | 49.38 | [逐步记录](cluster_hashed_161108/scan7_r60.md) |
| cluster_hashed_161108 | 已有Sweep | 106 | 47.43 | [逐步记录](cluster_hashed_161108/sweep.md) |
| cluster_hashed_161108 | 新续行默认行动 | 134 | 50.76 | [逐步记录](cluster_hashed_161108/center_default.md) |
| cluster_hashed_161108 | 新续行加预演选择 | 133 | 50.11 | [逐步记录](cluster_hashed_161108/rollout_selected.md) |
| line_smooth_161109 | 原两阶段基线 | 181 | 62.97 | [逐步记录](line_smooth_161109/scan7_r60.md) |
| line_smooth_161109 | 已有Sweep | 197 | 57.03 | [逐步记录](line_smooth_161109/sweep.md) |
| line_smooth_161109 | 新续行默认行动 | 194 | 68.56 | [逐步记录](line_smooth_161109/center_default.md) |
| line_smooth_161109 | 新续行加预演选择 | 191 | 66.38 | [逐步记录](line_smooth_161109/rollout_selected.md) |
| line_biased_161110 | 原两阶段基线 | 187 | 65.22 | [逐步记录](line_biased_161110/scan7_r60.md) |
| line_biased_161110 | 已有Sweep | 144 | 57.93 | [逐步记录](line_biased_161110/sweep.md) |
| line_biased_161110 | 新续行默认行动 | 198 | 70.28 | [逐步记录](line_biased_161110/center_default.md) |
| line_biased_161110 | 新续行加预演选择 | 197 | 68.99 | [逐步记录](line_biased_161110/rollout_selected.md) |
| line_hashed_161111 | 原两阶段基线 | 180 | 68.70 | [逐步记录](line_hashed_161111/scan7_r60.md) |
| line_hashed_161111 | 已有Sweep | 154 | 43.76 | [逐步记录](line_hashed_161111/sweep.md) |
| line_hashed_161111 | 新续行默认行动 | 190 | 75.44 | [逐步记录](line_hashed_161111/center_default.md) |
| line_hashed_161111 | 新续行加预演选择 | 197 | 74.60 | [逐步记录](line_hashed_161111/rollout_selected.md) |

## 理由代码

- `fixed_scan`：按固定扫描任务检测；清除/排除频道及已足够小的区域会在任务生成时跳过。
- `guaranteed_here`：当前位置20米范围包含该源整个支持集，在原地保证清除。
- `guaranteed_center`：该源包围圆小于20米，去圆心保证清除。
- `one_small_center_try`：续行中该源区域不超过30米且中心相容，执行一次中心试清。
- `approach_center_and_measure`：区域仍大，去当前估计中心补测；中心已测时才横向偏移。
- `small_region_center_try`：原基线在20—30米区域对相容中心试清。
- `completion_shared_probe`：旧局部评价选择原地补测；仍使用旧W/G规则。
- `completion_localize`：旧局部评价选择移动补测。
- `completion_clear`：旧局部规则选择清除。
- `completion_cell_clear`：旧局部规则选择清除格试清。

后缀_shared代表执行选中的共享检测块；_single代表选中的单频道动作。其余冻结基线理由代码在CSV中保留原值，未记录的评分不补造。
