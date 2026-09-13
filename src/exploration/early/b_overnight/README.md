# B 题夜间研究入口

本轮按用户授权，多方向推进实现，额度剩余 10% 时停止研究并归档。核心目标是让可靠发现、信息更新、动态选点和有限清除共用一条方法链。原 `../b_adaptive_q3/` 冻结，新方向通过继承或独立状态接入。

## 先看这些

- [当前结果与取舍](RESULTS.md)：哪些方向留下、哪些暂停，比较对象和证据边界。
- [题面指标汇总](SCORECARD.md)：逐局以“总时间/成功清除数”为主指标，总时间单独作为辅助指标。
- [Q4 主动困难搜索](WORST_CASE_SEARCH.md)、[Q3 Sweep 反例与 Detour 修补](SWEEP_COUNTEREXAMPLE.md)、[TourSweep 路线研究](TOUR_SWEEP.md)：保留最坏发现、失败机制和暂停依据。
- [实时续接](PROGRESS.md)、[原研究计划](PLAN.md)：当前任务、授权与保护。
- [Q1/Q2 数学模型](MODEL_Q1_Q2.md)、[Q3 方法说明](MODEL_Q3.md)、[Q4 方法说明](MODEL_Q4.md)：包含可证明部分及与程序的对应。文稿仍待团队人工审阅。
- [有限完成时间](FALLBACK_BOUND.md)、[最终 Q4 审查](FINAL_Q4_REVIEW.md)：正确性与时限边界。
- [演练接口](practice/README.md)：已经复用公开协议；启动前需实际检查当前官方界面。正式测试逐次授权要求不变。

## 可运行核心

Q3 主体是 `task_cost.CompletionCostPolicy + state.InformationState`。候选 `sweep_policy.Q3SweepPolicy` 先沿共同发现路线积累信息，再复用同一个 Completion 清除流程；强参照为 `batch_commitment.CommittedBasePolicy`。

围绕集中巡查的反例，已试过 Q3 DetourSweep 的途中插入和 Q4 TourSweep 的剩余发现路线优化；两方向均未取得足以替换原方法的收益，当前暂停。原 Q3 Sweep 仍为候选；TourSweep 的 Q3 类只有实现，没有整局收益证据。

Q4 当前主线是 `q4_anchor_design.Q4Symmetric25Policy + q4_joint_state.Q4JointCoverageInformationState`。25 个点是具有连续覆盖证明的发现参考网络，运行时还会增加定位点，不能称“全程最多 25 点”。

主动困难搜索共完成 14 次联合方案与 2 次原 37 点对照，全部全清、未触发后备。联合方案最大已找到成本为 784.57 秒/源，同一案例原 37 点为 1189.55 秒/源；这是固定零误差场下的有限空间与朝向搜索，不是全局最坏界或概率保证。完整案例和两种耗时排序见 [WORST_CASE_SEARCH.md](WORST_CASE_SEARCH.md)。

本地入口（在仓库根目录运行，每次使用新的输出目录）：

```powershell
py -3.13 experiments/b_overnight/astra_guard.py check
py -3.13 experiments/b_overnight/runner.py --policies committed_baseline completion sweep --seed 50100 --repeats 1 --output experiments/b_overnight/runs/new_q3
py -3.13 experiments/b_overnight/q4_compare.py --policies directional anchors25 joint25 --seed 50700 --output experiments/b_overnight/runs/new_q4
```

这些是复现入口示例，不代表上述新种子已经运行。保护触发后不得执行，需用户另行安排下一轮。

## 证据位置

每批 `runs/<批次>/` 保存案例、配置、源码快照及散列、逐动作记录和结果。较新的统一批次另有 `summary.json / COMPARISON.md`。动作费用由独立账本复算；本地真值只用于环境与审计，不输入策略。

`practice/local_evidence/` 和 `practice/local_runs/` 是本机隐私证据，已忽略 Git。凭据只从 Windows 当前用户加密保存读取，不写入源码、结果或可提交日志。

所有结果目前属于实验候选；未晋升 `src/`，没有代替团队人工核验，也没有自行启动正式测试。

## 本轮已归档

额度达到10%后已停止研究并暂停自动续跑。请先看[最终归档](ARCHIVE.md)和[次日接续](HANDOFF.md)，不要在STOP状态下执行本页示例。

第三问新增[真值效率参照](../b_oracle_q3/RESULTS.md)：同案例理想可行路线与数学下界，用于判断距离理想效率还有多远。用户后续已明确解除夜间资源锁，旧停止要求仅为历史记录。
