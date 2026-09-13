"""Q4官方演练的公开API适配器；没有启动正式测试或自动选择模式的入口。

使用前必须由人或本对话已获授权的代理，实际查看本次官方窗口，确认
“问题4、演练测试、案例代码”后写入UI证据收据。程序校验收据完整性、
120秒新鲜度与单次消费，但不把用户填写的字段当成模式证明，也不能
替代对截图/工具结果的语义核对。不得为通过校验编造工具引用。

截图无法落盘时可使用真实Codex工具结果引用，收据形如：
{
  "schema_version": 1,
  "observed_at_utc": "实际观察的带时区时间",
  "problem": 4, "port": 2026, "mode_visible_text": "演练测试",
  "window_title": "实际窗口标题", "case_code": "实际案例代码",
  "review_note": "操作者从上述实际工具结果核对本次模式的说明",
  "evidence": {"kind": "codex_tool_snapshot", "reference": "本对话实际工具结果引用"}
}
若有实际截图，evidence改为kind=screenshot、path=绝对路径、sha256=实际散列。
收据不可提前制作；不提供生成或刷新收据时间的命令。单次消费发生在
/enter前，失败也不可复用。另一份相同证据的收据同样被拒绝。

仓库根目录运行（队号仅从环境变量读取，不放命令参数、源码或日志）：
  py -3.13 experiments/q4/practice.py --receipt <本次收据.json>
    --output outputs/experiments/q4/<演练批次> --policy candidate
可选 --config-json <仅该策略参数.json>，默认读取CUMCM_ROBOT_ID环境变量。
已有UI授权允许演练；正式测试仍须逐次授权，本程序一律拒绝正式模式。

请求严格串行、固定127.0.0.1、无系统代理、retries=0。未知请求结果、
拒绝响应、坏计费均停止，不重试、不自动退出或重进。健康会话可以退出。
summary中的all_clear只表示公开状态证书；真实源数和官方终局需再看UI。
所有test_practice测试仅连接本进程随机回环端口，不连接真实模拟器。
"""
import argparse
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import threading
import time
import unicodedata

import common
from common import PROJECT, Q4State

CLIENT_PATH = PROJECT / "experiments/b_env_probe/client.py"
_spec = importlib.util.spec_from_file_location("_q4_public_robot_client", CLIENT_PATH)
_client = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_client)
RobotClient, ProbeError = _client.RobotClient, _client.ProbeError
OFFICIAL_OUTPUT_ROOT = (PROJECT / "outputs/experiments/q4").resolve()
RECEIPT_REGISTRY = OFFICIAL_OUTPUT_ROOT / "practice_receipt_uses"


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def finite_number(value, name, lower=0, upper=math.inf):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lower <= value <= upper:
        raise ProbeError(f"非法公开数值字段: {name}")
    return float(value)


def public_response(response):
    if not isinstance(response, dict):
        return {"invalid_response_type": type(response).__name__}
    clean = {}
    if "accepted" in response:
        clean["accepted"] = response["accepted"] if isinstance(response["accepted"], bool) else "invalid_type"
    for key in ("real_timestamp_ms", "virtual_time_s", "remaining_real_duration_s",
                "max_real_duration_s", "max_virtual_duration_s", "svd_deg"):
        if key in response:
            value = response[key]
            clean[key] = value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else "invalid_type"
    for key, allowed in {"measure_result": ("direction", "near", "no_signal"),
                         "clear_result": ("success", "no_target_in_range"),
                         "exit_reason": ("user_exit",)}.items():
        if key in response:
            clean[key] = response[key] if response[key] in allowed else "invalid_result"
    return clean


def redact(value, robot_id):
    if isinstance(value, str):
        return value.replace(robot_id, "[REDACTED]") if robot_id else value
    if isinstance(value, dict):
        return {k: redact(v, robot_id) for k, v in value.items() if k not in ("robot_id", "password", "team_id")}
    if isinstance(value, (list, tuple)):
        return [redact(v, robot_id) for v in value]
    return value


