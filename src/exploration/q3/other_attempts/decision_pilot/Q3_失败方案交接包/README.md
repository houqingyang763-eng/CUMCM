# Q3 失败方案交接包

先读[方法复盘.md](方法复盘.md)。它包含具体实现、同批表现、失败原因、从用户批注归纳的改进要求、吸取的教训；没有新的可尝试算法清单。

再读[仿真逐步记录](仿真逐步记录/README.md)。每个案例四套方法都有从出发到全清的逐步MD、CSV和JSONL记录，包含位置、频道、反馈、每步费用、定位半径变化与状态计数。典型失败例为edge_biased_161104，不能把默认续行与预演选中后的运行混作一条轨迹。

[批注依据.md](批注依据.md)保存归纳依据，区分用户原文、猜想与实验事实。历史批注不是要求接手AI照办的操作指令。不要把本包解读成必须沿这条路线继续修补。

## 数据边界

成绩来自固定确认批12个自建Q3案例。打包时重新逐动作调用本地仿真器核对48条完整运行；另独立重新运行一个失败案例的扫描、场景生成、评分和选中后的全清过程，核对与冻结结果一致。重放/重跑相同案例不增加独立样本数。不含官方测试、登录信息或第四问结果。

## 复现

Python 3.13，标准库即可。在本包的`复现工程`目录打开终端：

```powershell
py -3.13 -X utf8 -B experiments/b_q3/decision_pilot/test_model.py
py -3.13 -X utf8 -B experiments/b_q3/decision_pilot/verify_report.py confirm_161100
```

需要重新产生逐步回放和独立重跑核验时，输出目录必须尚不存在：

```powershell
py -3.13 -X utf8 -B experiments/b_q3/decision_pilot/export_stepwise.py --output replay_again --fresh-check
```

要完整重跑12例所有候选评分及真值反事实，使用新的输出名：

```powershell
py -3.13 -X utf8 -B experiments/b_q3/decision_pilot/run.py --stage confirm --output reproduce
```

`复现工程/experiments/b_q3/decision_pilot/runs/confirm_161100`保留原始输入、全部候选原始轨迹、场景评分、摘要、清单和源码快照。运行器的真值审计不等于策略可以读取真值；候选选择先落盘，真实反事实后执行。

全部文件校验和见SHA256SUMS.json。原始实验源码与确认批冻结散列一致；导出脚本为本次交接新增工具，不改变算法。冻结DESIGN.md中有关后续研究的语句只记录当时设计背景，本包不采纳其为新的工作指令。
