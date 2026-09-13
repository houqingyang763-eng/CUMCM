# 第三问两点起搜实验

[全部方法](../README.md) · [本方法文档、代码与结果索引](方法索引.md)

先读[结果报告](REPORT.md)：冻结第三轮在24个新案例平均57.89分钟，比baseline省6.52分钟；压力集无提速。未达到用户的10分钟改善及40–50分钟目标，第四轮修正后停止。

## 文件入口

- `patrol.py`、`covering_route.py`：独立策略，初始两点、局部几何与途中共同覆盖路线。
- `coverage_state.py`：只复用已有公开状态和连续覆盖证明。
- `initial_design.py`、`INITIAL_DESIGN.md`：初始布局的概率、定位与先验失配实验。
- `belief.py`、`test_belief.py`：条件发现概率及独立检查；未接入冻结策略。
- `MODEL.md`、`RESEARCH.md`：实际规则、公式、原始文献与迁移边界。
- `runner.py`、`test_validation.py`：配对运行、独立账本与关键正确性检查。
- `FREEZE.json`、`FINAL_VALIDATION.json`：冻结配置/源码/案例散列与独立确认。
- `runs/`：逐局动作、真实公开状态前后快照、费用、错误字段和冻结源码副本。

所有运行仅为自建第三问。这里不提供官方测试入口。

## 复现

命令工作目录为仓库根目录，Python3.13。主策略和运行器仅用标准库；概率与离线设计需numpy。
下面输出目录必须是尚不存在的新目录，运行器会拒绝覆盖既有批次。

```powershell
py -3.13 experiments/b_q3/probability_patrol/runner.py --policy patrol --config experiments/b_q3/probability_patrol/configs/r3_covering.json --cases experiments/b_q3/probability_patrol/cases/final_holdout/cases.json --out experiments/b_q3/probability_patrol/runs/reproduce_r3_holdout --workers 2
py -3.13 experiments/b_q3/probability_patrol/runner.py --policy baseline --cases experiments/b_q3/probability_patrol/cases/final_holdout/cases.json --out experiments/b_q3/probability_patrol/runs/reproduce_baseline_holdout --workers 2
py -3.13 experiments/b_q3/probability_patrol/test_validation.py
py -3.13 experiments/b_q3/probability_patrol/test_belief.py
py -3.13 experiments/b_q3/probability_patrol/summarize.py --no-figures
```

`summarize.py`默认读取本次冻结批次名称，生成已有批次的比较JSON/CSV；去掉`--no-figures`同时生成PNG/SVG，绘图还需matplotlib。
本机图使用临时目录安装的matplotlib3.11.1，未改系统Python依赖；数值实验不依赖绘图库。
离线设计具体命令见`INITIAL_DESIGN.md`，不要把单源蒙特卡洛样本数当成完整策略案例数。

R1及R2/R4配置用于解释逐轮变化，不是当前推荐参数。不要在看过最终新案例之后据其选择其他参数并重复声称是独立确认。

## 结束规则

所有频道须清除或由真实阴性覆盖/16源上限证明不存在，才能正常结束。概率质量低、网格为空、未来路线覆盖均不能提前结束。
运行器默认每局3000动作、180分钟虚拟时间、120秒墙钟诊断上限；触发任一上限都保留失败，不按成功子集计算整体性能。
本次冻结确认没有触发这些上限。
