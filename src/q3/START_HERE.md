# 第三问主体：F3与F3改

当前将两方案共同保留用于论文方法与实验比较。F3改是F3+A+扫描站挪近，没有启用B重插、换侧删站或增加预演深度。普通24例都全清；F3改平均省7.810秒，但新增16例平均慢46.387秒，目前证据不支持替代F3。

| 要查什么 | 入口 |
| --- | --- |
| F3原核心代码与69条分批历史轨迹 | [F3/README.md](F3/README.md)、[refined.py](F3/refined.py) |
| F3改的改动与冻结设计 | [F3_modified/README.md](F3_modified/README.md)、[DESIGN.md](F3_modified/DESIGN.md) |
| 共同开局、概率、几何和覆盖代码 | [_core/README.md](_core/README.md) |
| F3模型说明与原增量实验 | [模型](../exploration/q3/other_attempts/refinement/MODEL.md)、[报告](../exploration/q3/other_attempts/refinement/REPORT.md) |
| F3改的最终24例比较 | [报告](../../outputs/experiments/b_q3_p1/f3_modified_micro24_20260913/REPORT.md)、[逐例数据](../../outputs/experiments/b_q3_p1/f3_modified_micro24_20260913/analysis.json) |
| 原文件路径到现位置 | [source_manifest.json](source_manifest.json) |
| 实验运行/分析脚本的原件 | [verification/README.md](verification/README.md) |

## 使用

仓库根目录执行：

```powershell
py -3.13 -B -X utf8 src/q3/runtime.py --check
py -3.13 -B -X utf8 src/q3/verify_runtime.py
py -3.13 -B -X utf8 src/q3/verify_evidence.py
```

前者只构造两种策略；第二条复用原23项针对性测试；第三条只重算已有48条轨迹计费与24例汇总，不新增实验。核验记录在outputs/source_migration/q3。

在Python中可用`from src.q3.runtime import runtime`，再在`with runtime("F3") as session:`作用域内取得`policy, state = session`并接入公开反馈；可将方法名换为`F3_modified`。整局持续使用同一上下文，不每步重建。算法原件按指纹冻结，根目录通过仓库标记定位，运行输入按新清单解析。

原[README](README.md)记录上一轮归档状态，其中“未迁移src”描述的是本轮之前。当前以本页与[src总入口](../README.md)为准。迁移不是新增性能证据，正式测试未启动。
