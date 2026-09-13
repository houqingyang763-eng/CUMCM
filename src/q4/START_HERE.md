# 第四问主体：shared25

当前唯一交付方案为shared25，以[selected.py](selected.py)与[selected_config.json](selected_config.json)为准。B0和joint25保留对照。最后一轮A/B小改均未采纳，归入历史探索，不把其收益计入主体成绩。

| 要查什么 | 入口 |
| --- | --- |
| 正式求解、对照运行、制图和核验命令 | [README.md](README.md) |
| 完整模型与理论来源 | [MODEL.md](../exploration/q4/MODEL.md)、[THEORY_RESEARCH.md](../exploration/q4/THEORY_RESEARCH.md) |
| Baseline定义 | [BASELINE.md](../exploration/q4/BASELINE.md)、[baseline.py](baseline.py) |
| 32个不同案例的结果、退步与演练 | [交付报告](../../outputs/q4/delivery01/REPORT.md) |
| 图表、原结果和配对回放 | [outputs/q4](../../outputs/q4/README.md) |
| 首次晋升时的代码等价性 | [MIGRATION.md](MIGRATION.md) |
| 最新归档与小改取舍 | [HANDOFF.md](../exploration/q4/HANDOFF.md)、[小改归档](../exploration/q4/micro_changes/README.md) |

本轮保留全部正式求解代码、配置、报告生成器和原结果字节。仅将研究目录物理迁至src/exploration/q4，并调整审计器的文档读取位置。旧experiments/q4路径以兼容联接供现有报告使用；需要在新电脑使用旧路径时按[src总入口](../README.md)恢复。

独立确认24例与压力8例共416源全清；这是自建结果。单局官方演练13源全清，不是正式测试成绩。部分案例比joint25退步，完整记录必须保留。
