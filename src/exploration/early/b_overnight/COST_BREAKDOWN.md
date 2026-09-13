# 检测还是移动更占时间

本文件在保护停止后，仅归档已经计算并由分析代理返回的结果。没有新增试验。

当前共同案例比较中，移动占总成本约73%—80%。但这并不意味着只优化移动：Q3 Sweep相对Completion每局平均节省191.93秒，其中检测和切换节省126.42秒，占节约的65.9%；移动节省63.01秒。多数时间花在哪里，与某项改进实际省在哪里，是两件事。

关键坏例line_biased_48110中，Sweep多968.16秒，其中移动多870.16秒，占89.9%；检测多100秒、切换多22秒，清除反而省24秒。扫描少、点少或者失败清除少，都不能单独用来判断总时间更好。

因此继续优化时，仍应联合比较到下一点的移动费用、该点必要频道的检测费用、定位后清除及后续绕路。无论点数如何变化，都应按同一批案例的完整账本核对，而不是只比较点数。

来源为 runs/q3_sweep_validation/results.json 与 runs/q4_integrated_validation/results.json；坏例完整逐动作复核见[SWEEP_COUNTEREXAMPLE.md](SWEEP_COUNTEREXAMPLE.md)。三次真实官方演练的成本见[runs/official_practice/verified_results.json](runs/official_practice/verified_results.json)，这些是不同案例，只能各自展示成本构成，不能作策略配对排名。

本页是结束时的简要归档，未在停止后重新计算或检查可视化。策略选择的正式比较口径仍以[SCORECARD.md](SCORECARD.md)为准。