class PracticeClient(RobotClient):
    """复用已审计的公开客户端，增加串行与独立计费，禁止自动重试。"""
    def __init__(self, robot_id, port=2026, timeout=5.0, transport=None, clock=time.perf_counter):
        if not isinstance(robot_id, str) or not 1 <= len(robot_id.encode("utf-8")) <= 64 or any(unicodedata.category(c) in ("Cc", "Cf") for c in robot_id):
            raise ValueError("参赛队号格式无效")
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("端口必须是合法整数")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("连接超时必须为正数")
        super().__init__(robot_id, port=port, timeout=timeout, retries=0, transport=transport, clock=clock)
        self.position = (0., 0.)
        self.measure_channel = 1
        self.max_virtual = 360000.
        self.ledger = dict(move_s=0., switch_s=0., measure_s=0., success_clear_s=0., failed_clear_s=0.)
        self.successful_channels = set()
        self.validation_issue = None
        self._serial = threading.Lock()

    def worst_cost(self, action):
        move = math.dist(self.position, action["position"]) / 5
        return move + (5 + int(action["channel"] != self.measure_channel) if action["kind"] == "measure" else 5)

    def action(self, path, position=None, channel=None):
        if not self._serial.acquire(blocking=False):
            raise ProbeError("禁止并发发送不同动作")
        try:
            if self.retries != 0:
                self.validation_issue = "retry_configuration_changed"
                raise ProbeError("本适配器不允许重试")
            previous = self.virtual_time
            response = super().action(path, position, channel)
            finite_number(response.get("real_timestamp_ms"), "real_timestamp_ms")
            if path == "/enter":
                real_limit = finite_number(response.get("max_real_duration_s"), "max_real_duration_s", upper=1200)
                self.max_virtual = finite_number(response.get("max_virtual_duration_s"), "max_virtual_duration_s", lower=1, upper=360000)
                remaining = finite_number(response.get("remaining_real_duration_s"), "remaining_real_duration_s", upper=real_limit)
                if remaining != int(remaining) or abs(self.virtual_time) > 1e-6:
                    self.validation_issue = "invalid_enter_clock"
                    raise ProbeError("新会话初始时钟或现实限时异常")
            elif path == "/exit":
                if response.get("exit_reason") != "user_exit" or abs(self.virtual_time - previous) > 1e-6:
                    self.validation_issue = "invalid_exit_clock"
                    raise ProbeError("退出响应或时钟异常")
            else:
                move = math.dist(self.position, position) / 5
                switch = int(path == "/measure" and channel != self.measure_channel)
                success = path == "/clear" and response["clear_result"] == "success"
                operation = 5 if path == "/measure" or success else 3
                # 官方时钟按微秒累计，容许逐动作1毫秒独立核对余量。
                if abs(self.virtual_time - previous - move - switch - operation) > .001:
                    self.validation_issue = "cost_mismatch"
                    raise ProbeError("公开反馈与独立计费不符")
                self.ledger["move_s"] += move
                self.ledger["switch_s"] += switch
                self.ledger["measure_s" if path == "/measure" else "success_clear_s" if success else "failed_clear_s"] += operation
                self.position = tuple(position)
                if path == "/measure":
                    self.measure_channel = channel
                    if response["measure_result"] != "direction" and "svd_deg" in response:
                        self.validation_issue = "unexpected_bearing"
                        raise ProbeError("无示向度结果带有svd_deg")
                elif success:
                    if channel in self.successful_channels:
                        self.validation_issue = "duplicate_clear_success"
                        raise ProbeError("同一频道重复成功清除")
                    self.successful_channels.add(channel)
            return public_response(response)
        except Exception:
            self.failed = True
            raise
        finally:
            # RobotClient在验证前保留响应；错误响应也必须脱敏。
            for row in self.records:
                row["response"] = public_response(row.get("response"))
            self._serial.release()


