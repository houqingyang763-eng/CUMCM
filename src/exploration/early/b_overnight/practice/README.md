# 夜间策略的公开 HTTP 演练适配

状态：**本夜 Q3 Completion、Q4 joint25、Q3 Sweep 已各完成一局真实官方演练，分别核验 12 / 12、12 / 12、11 / 11 源全清。** 新增的 PowerShell 入口和 Sweep 接线也已通过本地替身与 HTTP 假服务检查；默认策略保持不变。

本目录复用 `experiments/b_env_probe/client.py` 的 `RobotClient`，不重造传输层。新增 `PracticeClient` 只补充串行控制、完整公开限时字段、独立计费核对和日志脱敏；冻结策略不作修改。

## 已核验的真实官方演练

| 问题 / 策略 | 官方源数 / 实际清除 | 总虚拟时间 / s | 每源平均 / s | 现实时间 / s |
|---|---:|---:|---:|---:|
| Q3 Completion | 12 / 12 | 4206.73 | 350.56 | 3.64 |
| Q4 joint25 | 12 / 12 | 7745.54 | 645.46 | 5.74 |
| Q3 Sweep | 11 / 11 | 4197.60 | 381.60 | 1.73 |

来源为[脱敏核验记录](../runs/official_practice/verified_results.json)：源数从实际结束 UI 核对，全清由不同频道的成功回执与官方源数共同核验；Q4 含 7 个全向源、5 个定向源。这是三个不同案例的单局演练，不是正式成绩，也不是策略间的配对性能比较。Q3 Sweep 共 129 个动作、131 个请求，无重试、无失败清除，独立账本核对通过。各局对应冻结接口源码与私有 UI/日志证据散列保存在该记录中；本地检查与真实官方运行分别留证。

## 已支持的策略

| 问题 | --strategy | 实际策略 / 信息状态 | 配置 |
|---|---|---|---|
| 3 | completion（默认） | CompletionCostPolicy / InformationState | 冻结默认参数 |
| 3 | configured | CompletionCostPolicy / InformationState | 必须显式提供 selected_config.json 等配置 |
| 3 | sweep（显式候选） | Q3SweepPolicy / InformationState | CompletionCostConfig；默认仍是 completion |
| 4 | joint25（默认） | Q4Symmetric25Policy / Q4JointCoverageInformationState | Q4Config 默认参数或显式覆盖 |
| 4 | directional | Q4DirectionalPolicy / Q4InformationState | Q4Config 默认参数或显式覆盖 |

不提供正式测试入口，也不通过代码切换官方测试模式。问题与策略不匹配时直接拒绝。

`joint25` 与 `q4_compare.py` 的同名工厂完全对齐：25 点可靠发现策略配连续覆盖证书与位置—方向联合外包状态。Q4 的 `no_signal` 仍不能按 Q3 方式删去整个 1000 m 接收圆。Python 接口为 `strategy(3)` 或 `strategy(4, "joint25")`，返回 `(policy, state)`；省略名称时 Q3 仍为 Completion，Q4 为 joint25。

## 模式证据与许可分开

用户已授权本任务演练，不再追加用户确认或口令。`live.py` 要求的是 **AGENTS.md 指定的当前实际官方 UI 证据**：获授权的操作者（人或代理）先实际查看当前官方界面，确认“演练测试”、问题号和案例编码，再提交核验收据。

HTTP 公开协议不返回演练/正式模式。端口开放、某个命令行布尔值或自己填写“演练”文字，都不能替代实际看过界面。代码检查收据字段、120 秒新鲜度、PNG/JPEG文件签名、截图散列和单次消费；**它不识别截图内容，画面语义由实际操作者核验**。不要把收据格式通过称为自动证明了官方模式。

收据字段示例，所有尖括号都必须由本次实际观察填写；不要把该示例当作已经获得的证据：

```json
{
  "observed_at_utc": "<本次实际观察的带时区时间>",
  "problem": 3,
  "case_code": "<当前演练案例编码>",
  "mode_visible_text": "演练测试",
  "window_title": "<实际官方窗口标题>",
  "screenshot_path": "<实际截图绝对路径>",
  "screenshot_sha256": "<该截图的SHA256>",
  "review_note": "<在当前实际画面中核对模式、问题号和案例的记录>",
  "port": 2026
}
```

