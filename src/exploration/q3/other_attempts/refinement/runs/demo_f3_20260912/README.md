# F3 新随机场景回放

用户要求再次查看此前 F3 的逐步行为。本次只生成一个新随机场景，未修改策略，也未重启信念树实验。

- 种子：186539142，一次抽取，无筛选或重抽。
- 场景假设：位置在任务圆内均匀分布，接收半径均匀分布，固定哈希方向误差；仅自建仿真。
- F3：RefinedPolicy(level=3, samples=4)，第二点按第一轮公开反馈用16个条件场景选取。核心文件哈希与此前 VALIDATION.json 一致。
- 结果：16源全清，139条动作，37个流程节点，52.684436分钟。初始两站发现12源；第41步首次清除，第139步完成。此例没有清除失败，不代表平均性能。
- AI核验：139条动作的反馈、方向误差界限和累计费用独立复算；原执行器逐步核对真实位置仍在可行区域内。回放140帧、139条讲解与流程分组完整对应日志。
- 图中真实位置仅用于事后讲解，不输入策略。填色为保守几何范围，不是概率密度；“理由”说明实际规则及有限试算选择，不声称每步最优。

## 文件

案例见cases.json，版本与抽样记录见manifest.json。案例子目录中保留完整selection.json；f3/下为actions.jsonl、metadata.json、result.json、view_data.json、WALKTHROUGH.md。replay_receipt.json记录核验和可视化位置。

## 复现

在仓库根目录执行以下两步，将 `<回放路径>` 替换为一个可写HTML路径。已有cases.json时保留本次场景，已有结果时只重建回放；不会重新抽样或覆盖策略。

```powershell
py -3.13 experiments/b_q3/refinement/demo_f3.py --root experiments/b_q3/refinement/runs/demo_f3_20260912 --visual <回放路径>
py -3.13 experiments/b_q3/refinement/finish_demo_f3.py --root experiments/b_q3/refinement/runs/demo_f3_20260912 --visual <回放路径>
```

若要从头重跑同一场景，将cases.json放入新的空实验目录，以该目录作为--root；不删除本次记录。新随机场景则使用没有cases.json的新目录。
