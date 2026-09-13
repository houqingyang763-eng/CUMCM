# 自适应第二站

[全部方法](../README.md) · [本方法文档、代码与结果索引](方法索引.md)

先看[REPORT.md](REPORT.md)：24个新案例，固定R3 58.16分钟，仅选点56.51分钟，联合频道56.47分钟。小幅增益主要来自位置；频道选择没有可靠额外收益，暂不晋升正式策略。

- [MODEL.md](MODEL.md)：先验、源数后验推导、候选动作、完整全清rollout、迁移边界。
- [adaptive.py](adaptive.py)：条件场景采样、候选生成与一步决策。
- [online.py](online.py)：`OnlineAdaptivePolicy`流式公开状态接口。
- [run.py](run.py)：四策略同案比较；输出目录必须不存在，防止覆盖。
- [diagnose.py](diagnose.py)：冻结后的候选事后最佳诊断、独立动作账本、配对区间。
- [sensitivity.py](sensitivity.py)：在独立64个后验场景与不同半径先验下重新评估原选择，不修改它。
- [runs/confirm/analysis.json](runs/confirm/analysis.json)：主结果。

从项目根运行：

```powershell
py -3.13 experiments/b_q3/adaptive_second/run.py --stage confirm --samples 16 --workers 6 --out experiments/b_q3/adaptive_second/runs/confirm_rerun
py -3.13 experiments/b_q3/adaptive_second/diagnose.py experiments/b_q3/adaptive_second/runs/confirm_rerun
```

Python3.13；策略核心用标准库，分析区间用numpy。既有依赖直接导入相邻实验目录，需保持manifest记录的文件版本。

测试：`test_adaptive.py`（8项）、`test_posterior_edges.py`（3项）、`test_online.py`（1项，读取已保存pilot决策，测试流式接入轨迹）。

只含自建仿真，不提供官方测试入口。全部概率分布为工作假设；当前选择计算平均171.5秒，在并发负载下测得，尚不适合直接宣称实时部署。