def validate_receipt(path, port, now=None):
    path = Path(path).resolve()
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    required = {"schema_version", "observed_at_utc", "problem", "port", "mode_visible_text",
                "window_title", "case_code", "review_note", "evidence"}
    if set(data) != required or data["schema_version"] != 1 or type(data["problem"]) is not int or data["problem"] != 4:
        raise ValueError("仅接受问题4本次演练的完整证据收据")
    if data["mode_visible_text"] != "演练测试" or type(data["port"]) is not int or data["port"] != port:
        raise ValueError("模式必须是本次实际核对的演练测试，且端口一致")
    for key in ("window_title", "case_code", "review_note"):
        if not isinstance(data[key], str) or not data[key].strip() or len(data[key]) > 500:
            raise ValueError("缺少实际窗口、案例或核验说明")
    observed = datetime.fromisoformat(data["observed_at_utc"].replace("Z", "+00:00"))
    if observed.tzinfo is None:
        raise ValueError("观察时间必须带时区")
    age = (time.time() if now is None else now) - observed.timestamp()
    if not 0 <= age <= 120:
        raise ValueError("UI证据超过120秒或时间在未来；必须重新实际观察")
    evidence = data["evidence"]
    if not isinstance(evidence, dict):
        raise ValueError("必须指向本次实际外部观察证据")
    if evidence.get("kind") == "codex_tool_snapshot":
        if set(evidence) != {"kind", "reference"} or not isinstance(evidence["reference"], str) or not 8 <= len(evidence["reference"]) <= 1000:
            raise ValueError("必须提供本对话实际工具结果引用")
        identity = evidence["reference"]
    elif evidence.get("kind") == "screenshot":
        if set(evidence) != {"kind", "path", "sha256"}:
            raise ValueError("截图证据字段不完整")
        image = Path(evidence["path"])
        if not image.is_absolute() or not image.is_file():
            raise ValueError("需要实际截图的绝对文件路径")
        raw = image.read_bytes()
        if len(raw) < 100 or not (raw.startswith(b"\x89PNG\r\n\x1a\n") or raw.startswith(b"\xff\xd8\xff")):
            raise ValueError("截图不是PNG或JPEG")
        identity = hashlib.sha256(raw).hexdigest()
        if identity != evidence["sha256"]:
            raise ValueError("实际截图散列不匹配")
    else:
        raise ValueError("不接受自行填写的布尔确认；需要实际截图或工具结果引用")
    if path.with_suffix(path.suffix + ".consumed").exists():
        raise ValueError("该UI证据收据已经使用")
    key = hashlib.sha256(json.dumps([evidence["kind"], identity, port, 4, data["case_code"]], ensure_ascii=False).encode()).hexdigest()
    return data, key


class ReviewedPracticeAuthorization:
    """记录操作者已完成的实际UI语义核验；程序只核验收据结构与一次性。"""
    scope = "official_practice"
    def __init__(self, receipt_path, port, registry=RECEIPT_REGISTRY):
        self.receipt_path, self.port = Path(receipt_path).resolve(), port
        self.registry = Path(registry)
        self.evidence_record = None

    def authorize(self, port, problem=4):
        if port != self.port or problem != 4:
            raise ValueError("UI核验与本次连接不匹配")
        data, key = validate_receipt(self.receipt_path, port)
        self.registry.mkdir(parents=True, exist_ok=True)
        marker = self.registry / f"{key}.consumed.json"
        consumed = dict(consumed_at_utc=datetime.now(timezone.utc).isoformat(), problem=4,
                        case_code=data["case_code"], evidence_key=key)
        # 全局证据指纹与本地收据各消费一次；复制收据也不能重用同一观察。
        with marker.open("x", encoding="utf-8") as stream:
            json.dump(consumed, stream, ensure_ascii=False)
        with self.receipt_path.with_suffix(self.receipt_path.suffix + ".consumed").open("x", encoding="utf-8") as stream:
            json.dump(consumed, stream, ensure_ascii=False)
        self.evidence_record = data


def load_verified_practice_ui(receipt_path, port=2026):
    validate_receipt(receipt_path, port)
    return ReviewedPracticeAuthorization(receipt_path, port)


def policy_and_state(name="candidate", overrides=None):
    if name == "candidate":
        from candidate import CandidateConfig, CandidatePolicy
        policy = CandidatePolicy(CandidateConfig(**(overrides or {})))
    elif name == "baseline":
        from baseline import BaselineConfig, BaselinePolicy
        policy = BaselinePolicy(BaselineConfig(**(overrides or {})))
    elif name == "joint25":
        from common import Joint25Policy, Q4Config
        policy = Joint25Policy(Q4Config(**(overrides or {})))
    else:
        raise ValueError("未知Q4演练策略")
    if "astra_guard" in sys.modules or "q4run" in sys.modules:
        raise RuntimeError("不得加载旧运行器或保护模块")
    return policy, Q4State()


