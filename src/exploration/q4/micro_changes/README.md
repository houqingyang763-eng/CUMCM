# 第四问小改法归档

状态：用户于2026-09-13要求停止继续优化，转入目录整理。A/B均未采纳，正式方案仍为src/q4中的shared25。

本轮已落盘：A、B各48例，新16例selected；另复用旧32例selected。现存完整审计记录覆盖144条运行、47913动作，全部通过；不将此前进度汇报中的“尚在跑”当成当前状态。

## 先看结果

- [归档报告与全部退步清单](../../../../outputs/experiments/q4/micro_changes/archive_summary/REPORT.md)
- [机器可读汇总](../../../../outputs/experiments/q4/micro_changes/archive_summary/summary.json)
- [完整审计记录](../../../../outputs/experiments/q4/micro_changes/independent_audit_full01.json)
- [冻结案例定义](../../../../outputs/experiments/q4/micro_changes/catalog.json)

比较对象为当前selected。A为6胜35平7退步，B为42胜0平6退步，差异容差0.0001秒。均未满足逐例不恶化要求，不能以平均改善声称验证通过。新16例不用于本轮事后调参。

## 文件职责

| 文件 | 用途 |
|---|---|
| micro_a.py、test_micro_a.py | 新认证清除目标的取消前缀风险排序及3项针对性检查 |
| micro_b.py、test_micro_b.py | 非主目标辅助补测净价值门槛及9项针对性检查 |
| bench.py、PLAN.md | 当时的冻结对照定义和本地运行器；计划保留为历史记录 |
| audit_results.py | 独立账本/反馈核对及公开状态重建；几何仍共享原实现 |
| summarize.py | 仅整理已存在结果，生成归档报告，不运行策略 |

A/B/selected各自的manifest、source快照及逐局轨迹位于outputs/experiments/q4/micro_changes。partial审计保留过程证据，full01是本轮完整审计。所有后续实验、组合或晋升均暂停，不自动续跑。
