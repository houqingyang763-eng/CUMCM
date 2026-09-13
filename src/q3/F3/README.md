# F3

F3是当前比较用的主方案。原实现见[refined.py](refined.py)，由上一级[runtime.py](../runtime.py)以`level=3, samples=4`构造。

它根据公开反馈选择开局位置，联合安排已发现源的定位、清除与未知频道扫描；过滤能够严格证明冗余的补测，在原候选与有限候选之间进行四场景预演，并在几何条件允许时采用少量清除圆。全清判据与连续覆盖约束仍由共用状态和几何模块负责。

## 当前最相关证据

- [原普通24例输入](evidence/micro_confirm/cases.json)：320100—320123，四种布局×三种误差×两例。
- `evidence/micro_confirm/<案例名>/`：原F3的动作、元数据、结果及原开局选择缓存。
- [与F3改的完整24例比较](../../../outputs/experiments/b_q3_p1/f3_modified_micro24_20260913/REPORT.md)：F3平均55.756分钟/局、259.675秒/源，24/24全清。
- [原F系列模型说明](../../exploration/q3/other_attempts/refinement/MODEL.md)、[原批次报告](../../exploration/q3/other_attempts/refinement/REPORT.md)：包含F1/F2/F4对照及历史结论，按原文保存。

`evidence/`另保留confirm、development、development_corrected、f3_equivalence、demo、random_audit、stress等历史批次的F3记录，共69条轨迹；这些批次的开发/校验用途不同，不能合成新的独立验证成绩。与其它方法共享的原总表和报告保留在其它路径尝试中，旧→新映射见[整理记录](../../exploration/q3/ORGANIZATION.md)。
