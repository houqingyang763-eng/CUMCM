# 2026-09-12 目录整理记录

用户要求按探索方法归组。本次实际目录为 `experiments/b_q3`。

## 搬迁对照

以下路径均相对于本目录。

| 原路径 | 新路径 |
| --- | --- |
| `AI1_optimization_summary_20260912` | `cross_method/AI1_optimization_summary_20260912` |
| `AI2_optimization_summary_20260912` | `cross_method/AI2_optimization_summary_20260912` |
| `AI3_optimization_summary_20260912` | `cross_method/AI3_optimization_summary_20260912` |
| `Q3_失败方案交接包` | `decision_pilot/Q3_失败方案交接包` |
| `Q3_失败方案交接包.zip` | `decision_pilot/Q3_失败方案交接包.zip` |
| `2026-09-11_Q3公式与选点讨论_原始对话及批注.md` | `legacy_baseline/2026-09-11_Q3公式与选点讨论_原始对话及批注.md` |
| `2026-09-11_Q3完整公式讲解_对话原文与六条批注.md` | `legacy_baseline/2026-09-11_Q3完整公式讲解_对话原文与六条批注.md` |
| `audit_recorded_practice.py` | `legacy_baseline/audit_recorded_practice.py` |
| `recorded_practice_audit.json` | `legacy_baseline/recorded_practice_audit.json` |

## 保留与修复

- 七个既有策略目录、代码导入位置、运行结果目录不动。旧基线新增独立材料入口。
- 原始对话、统计JSON、结果日志、ZIP和交接包内部全部保持字节一致。交接包内部冻结工程是历史证据，不参与现行代码导航重写。
- AI综述仅修复搬迁影响的文档链接、重建脚本根路径及生成链接；原数值结论未改。
- 旧演练核验脚本修复根路径；交接包构建脚本修复输出和讨论输入路径；目录外模型重评修复交接包链接。
- AI_USAGE历史条目保留当时路径，本表用于追溯。未提交Git或运行实验。

## 校验

- 原有 4561 个文件均找到对应新位置；其中 394 个随目录或文件搬迁。
- 逐文件SHA256对照：除已列明的 22 个导航/路径修改文件外，其余原文件字节一致，无丢失或意外改动。
- 修改的Python文件通过语法检查；活动说明文档未新增失效的本地链接。
- 扫描时发现 2 个原有失效链接，保持原文，详见[校验清单](cross_method/organization_validation.json)。
- 本次不重跑仿真、不重新评估模型性能。
