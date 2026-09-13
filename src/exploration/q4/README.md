# 第四问独立工作目录

**整理状态（2026-09-13）：已停止追加优化，当前正式方案仍为shared25。** 后续A/B小改各48例已完成但均有退步，未采纳。准备大整理时先看[交接说明](HANDOFF.md)和[文件分组清单](FILES.md)；最后一轮结果见[小改法归档](micro_changes/README.md)。

本轮已完成baseline、理论适配、候选比较、32个不同案例确认、官方单局演练及独立代码整理。交付方案为 **shared25：定向条件推断＋共享任务路线＋认证多圆清除**。以F3为框架，重建第四问对固定朝向和阴性反馈的解释；完整rollout与源数上界顺扫未作为默认算法启用。

## 先看这三处

1. [最终结果报告](../../../outputs/q4/delivery01/REPORT.md)：同案例收益、压力测试、退步和官方演练。
2. [中文模型说明](MODEL.md)：约束、公式、理论根据、执行流程与论文组织；[一手文献及细推导](THEORY_RESEARCH.md)。
3. [正式代码与复现](../../q4/README.md)：求解仅依赖Python标准库，唯一配置为`src/q4/selected_config.json`。研究构造器的默认参数不能代替正式入口。

## 交付结论

| 自建批次 | 全清 | B0平均秒/源 | 旧joint25平均秒/源 | 新模型平均秒/源 |
|---|---:|---:|---:|---:|
| 独立确认24局 | 312/312源 | 588.79 | 563.04 | **514.84** |
| 压力8局 | 104/104源 | 629.71 | 526.20 | **510.73** |

各方法均全清。指标为逐局`T/N`再等权取平均。确认集新模型比B0平均整局省15.77分钟，比joint25省9.76分钟；22/24局快于B0、20/24局快于joint25。压力集相应为8/8和6/8。新模型本地运行最长39.21秒，包含状态更新和独立审计。相对joint25最差单局退步29.95分钟，不能声称逐局支配。[逐轨迹退步诊断](../../../outputs/q4/diagnostics01/REPORT.md)

研究目录`holdout01`与正式目录`holdout01`是同一24例的迁移复算，不计为48例。正式压力8例与这24例不同。场景生成规律均为团队假设，有限自建结果不代表官方隐藏分布。

官方问题4**演练**单局13/13源全清（全向8、定向5），虚拟总时间6012.596225秒，462.51秒/源，现实16.01秒。公开成功频道、实际官方终局和独立计费已交叉核对，0次自动重试；[核验证据](../../../outputs/experiments/q4/practice_shared01/verified_summary.json)。这是实际接口核验，不与不同官方案例作速度对照。未使用正式测试机会。

## 从首版到定稿

B0在首批前冻结：[定义](BASELINE.md)、[实现](baseline.py)。它先完成25点发现，再按估计中心开放路线逐源补测、清除；另用已有joint25作较强对照。

下表均为同一12个开发案例，各策略全清159/159源。开发数据用于改进选择，不能作为独立确认。“多用秒”是候选减shared的整局均值，正数表示更慢。

| 方案 | 平均秒/源 | 比shared平均整局多用秒 | 判断 |
|---|---:|---:|---|
| B0 | 574.0082 | 1015.70 | 简单参照 |
| joint25 | 548.6203 | 642.51 | 较强旧参照 |
| 首版candidate | 562.9065 | 768.54 | 普遍补扫吞掉移动节省，未选 |
| 共享路线＋几何评分 | 506.5809 | 71.50 | 失败清除204次，未选 |
| **shared25** | **498.1828** | **0.00** | **交付主方案** |
| 22点发现构造 | 509.6619 | 186.50 | 几何更紧但整局未改善 |
| 按已见12源触发顺扫 | 503.3736 | 56.69 | 未选 |
| 按已见14源触发顺扫 | 506.3235 | 118.93 | 未选 |
| 15源时概率价值顺扫 | 497.3497 | -13.99 | 1胜3负8平，收益集中在1例，未选 |

首版比B0平均少移动976.90秒，却多花约733秒检测切频，且平均慢于joint25。修正方向是只承诺能替代专程发现任务的共享扫描，并真正履行承诺。shared相对几何评分平均再省71.50秒，失败清除204次降至13次；这是完整策略对照，不是孤立局部事件的精确因果分解。

完整rollout只试验首4个开发案例，与shared在**相同4例**中比较为2胜2负、平均慢95.53秒，现实耗时最高187.16秒，未选。不能把其4例均值与其他12例均值直接排名。

概率顺扫首次试验发现同站预算重复扣除，修复并通过10项检查后重跑12例，修复前后证据均保留。当前决策使用修复后结果；去掉唯一获益例，其余11例平均反而慢13.52秒，暂不追加这层复杂度。[概率诊断及缺陷记录](CAP_DIAGNOSTIC.md)、[开发跨批次汇总](../../../outputs/experiments/q4/exploration_comparison01/summary.json)

## 批次与复现入口

目录已补齐分组导航：[正式结果目录](../../../outputs/q4/README.md)、[研究结果目录](../../../outputs/experiments/q4/README.md)、[全部Q4目录清单](../../../outputs/q4/organization01/INDEX.md)。以下运行命令保留为复现说明，本轮不自动执行。

研究结果均在`outputs/experiments/q4`：

- `baseline_smoke`、`runner_smoke_20260913_0304`、`candidate_smoke01`：小规模闭环。
- `develop01`：B0、joint25、首版各12例；`develop02`：shared、geometric各12例，延迟导入清单遗漏另存源码补充记录。
- `develop03`、`discovery_design`：22点整局12例与连续覆盖设计；`develop04`：cap12/cap14各12例；`rollout_pilot01`：完整续行4例。
- `cap_diagnostic`、`cap_diagnostic_confirm`：56公开快照的概率诊断和独立池复核；`cap_value_pilot01`、`cap_value_pilot02`：修复前后各12例。
- `holdout01`：研究代码24例新种子确认；`practice_shared01`、`practice_ui`：官方演练与实际界面核对。

正式依据在`outputs/q4`：`migration_smoke`为8对共2768动作的迁移等价核对；`holdout01`和`pressure01`由正式代码运行；`delivery01`为生成报告与CSV；`diagnostics01`为退步解释；`figures01`为4张PNG及PDF论文图。各批保留种子、配置、源码指纹、逐条动作与独立账本。

仓库根目录运行以下命令，输出目录须未使用：

```powershell
py -3.13 -X utf8 experiments/q4/run.py --split develop --policies shared=candidate:CandidatePolicy geometric=candidate:CandidatePolicy --config-json experiments/q4/compare_planner.json --output outputs/experiments/q4/replay_shared --workers 2
py -3.13 -X utf8 experiments/q4/run.py --split develop --policies capev=candidate_cap:CapPolicy --output outputs/experiments/q4/replay_cap --workers 2
py -3.13 -X utf8 -m unittest discover -s experiments/q4 -p "test_*.py" -v
```

历史首版精确复现以该批`source/`和manifest为准，不能用当前候选源码冒充旧版本。[启动计划与第一版失败处理](PLAN.md)保留为过程记录。一次额度重置已在剩余4%时成功使用，未使用第二次。第三问、原始题面和其他团队成果均未改动，无Git提交或远端发布。本轮自动核验已完成，论文整合与最终提交仍由团队人工审阅。