建议收据与截图放在本目录被忽略的 `local_evidence/`。截图只用于当前模式核验，不把队号或凭据写入可提交成果。收据在 `/enter` 前原子消费一次，即使网络结果不明也不自动重新进入。再次进入必须重新观察当前界面取得新收据；这不是要求再次向用户索取演练许可。任何正式测试仍需用户针对该次、该问题单独明确授权，本驱动不承担正式入口。

## 已获授权演练的运行方式

推荐新手使用 `run_practice.ps1`。在仓库根目录，完成当前真实 UI 核验、演练已由获授权操作者启动并开放接口后，运行一条对应命令即可：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File experiments/b_overnight/practice/run_practice.ps1 -Problem 3 -UiReceipt experiments/b_overnight/practice/local_evidence/current.json -Output experiments/b_overnight/practice/local_runs/new_q3_case

powershell -NoProfile -ExecutionPolicy Bypass -File experiments/b_overnight/practice/run_practice.ps1 -Problem 4 -UiReceipt experiments/b_overnight/practice/local_evidence/current.json -Output experiments/b_overnight/practice/local_runs/new_q4_case

powershell -NoProfile -ExecutionPolicy Bypass -File experiments/b_overnight/practice/run_practice.ps1 -Problem 3 -Strategy sweep -UiReceipt experiments/b_overnight/practice/local_evidence/current.json -Output experiments/b_overnight/practice/local_runs/new_sweep_case
```

省略 `Strategy` 时，问题3用 Completion，问题4用 joint25。`configured` 必须另加 `-Config <平面参数JSON文件>`。`ExecutionPolicy Bypass` 仅作用于这次 PowerShell 进程，不修改机器的持久执行策略。

入口自动从 `%LOCALAPPDATA%/CUMCM/jammers-credential.clixml` 导入当前用户已有的 Windows DPAPI 凭据，只取 `UserName`，不取出明文密码。队号通过短生命进程环境传给 Python，不进入命令行；无论成功、Python 非零退出或启动异常，`finally` 都恢复原有 `CUMCM_ROBOT_ID`，原先没有则移除。Python 退出码原样向上传递；入口自身参数、私有凭据或启动错误返回 2，错误正文不打印凭据内容。

`UiReceipt` 与 `Output` 均必需，输出必须是新路径。脚本不生成收据、不识别截图、不登录或点击官方界面；当前真实模式证明与单次消费仍由原 Python 入口核验。已有演练授权不增加任何口令或新确认，正式测试仍无入口。动作间的 guard、20分钟/100小时保护和重复请求处理全部沿用 Python；STOP 时不自动重试或解除保护。

收据与截图放 `local_evidence/`，真实运行输出放 `local_runs/`；替身测试文件放 `local_launcher_checks/`，均被 Git 忽略。本目录还忽略 `*.clixml`，不要把真实凭据移入可提交源码。PowerShell 检查只使用临时假凭据和明确标注的普通输入文本，后者不是 UI 收据，且从未交给真实 `live.py` 执行。

高级用户也可直接运行以下 Python 入口；此时 `CUMCM_ROBOT_ID` 必须已在当前进程环境内设为已登录队号，不要把实际队号写到命令行、代码或日志：

```powershell
py -3.13 experiments/b_overnight/practice/live.py --problem 3 --strategy completion --ui-receipt experiments/b_overnight/practice/local_evidence/current.json --output experiments/b_overnight/practice/local_runs/one_case

py -3.13 experiments/b_overnight/practice/live.py --problem 3 --strategy configured --config experiments/b_overnight/runs/configuration_search/selected_config.json --ui-receipt experiments/b_overnight/practice/local_evidence/current.json --output experiments/b_overnight/practice/local_runs/one_configured_case

