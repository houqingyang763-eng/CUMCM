# 第四问从研究代码到正式代码的迁移

状态：迁移核验完成，后续正式24例确认和8例压力试验均全清；团队人工审核尚未由本次自动检查代替。迁移不修改任何 `experiments/` 文件；这是研究到正式分析的生命周期迁移，不以副本保存算法版本历史。

## 改动范围与不变部分

`candidate.py`、`belief.py`、`planner.py`、场景生成器以及主要几何、状态、仿真模块保留原算法。`SelectedPolicy` 新增唯一参数入口，明确指定shared25，避免构造器研究默认值被误当作正式选择。当前明确关闭cap顺扫与完整rollout；候选研究能力仍保留供本地支撑对照。

`common.bootstrap()` 仅加入相邻 `core/`。`task_cost.py` 和 `coverage.py` 删除历史路径注入。`q2_geometry.py` 不再动态加载旧目录几何，只晋升 `reception_certificate` 和 `guaranteed_reception` 两个实际必需的纯函数；不迁入其历史CLI。`route_dp.py` 只保留整数开放路径所需常量与两个纯函数，不包含真值oracle求解或旧批次入口。上述保留函数单独作AST等价核对。

公开客户端迁入 `core/public_client.py`。演练入口只读正式配置，保留实际UI核对、120秒证据新鲜度、单次消费、零重试、公开计费审计和脱敏记录。官方正式测试模式仍拒绝。输出根统一为 `outputs/q4`。

运行器与演练适配器记录实际本地依赖及已知延迟导入的 `planner.py`，同时记录 `selected_config.json`。发现本仓库目录外代码混入时拒绝继续；不把正在开发但未参与运行的制图、报告模块纳入策略运行指纹。

## 验证口径

四个固定smoke场景分别运行研究代码和晋升代码，对B0及shared25逐动作比较 `kind`、`position`、`channel`、`reason` 与公开响应，排除非确定的现实耗时字段；要求动作序列、虚拟时间、清除数、独立计费与全清结果一致。两边分别在全新Python进程中加载，避免同名模块互相污染。来源文件与完整配置同时冻结，结果留在 `outputs/q4/migration_smoke`。

接口、状态、独立计费、模拟HTTP故障、收据边界与正式配置检查从本目录独立运行。迁移比较读取旧来源仅用于一次等价审计；`run.py`、`practice.py` 和正式策略运行不依赖旧来源存在。

下表与精确源指纹见 [migration_sources.json](migration_sources.json)。后续算法改动通过Git与新的运行清单记录；此文件中的源指纹是迁移时的事实，不随研究文件继续发展而改写。

| 原文件 | 正式文件 | 迁移变化 |
|---|---|---|
| `experiments/b_adaptive_q3/geometry.py` | `src/q4/core/geometry.py` | 逐字节晋升；计算逻辑不变 |
| `experiments/b_adaptive_q3/state.py` | `src/q4/core/state.py` | 逐字节晋升；计算逻辑不变 |
| `experiments/b_adaptive_q3/policy.py` | `src/q4/core/policy.py` | 逐字节晋升；计算逻辑不变 |
| `experiments/b_adaptive_q3/simulation.py` | `src/q4/core/simulation.py` | 逐字节晋升；计算逻辑不变 |
| `experiments/b_overnight/q4.py` | `src/q4/core/q4.py` | 逐字节晋升；计算逻辑不变 |
| `experiments/b_overnight/q4_coverage.py` | `src/q4/core/q4_coverage.py` | 逐字节晋升；计算逻辑不变 |
| `experiments/b_overnight/q4_joint_state.py` | `src/q4/core/q4_joint_state.py` | 逐字节晋升；计算逻辑不变 |
| `experiments/b_overnight/task_cost.py` | `src/q4/core/task_cost.py` | 移除旧目录Path/sys.path配置；全部类与函数AST保持不变 |
| `experiments/b_overnight/coverage.py` | `src/q4/core/coverage.py` | 移除旧目录Path/sys.path配置；全部类与函数AST保持不变 |
| `experiments/b_overnight/q2_geometry.py` | `src/q4/core/q2_geometry.py` | 仅保留reception_certificate、guaranteed_reception，AST不变；几何底座改本地静态导入；不迁移CLI或其他无关定义 |
| `experiments/b_oracle_q3/oracle.py` | `src/q4/core/route_dp.py` | 仅保留SCALE、INF、distance_floor、shortest_open_path；函数AST不变；去除真值接口与历史运行入口 |
| `experiments/b_env_probe/client.py` | `src/q4/core/public_client.py` | 逐字节晋升；计算逻辑不变 |
| `experiments/q4/common.py` | `src/q4/common.py` | bootstrap只加入本地core；类与常量计算逻辑不变 |
| `experiments/q4/candidate.py` | `src/q4/candidate.py` | 逐字节晋升；计算逻辑不变 |
| `experiments/q4/belief.py` | `src/q4/belief.py` | 逐字节晋升；计算逻辑不变 |
| `experiments/q4/planner.py` | `src/q4/planner.py` | 逐字节晋升；计算逻辑不变 |
| `experiments/q4/cases.py` | `src/q4/cases.py` | 逐字节晋升；计算逻辑不变 |
| `experiments/q4/analyze.py` | `src/q4/analyze.py` | 逐字节晋升；计算逻辑不变 |
| `experiments/q4/baseline.py` | `src/q4/baseline.py` | 路线DP改为本地core/route_dp；全部类和函数AST不变 |
| `experiments/q4/run.py` | `src/q4/run.py` | 正式输出根改outputs/q4；固定selected入口与本地依赖清单 |
| `experiments/q4/practice.py` | `src/q4/practice.py` | 正式输出根改outputs/q4；本地公开客户端与固定selected入口；收据/协议边界不变 |
| `experiments/q4/test_practice.py` | `src/q4/test_practice.py` | 逐字节晋升；计算逻辑不变 |
| `experiments/q4/test_runner.py` | `src/q4/test_runner.py` | 移除依赖历史文件的AST测试；其余6项接口/状态/审计测试保持原样，迁移AST另单独记录 |
| `experiments/q4/verify_practice.py` | `src/q4/verify_practice.py` | 原样迁移；不读取隐藏案例，核对当前官方终局记录 |

新增文件为selected.py、selected_config.json、test_selected.py及本目录说明；分别提供唯一正式入口、全量参数、配置与依赖封闭性检查。

核验结果：[迁移报告](../../outputs/q4/migration_smoke/REPORT.md)。8对完整轨迹均一致，共2768动作；独立临时部署的18项检查通过。迁移审计本身未连接真实官方接口；后续确认、压力和迁移前同配置官方演练见[交付报告](../../outputs/q4/delivery01/REPORT.md)。研究和正式目录同一24例的复算不增加独立场景数。
