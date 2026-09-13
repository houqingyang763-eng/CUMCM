# 批次承诺：结果与冻结交付

新增 12 例强参照比较后，建议默认 Completion 继续作为后续核心，同时把已履约的 `CommittedBasePolicy` 作为必须保留的简单强参照。Completion 相对它的平均成本优势只有 3.32%，但最慢四分之一与最差成本分别降低 11.85% 和 13.19%。两者配对各赢 6 例；第一轮 configured 在本批没有胜过默认 Completion。具体完整结果见本文末的独立比较。

最初四例开发检查发现：旧 Base 确实存在“按整批估值、执行途中离开”的缺口，履行真实 `planned_channels` 后，四个新构造布局全部降低成本，平均虚拟耗时由 5101.45 s 降至 4350.22 s（下降 14.73%）。当前 Completion 在四例中原本就自然完成批次；第四问冻结 31 点策略的一例也是如此。它们包装前后的物理动作与公开反馈逐项完全一致。因此保留包装作为 Base 的可选修正，不给 Completion 或 Q4 默认增加这一层。

这些案例现已用于开发检查，不再视为未见案例；结果没有证明所有布局上占优，也没有证明包装 Base 优于 Completion。四例中包装 Base 的平均成本仍略高于 Completion 的 4331.65 s。

## 完整可执行接口

文件 `batch_commitment.py` 提供：

- `CommittedBasePolicy(config=None, reference_only=False)`：实际继承 `BasePolicy`。
- `CommittedCompletionPolicy(config=None, reference_only=False)`：实际继承 `CompletionCostPolicy`。
- `BatchCommitmentMixin`：可写 `class CommittedQ4(BatchCommitmentMixin, Q4ReducedAnchorPolicy): pass`，继续配合 `Q4CoverageInformationState`。
- `natural_batch_fulfilment(rows, state_factory)`：只重放动作及公开反馈，统计原执行是否在离开前完成计划。

保留原策略的 `choose(state)`、`config`、`fallback_started` 等接口。包装不修改状态更新、题设误差、收费、覆盖证书或全清判定，也没有改动冻结策略及共享运行驱动。

队列只来自原策略当前动作上的真实 `planned_channels`，且必须首频道与当前动作一致；不自行扩展为全频道扫描。第一次仍返回原动作；每步得到公开反馈、更新同一完整信息状态后，再决定队列下一项。已经清除、已经证明不存在或已经在该点测过的频道立即跳过。当前位置出现 `near` 时先原地清除，反馈后续队列。动作数或虚拟预算保护阈值、已经启动的后备、`reference_only` 始终优先，取消队列并交回原策略。无新反馈时重复 `choose` 不推进队列；外部把位置改变后取消队列，不强迫折返。

## 数学理由与边界

若原选点的评价使用整批收益与移动后共享成本，而每次只执行首项就重新比较位置，那么评价对象与实际执行对象不同。包装把这一项计划具体化为一个有限动作序列，使承诺期间共享移动费用的假设成立。

这只是修补行为契约，不是一个最优性定理。新反馈可能使另一位置更有价值；短队列承诺也可能付出机会成本。保护阈值和 `near` 清除仍可中断，其他新信息则在队列结束后由原策略利用。队列最多包含原计划中不同的 20 个频道，没有无界承诺。

## 四布局完整对照

以下均为 Q3 自建公开反馈模拟，默认 `Config` 或 `CompletionCostConfig`，同例同布局、误差过程和真实源，全部源都被实际清除。单位为秒；“包装”仅指批次队列。

| 开发案例 | 源数 | Base | 包装 Base | Completion | 包装 Completion |
|---|---:|---:|---:|---:|---:|
| uniform_smooth_43100 | 11 | 5717.69 | 5344.26 | 4639.58 | 4639.58 |
| edge_biased_43101 | 12 | 6934.51 | 5419.65 | 4601.73 | 4601.73 |
| cluster_hashed_43102 | 13 | 3603.69 | 3537.81 | 3891.51 | 3891.51 |
| line_hashed_43103 | 14 | 4149.90 | 3099.15 | 4193.78 | 4193.78 |
| 平均 | — | 5101.45 | 4350.22 | 4331.65 | 4331.65 |

收益主要体现为少走路；不能把所有差值解释成少测频道。例如 cluster 包装后测量由 115 次增加到 120 次，而移动费用由 2863.69 s 降至 2762.81 s，总成本仍降低 65.88 s。edge 的原 Base 触发后备，包装 Base 未触发。

