"""复用既有公开 HTTP 客户端，将冻结策略接入逐动作反馈。"""
import importlib.util
import json
import math
from pathlib import Path
import sys
import threading
import time
import unicodedata

ROOT = Path(__file__).resolve().parent
NIGHT = ROOT.parent
if str(NIGHT) not in sys.path:
    sys.path.insert(0, str(NIGHT))
_spec = importlib.util.spec_from_file_location("cumcm_existing_robot_client", NIGHT.parent / "b_env_probe" / "client.py")
_client_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_client_module)
RobotClient, ProbeError = _client_module.RobotClient, _client_module.ProbeError

from task_cost import CompletionCostConfig, CompletionCostPolicy
from q4 import Q4Config, Q4DirectionalPolicy, Q4InformationState
from state import InformationState
from astra_guard import check_cached


def finite_number(value, name, lower=0, upper=math.inf):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lower <= value <= upper:
        raise ProbeError(f"非法 {name}")
    return float(value)


def public_response(response):
    if not isinstance(response, dict):
        return {"invalid_response_type": type(response).__name__}
    numeric = ("real_timestamp_ms", "virtual_time_s", "remaining_real_duration_s", "max_real_duration_s", "max_virtual_duration_s", "svd_deg")
    result = {}
    if "accepted" in response:
        result["accepted"] = response["accepted"] if isinstance(response["accepted"], bool) else "invalid_type"
    for key in numeric:
        if key in response:
            value = response[key]
            result[key] = value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else "invalid_type"
    enums = {"measure_result": ("direction", "near", "no_signal"), "clear_result": ("success", "no_target_in_range"), "exit_reason": ("user_exit",)}
    for key, allowed in enums.items():
        if key in response:
            result[key] = response[key] if response[key] in allowed else "invalid_result"
    return result


class PracticeClient(RobotClient):
    """继承同 ID 同字节重试；增加串行锁、公开限时字段和独立计费核对。"""
    def __init__(self, robot_id, *args, **kwargs):
        if not isinstance(robot_id, str) or not 1 <= len(robot_id.encode("utf-8")) <= 64 or any(unicodedata.category(ch) in ("Cc", "Cf") for ch in robot_id):
            raise ValueError("参赛队号格式无效")
        super().__init__(robot_id, *args, **kwargs)
        self.position = (0.0, 0.0)
        self.measure_channel = 1
        self.max_virtual = 360000.0
        self.ledger = dict(move_s=0.0, switch_s=0.0, measure_s=0.0, clear_s=0.0)
        self._serial = threading.Lock()

    def worst_cost(self, action):
        q = action["position"]
        move = math.hypot(q[0] - self.position[0], q[1] - self.position[1]) / 5
        return move + (5 + int(action["channel"] != self.measure_channel) if action["kind"] == "measure" else 5)

    def action(self, path, position=None, channel=None):
        if not self._serial.acquire(blocking=False):
            raise ProbeError("禁止并发发送不同动作")
        try:
            previous = self.virtual_time
            response = super().action(path, position, channel)
            finite_number(response.get("real_timestamp_ms"), "现实时间戳")
            if path == "/enter":
                max_real = finite_number(response.get("max_real_duration_s"), "现实限时", upper=1200)
                self.max_virtual = finite_number(response.get("max_virtual_duration_s"), "虚拟限时", lower=1, upper=360000)
                remaining = finite_number(response.get("remaining_real_duration_s"), "剩余现实时间", upper=max_real)
                if remaining != int(remaining) or abs(self.virtual_time) > 1e-6:
                    raise ProbeError("进入响应不符合新会话约束")
            elif path == "/exit":
                if response.get("exit_reason") != "user_exit" or abs(self.virtual_time - previous) > 1e-3:
                    raise ProbeError("退出响应或计时异常")
            else:
                q = tuple(position)
                move = math.hypot(q[0] - self.position[0], q[1] - self.position[1]) / 5
                switch = int(path == "/measure" and channel != self.measure_channel)
                operation = 5 if path == "/measure" or response["clear_result"] == "success" else 3
                if abs(self.virtual_time - previous - move - switch - operation) > 1e-3:
                    raise ProbeError("公开动作响应与独立计费相差超过 1 毫秒")
                self.ledger["move_s"] += move
                self.ledger["switch_s"] += switch
                self.ledger["measure_s" if path == "/measure" else "clear_s"] += operation
                self.position = q
                if path == "/measure":
                    self.measure_channel = channel
            # 只保存公开定义字段，避免意外响应字段泄露身份信息。
            self.records[-1]["response"] = public_response(response)
            return public_response(response)
        except Exception:
            self.failed = True
            raise
        finally:
            self._serial.release()


