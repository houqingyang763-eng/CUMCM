# 2026-09-13：为最终整理归组

用户要求：F3、F3改放一个文件夹，其它路径尝试放另一个文件夹。本次实际操作范围为`experiments/b_q3`；没有删除旧实验，没有改变算法或重跑整局。

## 当前布局

```text
b_q3/
├─ final_methods/
│  ├─ F3/                 原核心文件、F3历史轨迹、说明
│  ├─ F3_modified/        原轻量与挪站算子、冻结设计、结果入口
│  ├─ _core/              公共原代码与配置
│  ├─ verification/       原测试和原24例运行分析脚本
│  ├─ runtime.py          统一运行接口
│  └─ verify_runtime.py   原23项测试的现行入口
├─ other_attempts/        其余原路线、开发过程、综述与诊断
├─ README.md
├─ ORGANIZATION.md
├─ organization_manifest.json
└─ verify_organization.py
```

## 搬迁原则与证据

- 原4713个文件、254338224字节全部逐文件记录旧路径、新路径和SHA256，见[完整清单](organization_manifest.json)。原文件字节不改，不用重新计算的指纹覆盖实验时指纹。
- 原`refinement/refined.py`移到`final_methods/F3/`；原`cross_method/p1/{light_route,relocate}.py`移到`final_methods/F3_modified/`。其它公共运行输入移到`final_methods/_core/`。
- 原F3的69个结果子目录及已有案例输入、开局缓存移到`final_methods/F3/evidence/`，按原批次分开；其它方法的同批结果仍在`other_attempts/refinement/runs/`。完整成绩解释以各原批次为准。
- 原根README和ORGANIZATION保留在`other_attempts/_previous_navigation/`，其余历史目录整体进入`other_attempts`，再抽出上述最终方案原件。
- `outputs/experiments/b_q3_p1/`中的原结果批次没有搬走，也没有复制；最终方案提供直接入口。F3改普通24例继续引用原8例加新增16例，完整保留来源链。
- Q3目录外4个公共几何/环境文件保留原址，并记录当前指纹。未影响第四问代码或官方原件。

## 为什么使用统一运行入口

旧脚本通过`__file__.resolve().parents[...]`寻找原工程，并严格校验冻结文件。新[runtime.py](final_methods/runtime.py)先用清单找到原件、校验SHA256，再把仅需的12/14项输入复制到系统临时目录中的旧工程形状。策略在同一个上下文中执行，退出后清理临时副本。没有维护第二套算法版本，也没有修改原算法以迁就目录。

历史脚本与文档保留原路径，不承诺它们在新物理位置可以直接启动。最终策略使用统一接口；测试使用`verify_runtime.py`；旧结果核验使用`verify_organization.py`。

## 查询旧路径

```powershell
py -3.13 -B experiments/b_q3/verify_organization.py --resolve experiments/b_q3/refinement/refined.py
```

此命令只显示当前文件位置，不执行旧脚本。也可按旧路径在`organization_manifest.json`查询。

## 校验

```powershell
py -3.13 -B experiments/b_q3/final_methods/verify_runtime.py
py -3.13 -B experiments/b_q3/verify_organization.py --check-links
```

第一条重用原F3 12项、轻量6项、挪站5项测试。第二条核对4713个原文件及4个外部依赖、最终24例的冻结文件与48条日志计费，并检查新导航的本地链接。

完整记录：[目录与旧结果校验](../../outputs/experiments/b_q3_organization_20260913/validation.json)、[原测试输出](../../outputs/experiments/b_q3_organization_20260913/runtime_validation.json)。验证由AI/程序执行，本次未声称团队已人工审核，也未改`src`或发布Git。
