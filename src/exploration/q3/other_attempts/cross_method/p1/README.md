# P1：联合路线与完整清除任务

**最新：用户将第三轮R命名为F3改；原普通24例已补齐，[完整比较结果](../../../../outputs/experiments/b_q3_p1/f3_modified_micro24_20260913/REPORT.md)不支持替代F3。** 两者24/24全清，F3改平均每局仅省7.810秒（0.23%）、每源省0.537秒，两个95%区间均跨零；新增16例平均每局反而慢46.387秒。原8例是这24例的子集，本批复用8例、补跑16例，没有重调参数。[运行前设计与方案定义](F3_MODIFIED_DESIGN.md)，[比较图](../../../../outputs/experiments/b_q3_p1/f3_modified_micro24_20260913/comparison.png)。

用户于2026-09-13明确授权运行。设计见[实验设计](../P1_EXPERIMENT_DESIGN.md)，固定8例及旧F3指纹见[筛选清单](../p1_screening_manifest.json)。只运行一个候选组合，不做组件排列组合。

**本轮已完成：8/8全清，平均省1.244分钟，但去掉最大收益例后其余7例平均慢10.830秒，未通过原定筛选，保留F3。** 详见[实验结论](RESULTS.md)及[完整报告](runs/screening_20260913/REPORT.md)。

**当前第二轮已完成：[轻量实验结论](LIGHTWEIGHT_RESULTS.md)**——24/24全清，A平均省69.201秒、B省53.307秒，均通过开发筛选；AB平均省49.996秒但未通过逐例删除检查。保留两个单项，不采用当前组合。[运行前设计](LIGHTWEIGHT_DESIGN.md)；输出目录为`outputs/experiments/b_q3_p1/light_screening_20260913/`。

**第三轮已完成：[挪站结果与换侧机会](RELOCATION_RESULTS.md)**——8/8全清，比A平均再省47.003秒，5胜3平；但平均查漏尾段多19.218秒，不能视为已解决长尾。[冻结设计](RELOCATION_DESIGN.md)。换侧保留为候选，35次实际横向补测中未发现现成两侧点可省时删站的机会，本轮未叠加运行。

此前[预演诊断与加深搜索建议](NEXT_DESIGN.md)仅重算旧日志，未运行新策略。用户随后明确要求回到查漏问题、使用已有轻量方法，该加深搜索建议已搁置。

## 实现与当前批次

- `p1_tasks.py`：完整服务任务、可能成功出口、共同保证圆、逐频道连续覆盖与开放路线。任务之间只调整访问顺序；内部顺序在选任务时枚举既有两/三圆的有限排列。
- `p1_policy.py`：原F3候选加一个联合路线首任务；同一4场景完整预演、无嵌套采样的共同续行、实际落点扫描及原候选安全回退。
- `p1_run.py`：核对冻结输入与旧F3、同案运行、3000动作/180虚拟分钟/1200现实秒上限。共用开局选择采用已核对缓存，历史选择用时单列并计入现实预算。
- `test_p1.py`：11项接口检查，包括关闭P1的F3等价、提前成功、所有出口覆盖、状态不污染、任务槽替换和条件场景全清。输出见[test_results.txt](test_results.txt)。
- `analyze_results.py`：只重放结果日志、独立计费及配对汇总，不重新调用策略。
- `plot_routes.py`：事后真实路线图，图示真实源不输入控制器。

当前筛选目录为 `runs/screening_20260913/`。模型源码在批次启动时冻结；分析和绘图工具单独记录，不作为参试算法变更。测试期间发现历史同名`run`模块导入冲突，已用独立模块名解决；发生在完整筛选启动之前，没有产生失败案例成绩。

先按既定接口实现，再对同一名义计划中的F1几何资格作缓存，避免2-opt重复证明；缓存不跨公开状态复用，也不改变费用或候选选择。11项检查通过后才启动筛选。

## 命令

在仓库根目录运行：

```powershell
py -3.13 experiments/b_q3/cross_method/p1/test_p1.py
py -3.13 experiments/b_q3/cross_method/p1/p1_run.py --out experiments/b_q3/cross_method/p1/runs/new_screening --workers 2
py -3.13 experiments/b_q3/cross_method/p1/analyze_results.py experiments/b_q3/cross_method/p1/runs/new_screening
```

运行器拒绝覆盖既有输出；上述`new_screening`只是复现时的新输出位置，不代表本轮另有一批。官方测试与P2/P3均不属于本次运行。

## 轻量第二轮入口

- `light_route.py`：两个独立开关；只后处理原F3路线，保持原四场景非递归预演机制。
- `light_run.py`：三组各8例、原始输入指纹核对、独立进程、每局日志和批次源码冻结。
- `test_light.py`及`light_test_results.txt`：关闭开关兼容、覆盖、变量边界与接入检查。
- `analyze_light.py`：旧8例及新24例的反馈、计费、状态重放与冻结门槛汇总。
- `plot_light.py`：每组最好/最差案例的实际路线对照。

复现时使用新的输出目录：

```powershell
py -3.13 experiments/b_q3/cross_method/p1/light_run.py --out outputs/experiments/b_q3_p1/new_light_screening --workers 2
py -3.13 experiments/b_q3/cross_method/p1/analyze_light.py outputs/experiments/b_q3_p1/new_light_screening
```
