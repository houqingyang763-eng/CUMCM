# 最终整理：F3与F3改

| 方案 | 用途 | 核心源码 | 普通24例结果 |
| --- | --- | --- | --- |
| [F3](F3/README.md) | 对照主方案 | [refined.py](F3/refined.py) | 平均55.756分钟/局，259.675秒/源 |
| [F3改](F3_modified/README.md) | 保留对比方案 | [light_route.py](F3_modified/light_route.py)、[relocate.py](F3_modified/relocate.py) | 平均55.625分钟/局，259.138秒/源 |

两者均24/24全清。F3改平均仅省7.810秒/局，新增16例反而慢46.387秒/局，本轮不支持替换F3。[完整结果](../../outputs/experiments/b_q3_p1/f3_modified_micro24_20260913/REPORT.md)；每源数值是每局T/N再等权平均。

## 文件分工

- `F3/`：F3原核心文件、说明和69条不同历史批次的F3轨迹。主比较只使用其中micro_confirm的24例，不把69条记录当作69次独立确认。
- `F3_modified/`：F3改的两个原算子文件、冻结设计和最终证据入口。
- [_core/](_core/README.md)：两个方案共用的开局选择、几何状态、覆盖路线及配置。
- [runtime.py](runtime.py)：统一运行接口。按搬迁清单读取原字节，在系统临时目录恢复原依赖结构，退出后清理临时文件。归档原件不会被改写。
- [verification/](verification/README.md)：原测试、原24例运行/分析脚本的冻结原件。
- [verify_runtime.py](verify_runtime.py)：迁移后调用原测试的现行入口。

4个第三问目录外的公共底层文件仍留在原位置，避免影响其他研究：`experiments/b_adaptive_q3/{geometry,simulation,state}.py`和`experiments/b_overnight/coverage.py`。这里只使用其中的几何覆盖模块，不运行历史保护程序；依赖指纹由统一入口校验。

## 使用策略接口

将本目录加入Python导入路径后：

```python
from runtime import runtime

with runtime("F3") as session:  # 或 "F3_modified"
    policy, state = session
    action = policy.choose(state)
    # 把action交给环境，再用真实公开反馈调用state.update(action, response)。
    # 持续在同一个with作用域中完成整局，不要每一步重新创建策略。
```

`selected=None`沿用原F3根据第一站公开反馈选择第二站的逻辑；已有同案公开历史缓存可通过`selected`传入。F3改固定启用A与10次二分挪站，未启用B或换侧删站。现实耗时上限可通过`deadline=time.perf_counter()+秒数`传入。

原文件仍包含早期F1/F2/F4或B开关的共用实现，保留这些代码是为了保持历史字节；统一接口仅构造F3与F3改。该目录是研究方案整理入口，本次没有迁移到`src`或修改正式提交代码。
