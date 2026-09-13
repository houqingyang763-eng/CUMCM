# 第四问文件分组清单

此表按作用整理现有文件，配合[交接说明](HANDOFF.md)阅读；保留原路径以维持导入、文档链接和历史来源指纹。

| 分组 | experiments/q4内的文件 | 定位 |
|---|---|---|
| 当前阅读入口 | README.md、HANDOFF.md、FILES.md | 状态、证据导航、大整理交接 |
| 模型与理论 | MODEL.md、THEORY_RESEARCH.md、BASELINE.md | 主模型说明、一手文献、比较基线 |
| 专题探索 | BELIEF_REVIEW.md、DISCOVERY_DESIGN.md、CAP_DIAGNOSTIC.md | 条件模型检查、22点构造、概率顺扫与缺陷边界 |
| 历史计划与授权 | PLAN.md、reset_authorization.json | 启动计划与已使用的一次重置记录，不是继续执行指令 |
| 研究算法 | baseline.py、candidate.py、belief.py、planner.py、common.py | 研究实现；正式交付依赖位于src/q4 |
| 研究场景和统计 | cases.py、run.py、analyze.py、diagnose.py | 自建运行、账本、结果比较 |
| 未采纳候选 | candidate_cap.py、cap_value.py、discovery_design.py | 顺扫和发现点构造探索 |
| 冻结对照配置 | compare_cap.json、compare_cover22.json、compare_planner.json、compare_rollout.json、cover22_selection.json | 各批候选参数；历史精确版本以各批source为准 |
| 演练接口 | practice.py、verify_practice.py、practice_shared.json | 研究阶段演练；正式入口在src/q4 |
| 针对性检查 | test_baseline.py、test_belief.py、test_belief_extra.py、test_candidate.py、test_cap_policy.py、test_planner.py、test_practice.py、test_runner.py | 实现和边界检查，不等于隐藏案例性能保证 |
| 最后两局诊断 | micro_diagnosis.py | 从原日志重建公开前缀，生成micro_diagnosis批次 |
| 最后一轮小改 | micro_changes/ | A/B独立候选、冻结计划、运行器、审计、结果归档；已停止继续推进 |
| 目录整理工具 | organize_index.py | 仅生成目录清单与输出导航，不运行策略 |

## src/q4中的正式文件

- selected.py与selected_config.json：唯一当前选定策略和参数。
- candidate.py、planner.py、belief.py、common.py、core/：正式算法依赖。
- baseline.py、cases.py、run.py、analyze.py：比较基线、固定场景、完整运行和统计。
- practice.py、verify_practice.py：实际演练接口边界及结果核验。
- report.py、figures.py、diagnose_regressions.py：正式报告、论文图、退步诊断。
- replay_compare.py、replay_pair.html：原日志配对回放；不重新执行策略。
- audit_delivery.py、test_selected.py、test_runner.py、test_practice.py：交付核验与测试。
- README.md、MIGRATION.md、migration_sources.json、requirements-figures.txt：入口、迁移来源与制图依赖。

正式运行源码和配置本次没有调整。输出批次、旧版本边界与可再生成项见[交接说明](HANDOFF.md)及两处outputs目录入口。