def snapshot_sources(output):
    paths = {Path(__file__).resolve(), CLIENT_PATH, PROJECT / "experiments/b_adaptive_q3/geometry.py",
             PROJECT / "experiments/q4/planner.py"}
    for module in tuple(sys.modules.values()):
        raw = getattr(module, "__file__", None)
        if raw:
            path = Path(raw).resolve()
            if path.suffix == ".py" and PROJECT in path.parents:
                paths.add(path)
    hashes = {}
    for path in sorted(paths):
        relative = path.relative_to(PROJECT)
        data = path.read_bytes()
        hashes[relative.as_posix()] = hashlib.sha256(data).hexdigest()
        destination = output / "source" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    return hashes


def audit_public_state(state, client):
    if abs(state.virtual_time_s - client.virtual_time) > 1e-6 or tuple(state.position) != client.position or state.measuring_channel != client.measure_channel:
        raise ProbeError("策略公开状态与接口计费状态不一致")
    cleared = {j for j, c in state.channels.items() if c.status == "cleared"}
    if cleared != client.successful_channels or len(state.ever_seen) > 16:
        raise ProbeError("清除记录或源数上界不一致")
    if state.complete and any(c.status not in ("cleared", "absent") for c in state.channels.values()):
        raise ProbeError("尚有未知目标却宣称完成")


