# Q3 三人并行实验交接

更新：2026-09-13。

## 先给接手的人看

我们已有能完整运行的F3，还想减少第三问整局清除时间。现在拆为“怎么安排路线、哪些补测值得做、开局两点怎么选”。用户负责方向一；队友A负责方向二；队友B负责方向三。三人从同一F3出发，各做小组合对照，再汇合有效改动。

这不是让队友重新读24种方法，也不只有三个设置：共有 **2＋3＋2＝7个候选**。历史成绩只是线索，是否采用看本次同案全清总耗时。本次交付设计、案例索引、代码依赖和启动检查；候选仍需接手者实现。

## 取得共同版本

- 仓库：`https://github.com/houqingyang763-eng/CUMCM`
- 交接分支：`handoff/q3-parallel-20260912`。收到队长提供的固定提交号时按该提交取代码，不追随后来的分支移动。
- 基础实验快照：`d3ef0e09f3f290e8a6322c437fc06098115278ed`。本交接在该快照上补充共享材料，F3行为不作优化。
- 上游`MrRoam/CUMCM`不是本次落点；只拉上游main可能缺材料。此次使用fork任务分支，未宣称合入上游。

已有仓库先检查分支、工作区和remote；有未提交成果则保留并另开worktree，不能reset、自动stash或覆盖。没有仓库可clone交接分支。方向二建议新建`experiments/q3-p2-measurement`，方向三建议`experiments/q3-p3-opening`；同名已存在先检查。

接手Codex先读根目录`AGENTS.md`、`problem/B题.md`的问题三与设备条件、本文件和本方向入口，再向队员简明解释“为什么做、我负责什么、交什么”，随后直接开展已分配的设计、实现和自建本地实验。无需恢复历史额度保护或启动guard。官方问题3/4正式测试仍须逐问逐次授权。

## 共同起点

| 项目 | 统一约定 |
| --- | --- |
| B0 | `experiments/b_q3/refinement/refined.py`，`RefinedPolicy(selected, level=3, samples=4)` |
| 配置 | `experiments/b_q3/probability_patrol/configs/r3_covering.json`及原策略默认值 |
| 开局 | 从原点、频道1开始；原首测点`(-129.903811,-75.0)`米；第二点按首站公开反馈选，不强行替换成配置默认点 |
| 缓存 | P1/P2沿用各案例原`selection.json`；P3改首点后必须重算新历史，不能沿用旧选择 |
| 预演 | 后续4场景，第二站旧选择16场景；原F3内部采用F1非递归续行近似，并未完整复制未来在线选择 |
| 案例 | [team_screening_manifest.json](team_screening_manifest.json)，历史micro_confirm索引0、3、6、9、12、15、18、21 |
| 单位 | 秒、米、角度；移动5米/秒，检测5秒，换频1秒，失败清除3秒，成功清除5秒。清除不改变测向机频道 |
| 本地限制 | 3000动作、1200秒现实软限、10800秒虚拟限；这是实验限制，不是题面虚拟时限。驱动外预计算开局也要单列用时 |
| 保留 | 实际公开反馈、连续覆盖终止证明、F1、多圆认证和成功即停；真值只给环境与事后评估 |
| 排除 | F4独立复查、多步信念树、W/G、参数网格、本轮官方正式测试 |

八例覆盖四布局、smooth/biased误差、10—16源，与P1已有设计一致。它们都是看过的开发案例；hashed及未见种子留待最终确认。B0历史结果兼容时复用；旧电脑的wall_s不能用于证明新代码更快，要比较现实速度需本机重跑。

从仓库根目录运行检查，Windows推荐Python 3.13，其他系统用同版本python：

```powershell
py -3.13 experiments/b_q3/cross_method/prepare_team.py --check
```

此命令核对文件、案例、F3依赖指纹、旧结果和独立账本，尝试导入策略；不运行策略、不调用官方接口。指纹按Git的LF换行核对，差异必须解释，不能重盖清单绕过检查。

旧p1_screening_manifest.json保留最初本地字节审查记录；Git可能转换换行，跨电脑以team_screening_manifest.json及本检查为准，不改写旧审查记录。state.py在交接中仅补齐历史末尾空行，已核对Python语法树不变。

例如方向二准备新输出目录：

```powershell
py -3.13 experiments/b_q3/cross_method/prepare_team.py --out outputs/experiments/b_q3_p2/first_screen
```

输出cases.json、B0旧结果引用表与baseline_selection/。目录必须不存在；仅准备输入，不声称已经运行候选。方向一、三分别改为b_q3_p1、b_q3_p3，下一批换新run-id。

## 方向一：用户负责路线，两个设置

P1a_channel_route：逐频道检查接入共同路线；P1b_joint_tasks：在其上加入完整清除序列、内部费用和可能成功落点。参考[P1设计](P1_EXPERIMENT_DESIGN.md)、[共同路线](../probability_patrol/covering_route.py)、[逐频道路线](../clearability/channel_route.py)。P1旧设计的“一个完整候选”现归P1b，P1a是同框架下保留原多圆路线表达的对照；本交接覆盖旧文的数量和执行顺序，保留其几何设计。

代码写`experiments/b_q3/cross_method/p1/`。不能把多圆首点当整项任务，也不能把未来计划当实际阴性证据。两设置尽量共用新续行框架；额外差异如实记录，不能声称只隔离了一个零件。其他两方向不等待P1结果。