| 案例 | Base 测量/测点 | 包装 Base 测量/测点 | Base 移动 | 包装 Base 移动 |
|---|---:|---:|---:|---:|
| uniform | 229 / 50 | 218 / 39 | 4324.69 | 4001.26 |
| edge | 223 / 91 | 221 / 94 | 5609.51 | 4110.65 |
| cluster | 115 / 20 | 120 / 19 | 2863.69 | 2762.81 |
| line | 124 / 28 | 108 / 19 | 3353.90 | 2392.15 |

原 Base 日志中共有 191 个含多个频道的计划，其中 61 个在仍有频道未履约时离开，留下 293 个计划频道项；包装 Base 的 75 个计划全部完成。一个点重复规划会产生互相重叠的计划，所以这些是计划条目数，不是独立案例数或不同频道数，不能据此计算独立失败概率。

原 Completion 的 37 个计划全部自然履约。包装减少了重复规划所写出的计划条目，但四例每一步的 `(kind, position, channel, response)` 均与原策略完全相同，合计 632 个动作；不仅是最终总费用相同。原动作的原因和队列统计元数据当然不同，不纳入物理等价比较。

## 第四问复用检查

新例 `q4_uniform_random_smooth_43110` 含 14 个源，其中 9 个定向源。冻结 `Q4ReducedAnchorPolicy` 配 `Q4CoverageInformationState`，与其混入批次包装的版本均全清：

| 策略 | 总费用 | 移动 | 切频 | 测量 | 清除 | 测量数 | 失败清除 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Q4 31 点 | 11595.41 | 9118.41 | 280 | 1605 | 592 | 321 | 174 |
| 包装 Q4 31 点 | 11595.41 | 9118.41 | 280 | 1605 | 592 | 321 | 174 |

两者均 509 个动作、64 个测点、未触发后备；29 个计划本来全部自然履约。全部 509 步物理动作及反馈严格相同。大量失败清除如实计费，未当作成功或略去。此例支持“包装不改变该次运行”，不支持减少失败清除或提高 Q4 一般性能。实测计算墙钟时间不用于收益结论，避免缓存和运行噪声影响。

## 验证、证据与复现

5 个构造单元检查通过：只执行真实计划、跳过终态和同点已测、`near` 原地清除后续队列、保护优先、位置变化不折返。18 个完整运行全部成功，合计 228 个实际源清除；运行时原有费用账本、真源保留及 Q4 方向兼容审计通过。没有访问官方模拟器或隐藏数据。

证据目录：`runs/batch_commitment/development/`。包含固定案例、配置、源文件快照及 SHA256 清单、全部动作与公开反馈、完整费用 `results.json`、汇总 `RESULTS.md` 以及逐步相等和均值核对 `analysis.json`。

运行命令（工作目录为仓库根目录）：

```powershell
py -3.13 experiments/b_overnight/astra_guard.py check
py -3.13 experiments/b_overnight/test_batch_commitment.py
py -3.13 experiments/b_overnight/test_batch_commitment.py --batch experiments/b_overnight/runs/batch_commitment/another_batch
```

批次驱动每局检查本夜额度保护，输出目录须为未存在的新目录。`batch_stats.completed_batches` 只在下一次 `choose` 时累加，驱动达到 `state.complete` 后立即退出可能使末批未累加；最终履约结论采用独立日志重放结果，不依赖这个内部计数。

冻结点：`batch_commitment.py` SHA256 为 `8aecb3028fcaad2412a493dd5a02a0f6b09f1859c4ced62dc87219dc01ba1dfa`。此次没有继续参数微调或模块消融；主要交付是 Base 的可选契约修复，以及 Completion / Q4 已自然履约的零影响证据。

## 新增：12 例独立强参照比较

此前 Completion 相对旧 Base 的成绩，包含旧 Base 没有履行其整批计划的影响，不能全部归因于更复杂的任务成本模型。本轮不重跑旧 Base，只比较冻结 CommittedBase、默认 Completion，以及第一轮 `validation_configs.json` 的 configured。不同批次的数据不能相减来估计这一混杂影响的精确比例；本次也不是任务成本模型各内部机制的因果消融。

执行前固定种子 94100—94111、四布局乘三误差过程（smooth / biased / hashed），现有案例文件中没有这些种子。各局三策略采用相同案例；运行顺序按案例轮换；策略和配置均未根据中途结果改变。configured 明确来自第一轮配置，并非 `refinement_validation_configs.json`。预先定义尾部为每个策略自身 12 局中耗时最高的 3 局均值。