def run_session(client, policy, state, authorization, output, reserve_real_s=15., max_actions=5000, audit_hook=None):
    if not callable(getattr(authorization, "authorize", None)) or getattr(authorization, "scope", None) not in ("official_practice", "self_built_http_mock"):
        raise ValueError("需要本次实际UI核验对象或本进程假服务对象，布尔值无效")
    output = Path(output).resolve()
    if authorization.scope == "official_practice" and OFFICIAL_OUTPUT_ROOT not in output.parents:
        raise ValueError("演练产物必须进入outputs/experiments/q4/<run-id>")
    if not math.isfinite(reserve_real_s) or reserve_real_s < 1 or type(max_actions) is not int or max_actions < 1:
        raise ValueError("现实时间预留和动作上限无效")
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    rows, pending, error_type, stop_reason = [], None, None, None
    config = getattr(policy, "config", None)
    config = config.to_dict() if hasattr(config, "to_dict") else asdict(config) if is_dataclass(config) else config
    dump(output / "config.json", redact(config, client.robot_id))
    hashes = snapshot_sources(output)
    dump(output / "manifest.json", dict(created_at_utc=datetime.now(timezone.utc).isoformat(),
         scope=authorization.scope, problem=4, code_sha256=hashes, python=sys.version,
         policy=type(policy).__name__, state_class=type(state).__name__, port=client.port,
         transport="127.0.0.1_public_HTTP_serial", automatic_retries=0))
    with (output / "actions.jsonl").open("w", encoding="utf-8") as trace:
        try:
            authorization.authorize(client.port, 4)
            if getattr(authorization, "evidence_record", None):
                dump(output / "ui_evidence.json", redact(authorization.evidence_record, client.robot_id))
            enter = client.action("/enter")
            dump(output / "enter.json", enter)
            # 候选可在内部耗时循环中检查该真实截止时间；入口还会在规划后复查。
            # 不按配置默认1200秒猜测本次实际剩余时间。
            policy.wall_deadline = client.deadline - reserve_real_s
            while not state.complete:
                if len(rows) >= max_actions:
                    stop_reason = "action_limit"
                    break
                if client.deadline - client.clock() <= reserve_real_s:
                    stop_reason = "real_time_reserve"
                    break
                stamp = time.perf_counter()
                action = policy.choose(state)
                planning_s = time.perf_counter() - stamp
                if action is None or action.get("kind") not in ("measure", "clear"):
                    raise ProbeError("未证明完成却没有合法动作")
                if client.deadline - client.clock() <= reserve_real_s:
                    stop_reason = "real_time_reserve_after_planning"
                    break
                if client.virtual_time + client.worst_cost(action) >= client.max_virtual - 1e-6:
                    stop_reason = "virtual_time_reserve"
                    break
                public_action = {key: action[key] for key in ("kind", "position", "channel", "reason") if key in action}
                pending = dict(step=len(rows) + 1, action=public_action, request_id=f"{client.prefix}-{client.sequence + 1}")
                dump(output / "pending.json", redact(pending, client.robot_id))
                response = client.action("/" + action["kind"], action["position"], action["channel"])
                row = dict(step=len(rows) + 1, action=public_action, response=response, planning_s=planning_s)
                rows.append(row)
                # 返回动作先落盘，再更新状态，状态错误不会抹掉真实请求。
                trace.write(json.dumps(redact(row, client.robot_id), ensure_ascii=False, allow_nan=False) + "\n")
                trace.flush()
                state.update(action, response)
                audit_public_state(state, client)
                if audit_hook:
                    audit_hook(state)
                pending = None
                dump(output / "pending.json", {"pending": False, "completed_steps": len(rows)})
            if state.complete:
                stop_reason = "complete_by_public_evidence"
        except Exception as exc:
            error_type = type(exc).__name__
            stop_reason = "transport_or_protocol_error" if client.failed else "local_or_authorization_error"
        finally:
            if client.entered and not client.failed and not client.exited and client.deadline - client.clock() > .05:
                try:
                    client.action("/exit")
                except Exception as exc:
                    error_type = error_type or type(exc).__name__
                    stop_reason = "exit_uncertain"
            dump(output / "http_records.json", redact(client.records, client.robot_id))
    cleared = len(client.successful_channels)
    state_evidence = dict(channel_status={j: c.status for j, c in state.channels.items()},
        absence_proofs=getattr(state, "absence_proofs", {}),
        clear_history={j: getattr(c, "clear_history", []) for j, c in state.channels.items()},
        joint_statistics=state.joint_statistics())
    dump(output / "state_evidence.json", state_evidence)
    source_changed = [name for name, sha in hashes.items() if not (PROJECT / name).is_file()
                      or hashlib.sha256((PROJECT / name).read_bytes()).hexdigest() != sha]
    if source_changed and error_type is None:
        stop_reason = "source_changed_during_session"
    summary = dict(scope=authorization.scope, problem=4, policy=type(policy).__name__,
        complete_by_public_evidence=state.complete and error_type is None and not source_changed,
        cleared_count=cleared, official_true_count=None, official_all_cleared=None,
        ui_result_check_pending=authorization.scope == "official_practice",
        actions=len(rows), requests_attempted=client.sequence, recorded_responses=len(client.records),
        automatic_retries=0, virtual_time_s=client.virtual_time,
        average_localization_clear_s=client.virtual_time / cleared if cleared else None,
        wall_time_s=time.perf_counter() - started, ledger=client.ledger,
        independently_accounted_s=sum(client.ledger.values()), stop_reason=stop_reason,
        error_type=error_type, validation_issue=client.validation_issue, exited=client.exited,
        protocol_stopped=client.failed, uncertain_request=pending,
        source_changed=source_changed)
    dump(output / "summary.json", redact(summary, client.robot_id))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=2026)
    parser.add_argument("--policy", choices=("candidate", "baseline", "joint25"), default="candidate")
    parser.add_argument("--config-json", type=Path)
    parser.add_argument("--robot-id-env", default="CUMCM_ROBOT_ID")
    parser.add_argument("--reserve-real-s", type=float, default=15.)
    parser.add_argument("--max-actions", type=int, default=5000)
    args = parser.parse_args()
    robot_id = os.environ.get(args.robot_id_env)
    if not robot_id:
        raise SystemExit("未设置参赛队号环境变量；不通过命令行传入或打印队号")
    authorization = load_verified_practice_ui(args.receipt, args.port)
    overrides = json.loads(args.config_json.read_text(encoding="utf-8-sig")) if args.config_json else {}
    policy, state = policy_and_state(args.policy, overrides)
    summary = run_session(PracticeClient(robot_id, port=args.port), policy, state, authorization,
                          args.output, reserve_real_s=args.reserve_real_s, max_actions=args.max_actions)
    print(json.dumps({key: summary[key] for key in ("scope", "complete_by_public_evidence", "cleared_count",
          "virtual_time_s", "average_localization_clear_s", "wall_time_s", "stop_reason", "error_type", "exited")}, ensure_ascii=False))
    if summary["error_type"] or not summary["complete_by_public_evidence"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