def strategy(problem, name=None, overrides=None):
    name = name or {3: "completion", 4: "joint25"}.get(problem)
    overrides = overrides or {}
    def validate(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("配置不允许 NaN/Infinity")
        if isinstance(value, dict):
            for x in value.values():
                validate(x)
        if isinstance(value, (list, tuple)):
            for x in value:
                validate(x)
    validate(overrides)
    if problem == 3 and name in ("completion", "configured"):
        if name == "configured" and not overrides:
            raise ValueError("configured 必须明确给出配置文件，不默用默认参数")
        config = CompletionCostConfig(**overrides)
        return CompletionCostPolicy(config), InformationState()
    if problem == 4 and name == "directional":
        return Q4DirectionalPolicy(Q4Config(**overrides)), Q4InformationState()
    if problem == 4 and name == "joint25":
        from q4_anchor_design import Q4Symmetric25Policy
        from q4_joint_state import Q4JointCoverageInformationState
        return Q4Symmetric25Policy(Q4Config(**overrides)), Q4JointCoverageInformationState()
    raise ValueError("问题与策略不匹配；只支持 Q3 completion/configured 和 Q4 joint25/directional")


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def run_session(client, policy, state, problem, authorization, output, guard=check_cached, audit_hook=None, reserve_real_s=10.0):
    """授权对象必须核对本次 UI 或确认为本进程拥有的假服务；不接受布尔开关。"""
    if not hasattr(authorization, "authorize") or not hasattr(authorization, "scope"):
        raise ValueError("需要具体的本次授权对象，布尔确认无效")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    rows, error, stop_reason = [], None, None
    dump(output / "config.json", policy.config.to_dict())
    pending = None
    try:
        guard()
        authorization.authorize(client.port, problem)
        enter = client.action("/enter")
        dump(output / "enter.json", enter)
        while not state.complete:
            guard()
            if len(rows) >= 5000:
                stop_reason = "action_limit"
                break
            if client.deadline - client.clock() <= reserve_real_s:
                stop_reason = "real_time_reserve"
                break
            action = policy.choose(state)
            if action is None:
                raise ProbeError("未证明完成却没有动作")
            if math.hypot(*action["position"]) > policy.config.domain_radius_m + 1e-6:
                raise ProbeError("策略动作超出声明区域")
            if client.deadline - client.clock() <= reserve_real_s:
                stop_reason = "real_time_reserve_after_planning"
                break
            if client.virtual_time + client.worst_cost(action) >= client.max_virtual - 1e-3:
                stop_reason = "virtual_time_reserve"
                break
            pending = dict(step=len(rows) + 1, kind=action["kind"], position=action["position"], channel=action["channel"],
                           request_id=f"{client.prefix}-{client.sequence + 1}")
            dump(output / "pending.json", pending)
            response = client.action("/" + action["kind"], action["position"], action["channel"])
            state.update(action, response)
            if audit_hook:
                audit_hook(state)
            rows.append(dict(step=len(rows) + 1, action=action, response=response))
            with (output / "actions.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(rows[-1], ensure_ascii=False, allow_nan=False) + "\n")
            pending = None
            dump(output / "pending.json", {"pending": False, "completed_steps": len(rows)})
        if state.complete:
            stop_reason = "complete_by_strategy_evidence"
    except Exception as exc:
        # 不序列化异常正文，避免第三方响应/参数中的敏感信息被意外回显。
        error = type(exc).__name__
        stop_reason = "transport_or_validation_error" if client.failed else "local_stop_or_policy_error"
    finally:
        # 结果不明时不发新命令；健康会话在尚有时间时主动 /exit。
        if client.entered and not client.failed and not client.exited and client.deadline - client.clock() > 0.05:
            try:
                client.action("/exit")
            except Exception as exc:
                error = error or type(exc).__name__
                stop_reason = "exit_uncertain"
        dump(output / "http_records.json", [{**row, "response": public_response(row["response"])} for row in client.records])
    state_evidence = dict(state_class=type(state).__name__,
                          channel_status={j: c.status for j, c in state.channels.items()},
                          absence_proofs=getattr(state, "absence_proofs", {}))
    if hasattr(state, "joint_statistics"):
        state_evidence["joint_statistics"] = state.joint_statistics()
    dump(output / "state_evidence.json", state_evidence)
    summary = dict(scope=authorization.scope, problem=problem, policy=type(policy).__name__, state_class=type(state).__name__,
                   complete_by_evidence=state.complete, cleared_count=sum(c.status == "cleared" for c in state.channels.values()),
                   official_true_count=None, official_all_cleared=None, ui_result_check_pending=authorization.scope == "official_practice",
                   actions=len(rows), requests=len(client.records), retry_count=sum(row["attempts"] - 1 for row in client.records),
                   virtual_time_s=client.virtual_time, wall_time_s=time.perf_counter() - started,
                   stop_reason=stop_reason, error_type=error, exited=client.exited,
                   uncertain_request=pending, protocol_stopped=client.failed, **client.ledger)
    dump(output / "summary.json", summary)
    return summary
