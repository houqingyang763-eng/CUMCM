# Q3 新决策设计与小验证

[全部方法](../README.md) · [本方法文档、代码与结果索引](方法索引.md)

本目录对应用户授权的“职责清楚的新决策设计＋一次能判断方向的小规模验证”。仅自建第三问；未改原两阶段、Sweep或官方接口。

- [本轮判断](REPORT.md)：为什么评价器有局部收益，但原型不应替换基线。
- [运行前冻结设计](DESIGN.md)：阶段职责、候选、相容场景、核心评价与验收。关于“每源一次试清”的实施边界见结果报告末尾，原冻结设计保持不改。
- [12例完整结果与独立核验](runs/confirm_161100/RESULTS.md)：同案例比较、费用分解、逐例收益、验证范围。
- [核心实现](model.py)：相容采样、候选、明确续行、平均完成费用。
- [实验入口](run.py)、[关键约束测试](test_model.py)、[独立核验与汇总](verify_report.py)。

从项目根目录运行：

```powershell
py -3.13 -B experiments/b_q3/decision_pilot/test_model.py
py -3.13 -B experiments/b_q3/decision_pilot/verify_report.py confirm_161100
```

需要重跑时使用新的输出名称，保留原记录：

```powershell
py -3.13 -B experiments/b_q3/decision_pilot/run.py --stage confirm --output confirm_reproduce
```

`confirm`固定12例输入，不是每次新增12例。各例的`selection_before_counterfactual.json`包含候选、假想源、逐场景评分与选中项；`diagnosis.json`包含事后实际比较；各候选的`*_actual.json`含服务轨迹，共同阶段一轨迹在`scan.json`。原两阶段和Sweep的actual文件为整局轨迹。原始统计列的阶段范围差异见生成报告，不应直接横比测量数量或wall_s。

状态：完成设计和验证；新原型未达替换门槛，停止扩大本轮重构。本结论由AI执行和检查，尚待团队人工复核。
