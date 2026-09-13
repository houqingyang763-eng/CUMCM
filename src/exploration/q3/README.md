# 第三问：最终整理入口

第三问已按用途分为两个文件夹。原实验文件全部保留，F3与F3改的算法和实验成绩没有改动。

| 文件夹 | 放什么 | 从哪里开始 |
| --- | --- | --- |
| [最终方案 final_methods](final_methods/README.md) | F3、F3改、必要公共代码、运行接口、F3原始证据与最终对比入口 | 当前用于最终整理的两个方案 |
| [其它路径尝试 other_attempts](other_attempts/README.md) | 其它模型路线、失败实验、开发过程、团队规划、AI综述和理论诊断 | 回溯试过什么、为什么保留或停止 |

当前结论仍是：F3为对照主方案；F3改完整24例没有显示出明确优势，作为比较方案保留。“最终方案”是本次文件归类，不改写这一结论。

## 常用入口

- [F3](final_methods/F3/README.md)
- [F3改](final_methods/F3_modified/README.md)
- [两方案普通24例比较](../../outputs/experiments/b_q3_p1/f3_modified_micro24_20260913/REPORT.md)
- [比较图](../../outputs/experiments/b_q3_p1/f3_modified_micro24_20260913/comparison.png)
- [整理记录与旧路径查询](ORGANIZATION.md)

在项目根目录执行：

```powershell
py -3.13 -B experiments/b_q3/final_methods/runtime.py --check
py -3.13 -B experiments/b_q3/final_methods/verify_runtime.py
py -3.13 -B experiments/b_q3/verify_organization.py --check-links
```

第一条只检查导入和策略构造；第二条运行原有23项测试；第三条核对搬迁文件、冻结指纹、24例旧轨迹计费和新导航链接。均不启动官方模拟器或新整局实验。