36 局全部实际全清，每个策略 153 个源，共 459 个源、5561 个动作；全部账本和真源保留审计通过，均未触发后备。每局开始和每 10 个动作检查额度保护。执行前后的策略及共享 runner 哈希完全一致，没有访问官方程序。

| 指标 | CommittedBase | Completion 默认 | configured 第一轮 |
|---|---:|---:|---:|
| 平均虚拟成本 / s | 3991.50 | **3859.10** | 3911.00 |
| 最慢 3 局均值 / s | 5359.76 | **4724.51** | 4757.20 |
| 最差虚拟成本 / s | 5480.62 | **4757.48** | 4790.50 |
| 相对 CommittedBase 配对胜 / 负 | — | 6 / 6 | 6 / 6 |
| 12 局现实总时间 / s | **6.13** | 21.45 | 20.29 |
| 现实平均每局 / s | **0.51** | 1.79 | 1.69 |
| 现实最慢一局 / s | **1.63** | 3.57 | 3.58 |
| 实际失败清除数 | 0 | 15 | 16 |

现实时间包含规划、状态更新、真值审计和驱动操作，是本机本地模拟测量，不是官方 HTTP 环境时延。默认 Completion 的整局计算在本批仍很短；已履约 Base 则约快 3.5 倍，作为便宜参照或未来短预算后续策略有价值。没有用这批数据实现自动策略切换，不能先知道布局标签再挑当局赢家。

| 案例 | CommittedBase / s | Completion / s | configured / s |
|---|---:|---:|---:|
| uniform_smooth_94100 | 3578.20 | 3722.56 | 3738.35 |
| uniform_biased_94101 | 4670.47 | 4730.28 | 4651.55 |
| uniform_hashed_94102 | 4747.56 | 4250.72 | 4790.50 |
| edge_smooth_94103 | 5436.86 | 4613.14 | 4640.71 |
| edge_biased_94104 | 5161.80 | 4685.78 | 4690.98 |
| edge_hashed_94105 | 5480.62 | 4757.48 | 4790.11 |
| cluster_smooth_94106 | 3231.76 | 3255.07 | 3299.64 |
| cluster_biased_94107 | 1337.36 | 1317.67 | 1331.00 |
| cluster_hashed_94108 | 3254.90 | 3406.05 | 3412.05 |
| line_smooth_94109 | 3802.49 | 4374.27 | 4332.13 |
| line_biased_94110 | 3978.37 | 3784.88 | 3782.84 |
| line_hashed_94111 | 3217.62 | 3411.36 | 3472.15 |

保留的主要反例是 `line_smooth_94109`：Completion 比 CommittedBase 慢 571.78 s（15.04%），configured 也慢。三个边界布局则全部是 Completion 更快，其布局均值由 5359.76 s 降至 4685.47 s；尾部优势主要来自这里。cluster 和 line 的组均值均由 CommittedBase 占优，不能写成复杂策略全面占优。

按本轮事先指定的综合指标，默认 Completion 是较合适的后续核心：平均、尾部和最差都优于两个对手；计算代价高于 CommittedBase，但本批每局不到 4 s。configured 没有体现出足以替代默认参数的优势。这个判断基于每个“布局×误差”只有一个新种子的 12 个本地案例，没有官方分布、罕见失败率或统计显著性保证；不能用它抹去其他已记录批次的相反证据。这批现已查看，后续若用于改进即成为开发证据。

新证据目录为 `runs/batch_commitment/independent/`：`analysis.json` 保存均值、最慢三局的具体名称、最差案例、现实时间和逐例配对差值；`results.json`、全部 `actions/` 保存完整成本与公开反馈；`cases.json`、`configs.json`、`validation_configs.json`、`source/` 和 `manifest.json` 保存执行输入与版本。第一轮配置 SHA256 为 `b40ab997c7e2acb65b52ee0badd4e0ed2630a1202f38b986579021a4fe8197d3`。

复现命令（新输出目录）：

```powershell
py -3.13 experiments/b_overnight/test_batch_commitment.py --independent experiments/b_overnight/runs/batch_commitment/independent_replay
```

这次只扩展了自己拥有的测试驱动与文档；冻结 `batch_commitment.py`、`task_cost.py` 和共享 `runner.py` 均未修改。