## 方向二：队友A负责测量取舍，三个设置

问题：一次补测是否值得；靠边测点是否把覆盖浪费到区域外。比较：

1. P2a_utility：一个改进的可清除效用规则，仅筛可选的已知源共享补测。
2. P2b_boundary：只有边界惩罚，显式strength_s=60。
3. P2c_both：与P2a完全相同的效用＋与P2b完全相同的边界强度。

阅读[隔离实验](../clearability/ACTIVATION_ONLY.md)、[activation_only.py](../clearability/activation_only.py)、[boundary_policy.py](../boundary_penalty/boundary_policy.py)、[边界报告](../boundary_penalty/REPORT.md)。旧线性略胜Sigmoid，不能只因Sigmoid像“激活函数”就优选它。完整S4曾退步，不直接搬入。

代码写`experiments/b_q3/cross_method/p2/`。先设计一版效用并写清定性含义、输入、失败回退，再固定三个设置。共用F3候选测点、开局、后验样本、续行器和预算；不同时加新测点、换路线或调多种强度。必要查漏、初始扫描、主目标测量不受可选补测门控删除；边界惩罚只排名，不计入真实耗时，不惩罚清除。

重点看：删掉一次检测是否后来多走路；叠加是否比单项差；两规则是否重复压低有用测量。两个类可能作用于不同钩子，显式组合并检查执行次序，不能靠多重继承假设两机制都生效。预演中没有新门控的近似要记录，不顺手改成另一套F3。

## 方向三：队友B负责开局，两个设置

P3a_fixed：事前选出可解释的新第一点、固定第二点。P3b_adaptive：与P3a共用第一点，第二点依据真实首站公开反馈选择。两者分别与原B0比较。

阅读[两点报告](../probability_patrol/REPORT.md)、[第二站报告](../adaptive_second/REPORT.md)、[adaptive.py](../adaptive_second/adaptive.py)。代码写`experiments/b_q3/cross_method/p3/`。

依据用人话说：先花多少移动、扫描和切频费用，收到反馈后还要花多少清除与查漏费用。交会角、发现数用于解释，不随意加权取代总耗时。用少量有解释的布局和单独记录的事前设计场景选点，不能读筛选八例真值挑点。记录点集、事前种子和计算成本，不展开半径/角度/频道网格。

重要限制：negative_mass对首点距原点≤300米才适用，本轮优先保留这个范围；扩到外侧必须先修正任务边界裁切及条件采样。a.first_state(case)固定用旧开局，只供B0评估；新开局要由环境执行新首站动作，返回公开状态供策略选择。selected不能含真值。首点改变后旧history_seed/selection.json无效；全阴性、第二站选当前点或空频道时仍须能合法继续。

后续路线、清除、补测、边界都保持原F3。不混入P2新门控，也不增加频道子集、起搜点数或树搜索。

## 接口、交付与汇合

各自仅在本方向目录写策略、运行器和说明，数值/图片/动作日志写`outputs/experiments/b_q3_p1|p2|p3/<run-id>/`。共享F3、模拟器、案例、清单只读。公共接口有需求先在本目录适配并记录整合建议，不覆盖他人文件。

运行可参考refinement/postcheck.py::task，复用probability_patrol/runner.py::execute_case的动作核验及独立计费；不要照抄默认生成24例或旧summarize的参照，应使用本清单八例与B0_f3。临时替换base.create_policy时单进程串行、finally恢复；并行用独立进程，禁止线程共享可变factory。旧缓存需核对首站历史，准备脚本把它放baseline_selection就是为了避免P3误读。

策略只收公开state，返回kind=measure|clear、position=[x,y]、channel；完成须state.complete，未完成却无动作视为失败。结果沿用success、cleared、real_n、total_s、per_source_s、failreason；失败保留per_source_s=null，不能把未完成时间当更快。先全清再比总时间和逐局T/cleared的均值。

每人交一份RESULTS.md及程序生成的summary.json，链接每个候选逐局结果、动作日志、配置/代码提交/种子。至少包含：

- 全清情况、均时、每源均时、相对B0节省（B0减candidate，正数更好）、胜负平、最大退步；保留失败。
- 移动/检测/切频/清除分解和最后成功清除后的查漏时间；查漏段与动作费用重叠，不能再次相加。
- 最值得保留、最差退步案例各一张配对轨迹图，指出首次关键分歧；无退步则如实说明。
- 推荐本方向哪个小设置、是否值得组合、有哪些干扰。没有收益也交完整结论，不无限追加组合。
- 现实时间单列，包括离线及首站选点成本；历史旧电脑用时不能作为配对速度证据。

可以先单例查明显错误，再完成八例；调试换新run-id，不能静默覆盖。三方各自完成后交用户汇合；至多两次有理由的集成，再冻结一个完整候选做全新12例确认，数量详见[矩阵](METHOD_COMBINATION_MATRIX.md)。不预设组合收益等于单项相加。

各自更新本方向记录以及AI使用/决策所需的小节，不重排公共文档。结果提交本方向分支，反馈分支、提交号和结果入口，不推main或共享交接分支；没有权限则先完成可提交材料并说明真实交付状态。
