# F3改

用户命名的F3改，就是原第三轮R：**F3＋A＋扫描站挪近**。

- [light_route.py](light_route.py)：启用A，利用已有服务停点承担未知频道扫描，满足连续覆盖和费用条件时取消专门扫描站。
- [relocate.py](relocate.py)：在没有已发现待清源、仍有未知频道时，固定任务与顺序，将扫描站沿前一站方向挪近；10次二分，每次检查连续覆盖。
- [冻结设计](DESIGN.md)：普通24例扩展前固定的算法、输入和统计口径。

当前入口为上一级[runtime.py](../runtime.py)，选择`F3_modified`。不包含B的扫描站重插，也没有加入换侧删站；预演场景数和深度未增加。

## 最终比较证据

- [完整24例报告](../../../outputs/experiments/b_q3_p1/f3_modified_micro24_20260913/REPORT.md)
- [逐例分析与来源指纹](../../../outputs/experiments/b_q3_p1/f3_modified_micro24_20260913/analysis.json)
- [配对比较图](../../../outputs/experiments/b_q3_p1/f3_modified_micro24_20260913/comparison.png)
- [24例逐例引用清单](../../../outputs/experiments/b_q3_p1/f3_modified_micro24_20260913/manifest.json)
- [复用8例的原始批次](../../../outputs/experiments/b_q3_p1/relocation_screening_20260913/REPORT.md)

两方案均24/24全清，F3改平均每局仅省7.810秒（0.23%）、每源省0.537秒，两个95%区间均跨零；新增16例平均每局慢46.387秒。因此保留为比较方案，不据此替代F3。

上述24例由本批新增16条和上一批复用8条轨迹组成。结果按项目约定留在`outputs/experiments/b_q3_p1/`，这里集中提供入口，未复制成另一个成绩版本。旧manifest中记录的原代码路径由[搬迁清单](../../exploration/q3/organization_manifest.json)解析。
