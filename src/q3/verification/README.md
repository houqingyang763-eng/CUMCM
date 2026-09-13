# 原测试与冻结运行脚本

`original/`保存原F3的12项测试、轻量方法6项测试、挪站5项测试，以及本次普通24例的原运行、分析和绘图脚本。文件内容未变。

现行测试入口为[verify_runtime.py](../verify_runtime.py)，它将必要代码和测试输入按旧路径放入临时目录，运行原测试后清理。不要直接在搬迁后的`original/`路径执行旧脚本，它们内部的原路径本身也是冻结记录的一部分。

```powershell
py -3.13 -B experiments/b_q3/final_methods/verify_runtime.py
```

[运行校验记录](../../../outputs/experiments/b_q3_organization_20260913/runtime_validation.json)保留每组测试的完整输出。历史结果完整性由[verify_organization.py](../../exploration/q3/verify_organization.py)单独核验，不需要重新跑24局。
