# 第四问正式代码入口

整理说明（2026-09-13）：后续A/B小改未采纳，本目录当前算法与配置保持shared25。全目录状态、研究归档与大整理注意事项见[Q4交接说明](../../experiments/q4/HANDOFF.md)。

状态：本轮交付方案已固定，迁移一致性核对、正式代码24例确认及8例压力检查均完成。32个不同案例、416源全部清除；本目录的18项接口、状态和配置检查通过。机器核验不代表参赛团队已完成人工审阅。

当前唯一选定策略为 `shared25`：25点可靠发现，位置条件定向评分，共享站替换，认证二至三圆清除；不启用完整rollout，不启用16源上界顺扫试探。所有实际参数保存在 [selected_config.json](selected_config.json)，`SelectedPolicy` 仅从此文件读取。后续正式改变须修改这一处并新建结果批次。

结果入口：[交付报告](../../outputs/q4/delivery01/REPORT.md)、[逐轨迹退步诊断](../../outputs/q4/diagnostics01/REPORT.md)。确认集514.84秒/源，B0为588.79、joint25为563.04；压力集510.73秒/源，B0为629.71、joint25为526.20。均为同案例全清后逐局T/N均值，不是官方隐藏成绩。shared25迁移前同配置已完成单局官方演练13/13源、462.51秒/源；[真实终局核验](../../outputs/experiments/q4/practice_shared01/verified_summary.json)。

## 本地运行与检查

要求Python 3.13；只使用标准库。算法、几何、模拟环境和公开HTTP客户端全部位于本目录，不导入研究目录或历史运行器。仓库根目录执行：

```powershell
py -3.13 -X utf8 src/q4/run.py --split smoke --output outputs/q4/replay_smoke
py -3.13 -X utf8 src/q4/run.py --split holdout --policies baseline joint25 selected --output outputs/q4/replay_holdout --workers 3
py -3.13 -X utf8 src/q4/run.py --split pressure --policies baseline joint25 selected --output outputs/q4/replay_pressure --workers 3
py -3.13 -X utf8 -m unittest discover -s src/q4 -p "test_*.py" -v
```

默认只运行 `selected`。`baseline` 是先完成发现后逐源处理的B0；`joint25`是既有强对照。`candidate`及显式模块映射只用于本地研究对照，允许 `--config-json` 按策略名提供参数；`selected` 拒绝这种覆盖，始终读取唯一正式配置。

每个批次写入 `outputs/q4/<批次>`。运行器保存场景、配置、依赖源码及SHA256、逐条动作与反馈、独立计费、最终公开状态和结果。`--resume` 要求源码、参数、案例、时限与Python完全一致；失败和中断记录保留。源真值只交给本地环境与独立审计器，不交给在线策略。

## 报告和论文图

报告从正式结果生成。4张图同时输出PNG与PDF，分别为主指标、成本分解、配对散点和固定首例路线；图中源位置只在运行结束后显示。制图另需`requirements-figures.txt`中的matplotlib，求解器不依赖它。本机已在忽略的`.venv-q4`中安装。

```powershell
py -3.13 -m venv .venv-q4
& ./.venv-q4/Scripts/python.exe -m pip install -r src/q4/requirements-figures.txt
& ./.venv-q4/Scripts/python.exe -X utf8 src/q4/figures.py --holdout outputs/q4/holdout01 --pressure outputs/q4/pressure01 --output outputs/q4/replay_figures
py -3.13 -X utf8 src/q4/report.py --holdout outputs/q4/holdout01 --pressure outputs/q4/pressure01 --practice outputs/experiments/q4/practice_shared01/verified_summary.json --output outputs/q4/replay_report
```

输出目录必须尚不存在。生成报告链接到本轮固定的模型说明、诊断和图目录；若建立新的算法版本或整套结果，应同步检查这些导航。正式确认清单中的源码指纹才是运行时版本，迁移清单另描述迁移当时的来源。

## 官方演练

先实际观察当前官方界面，核对“问题4、演练测试、案例代码”，将真实截图或本对话工具结果引用写入当次收据；格式见 [practice.py](practice.py) 开头。程序只验证证据记录的完整性、新鲜度和单次消费，不能把填写字段本身当作官方模式证明。

队号仅通过 `CUMCM_ROBOT_ID` 环境变量提供，不写入命令参数、代码或输出。实际进入前120秒内的收据仅可使用一次。

```powershell
py -3.13 src/q4/practice.py --receipt <本次实际UI收据.json> --output outputs/q4/practice01
py -3.13 src/q4/verify_practice.py outputs/q4/practice01 --ui-result outputs/q4/practice01/ui_final_observation.json
```

演练入口固定使用 `selected_config.json`，没有切换策略或覆盖算法参数的CLI选项。HTTP严格本机回环、串行、零重试；未知请求结果、坏计费或拒绝响应立即停止。正式测试模式一律拒绝。每一次问题4正式测试仍须用户明确授权，本代码不启动官方测试或操作界面。

程序全清证书与实际官方终局分开记录；完成后须实际查看官方总源数和正常退出状态，再运行终局核验。终局观察须来自真实界面，核验工具不生成或猜测这些字段。

## 模型、来源与迁移证据

模型草案只维护在 [experiments/q4/MODEL.md](../../experiments/q4/MODEL.md)，这里不再复制正文。题面入口为 [B题.md](../../problem/B题.md) 与 [附件2.md](../../problem/附件2.md)。

[MIGRATION.md](MIGRATION.md) 记录逐文件来源、裁剪与路径调整；[migration_sources.json](migration_sources.json) 保存来源与晋升文件指纹。迁移一致性证据见 [REPORT.md](../../outputs/q4/migration_smoke/REPORT.md)：4场景×2策略共8对、2768动作一致，每边每策略55/55源全清；无其他仓库目录的独立临时部署通过18项测试。这是实现等价核对，不是算法独立性能确认。算法版本历史由Git管理，不创建其他“最终版”代码副本。