py -3.13 experiments/b_overnight/practice/live.py --problem 4 --strategy joint25 --ui-receipt experiments/b_overnight/practice/local_evidence/current.json --output experiments/b_overnight/practice/local_runs/one_q4_joint25_case
```

示例中的输出目录应替换为本次的新目录。已完成的真实演练以本页核验记录为准，新的运行仍须当前 UI 证据。本轮额度保护保持启用：启动与动作之间检查当前 guard；存在 STOP 时只保存和退出，不自行解除保护。

## 请求、计费与重复动作

请求仅有附件2公开字段：arena_id、robot_id、request_id，以及动作所需 position/channel。不发送内部策略分数、reason 或其它元数据。固定连接回环地址，不经过代理；没有网络服务发现或自动点击官方界面。

继承客户端的幂等行为：每个新动作一个 request_id；仅在网络超时/连接中断时重试，复用原 ID 和完全相同的编码字节。没有并发新动作。假服务在“服务端已执行、响应尚未返回”时强制断线，验证重试不会重复计费。

重试耗尽、HTTP/accepted 拒绝、损坏响应或独立计费差异超过 1 毫秒时，锁定停止，不继续新动作，也不发一个新的 `/exit` 去猜测未知状态。若是本地停止、guard STOP 或时间预留触发，而协议仍健康且尚有现实时间，则主动 `/exit`。测试已经关闭接口时，不事后查询 `/exit` 原因。

`pending.json` 在发动作前记录无凭据的动作参数和 request_id，接受并更新后记录已完成。当前不支持进程崩溃后自动续局：即使猜测动作相同，也不能创建新 ID 重发。已有响应不确定时先核对官方 UI，保留日志。

独立账本使用 5 m/s、测量 5 秒、切频道 1 秒、清除成功 5 秒/失败 3 秒；clear 不改变测向机频道。每步核对响应虚拟时间差，使用浮点秒，允许至多 1 毫秒比较余量。

## 限时与输出

`/enter` 必须返回合法 max_virtual_duration_s、max_real_duration_s、remaining_real_duration_s；使用实际剩余现实秒，不固定假定还有 1200 秒。客户端现实截止时间保守扣除进入请求往返耗时。每次规划前后都检查 10 秒退出预留；最坏下一步费用若会达到虚拟上限，提前退出，上限最多 360000 秒。同步策略计算不能被此驱动强制抢占，但返回后会再检查，超时不继续发动作。

产物包括 config、enter、pending、动作JSONL、去标识化 HTTP 记录、summary、state_evidence，以及完整依赖源码快照和散列。源码在进入会话之前捕获，结束后核对运行期间未变；joint25 的状态类、频道终态、未知频道不存在证据和联合排除统计也落盘。真实官方源数和官方全清结果默认为 null；策略自身结束证据与官方界面结果分别记录，运行后仍需查看官方结果界面，不能自动把策略判断写成官方成绩。

## 本地假服务验证

```powershell
py -3.13 -m unittest discover -s experiments/b_overnight/practice -p test_practice.py -v
py -3.13 experiments/b_overnight/practice/mock_run.py --suite joint25 --output experiments/b_overnight/practice/runs/new_http_joint25_check
py -3.13 experiments/b_overnight/practice/mock_run.py --suite sweep --output experiments/b_overnight/practice/runs/new_http_sweep_check
```

假服务仅绑定本进程随机回环端口并明确拒用 2026，内部使用 LocalEnvironment。它模仿本驱动需要的公开字段、幂等、拒绝和计费；不是官方模拟器的独立复刻，也不代表官方性能。

早期 `runs/http_smoke/` 三局共 39/39 源清除、955 策略动作，均成功 `/exit`；每局故意丢失一次已执行测量的响应，均恰好重试一次且未重复计费。Q3 默认虚拟 4960.57 秒，Q3 configured 3436.48 秒，Q4 directional 13435.50 秒。这三个数只验证接线后的行为与反馈一致，不作为新性能比较。该版11项检查通过；`runs/http_final/` 三局再次取得相同虚拟结果，并保存当时16个相关源文件的快照。

当前 joint25 版13项检查通过，新增默认工厂对齐与 Q4 阴性不误删圆盘检查。`runs/http_joint25/` 完成以下三个 HTTP 整局：

| 本地案例 | 策略 | 全清数 | 动作数 | 虚拟成本 / s | 现实时间 / s | 失败清除 |
|---|---|---:|---:|---:|---:|---:|
| uniform_smooth_42100 | Q3 Completion | 12 / 12 | 179 | 4960.57 | 2.34 | 0 |
| q4_edge_outward_biased_96100 | Q4 joint25 | 14 / 14 | 377 | 7677.53 | 5.01 | 1 |
| q4_uniform_tangent_hashed_96101 | Q4 joint25 | 15 / 15 | 291 | 8067.07 | 5.61 | 16 |

两局 Q4 分别含 9 个朝外定向源与 10 个切向定向源，其余为全向源，半径均为最小 1000 m。每局在服务端已经执行第一条测量后故意丢失响应，客户端恰好重试一次：路径、请求 ID、请求编码字节 SHA256 完全相同，服务端各只执行一次，独立账本与环境逐步一致。三局合计 41 / 41 源全清、847 动作、3 次去重重试、全部正常 `/exit`；Q3 结果保持此前数值不变。联合状态在两局 Q4 分别保守排除了 376、211 个清除格，运行时真源保留和方向兼容审计通过。

`service_calls.json` 保存去标识化请求 ID、路径与字节散列；`retry_evidence.json` 保存重复请求对和唯一执行次数；`verification.json` 记录离线逐动作计费、策略反馈与 HTTP 记录逐项相同、编码字节散列重新构造核对，以及25个源文件的快照核验。所有实际队号、凭据均未读取或写入这批日志。结果仍只证明本地接线与反馈闭环，不是两种朝向上的一般性能保证。

若要复现早期三种策略接线组合，可使用 `--suite legacy`，输出到另一个新目录；当前默认假服务套件为 `joint25`。本次未执行该旧套件，旧结果保留。

新增 Sweep 接线的14项 Python 检查通过。`runs/http_sweep/` 完成 `uniform_smooth_98100`：12 / 12 源全清、139 动作、虚拟 4047.53 s、现实 2.22 s；一次已执行测量丢响应后同 ID 同字节重试，141 个唯一请求只执行一次，逐动作账本通过并正常 `/exit`。最终28个 Python / PowerShell / 传递依赖源文件已在运行前保存并核对未改变。该策略仍是显式候选，原本地反例见上级 `SWEEP_COUNTEREXAMPLE.md`，不因此改默认策略。

PowerShell 入口在 Windows PowerShell 5.1 和 PowerShell 7.6 各通过7项检查：默认问题映射、显式 Sweep、含空格/中文/方括号/美元符号/反引号的路径经真实 Python 参数往返、非零退出37、异常脱敏、环境恢复/移除、错误问题策略和重复输出拒绝。验证使用本地替身程序，没有连接官方；简要结果保存在 `runs/http_sweep/launcher_checks.json`，私有原始夹具保留在 `local_launcher_checks/`。

## 冻结接口和必要文件

当前接口冻结 SHA256：

- `run_practice.ps1`：`20da253a8fa16c698e13f2facc9d5705c69e280121fdd0a5ea38e6d885d7c462`
- `adapter.py`：`69094b664a6952d48a6e4e5a897b1a3252137abdfef70158da5d33ea722fe3be`
- `live.py`：`db126e263610eabb0b2b01cb1bf02c470ab7d6fd703dcb8d62cf09da58797d26`
- `provenance.py`：`8e20dd58abf86875799b6ad5b1702da298ac1f2739768128966bd672a1e995d5`

接上已授权演练时，在原仓库运行即可。主要入口为 `run_practice.ps1`，依赖 `live.py`、`adapter.py`、`evidence.py`、`provenance.py`，复用 `b_env_probe/client.py`；Q3/Q4 共用冻结 `b_adaptive_q3/`、`task_cost.py`、当前 `astra_guard.py`。Sweep 另需 `sweep_policy.py`；它也导入 Q4 策略，因此保留完整传递依赖：`q4.py`、`q4_anchor_design.py`、`q4_joint_state.py`、`q4_coverage.py`、`q2_geometry.py`、`coverage.py` 和 `q4run.py`。不要只复制入口文件或遗漏联合信息状态。当前全部相关版本以 `runs/http_sweep/manifest.json` 和 `source/` 为准；核心策略没有修改。

本次本地检查仍未覆盖新增 Sweep 的实际官方延迟与成绩，PowerShell 包装也尚未用于真实官方会话；正式成绩和真实模式必须依据对应官方界面记录，不能由本地闭环推定。
