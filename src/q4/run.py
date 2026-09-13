"""Q4自建场景完整运行器：策略只接收公开状态，逐动作真值与计费审计。

示例：py -3.13 src/q4/run.py --split smoke --policies joint25 baseline
      --output outputs/q4/smoke01 --workers 2
候选默认导入 candidate.CandidatePolicy；其他类用 name=module:Class 指定。
没有官方接口或正式测试入口，没有任何历史保护代码依赖。
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import hashlib
import importlib
import json
import math
from pathlib import Path
import platform
import sys
import time
import traceback

import common
from common import PROJECT, ROOT, Joint25Policy, Q4State
from cases import build_cases, validate_scene
from q4 import Q4Config
from q4_joint_state import Q4JointCoverageInformationState, orientation_in
from simulation import LocalEnvironment, Scenario
from state import audit_state

SCHEMA_VERSION = 1


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def policy_name(spec):
    return spec.split("=", 1)[0]


def make_policy(spec, overrides=None):
    name = policy_name(spec)
    if spec == "selected":
        if overrides:
            raise ValueError("selected只能读取selected_config.json，不接受配置覆盖")
        from selected import SelectedPolicy
        return SelectedPolicy()
    if spec == "joint25":
        cls, config_cls = Joint25Policy, Q4Config
    else:
        if "=" in spec:
            module_name, class_name = spec.split("=", 1)[1].split(":", 1)
        elif spec == "baseline":
            module_name, class_name = "baseline", "BaselinePolicy"
        elif spec == "candidate":
            module_name, class_name = "candidate", "CandidatePolicy"
        else:
            module_name, class_name = spec, "CandidatePolicy"
        module = importlib.import_module(module_name)
        cls = getattr(module, class_name)
        config_cls = getattr(module, class_name.replace("Policy", "Config"), getattr(module, "CandidateConfig", Q4Config))
    if "astra_guard" in sys.modules or "q4run" in sys.modules:
        raise RuntimeError("策略导入了退役的旧运行器或保护模块，请移除该依赖")
    return cls(config_cls(**overrides)) if overrides else cls()


def serial_config(policy):
    config = getattr(policy, "config", None)
    if hasattr(config, "to_dict"):
        return config.to_dict()
    return asdict(config) if is_dataclass(config) else config


def source_paths():
    # 已知延迟依赖须提前纳入；不把其他协作者正在探索的无关文件锁进本批。
    common.require_local_dependencies()
    paths = {ROOT / name for name in ("run.py", "analyze.py", "planner.py", "selected.py", "selected_config.json")}
    for module in tuple(sys.modules.values()):
        name = getattr(module, "__file__", None)
        if not name:
            continue
        path = Path(name).resolve()
        if path.suffix == ".py" and ROOT in path.parents:
            paths.add(path)
    paths.add(ROOT / "core/geometry.py")
    return sorted(paths)


def hash_paths(paths):
    return {path.relative_to(PROJECT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def verify_hashes(expected):
    changed = [name for name, sha in expected.items()
               if not (PROJECT / name).is_file() or hashlib.sha256((PROJECT / name).read_bytes()).hexdigest() != sha]
    if changed:
        raise RuntimeError(f"运行源码发生变化，不能继续使用同批指纹: {changed}")


def public_response(response):
    return {k: v for k, v in response.items() if k in
            ("accepted", "virtual_time_s", "measure_result", "svd_deg", "clear_result")}


class IndependentAudit:
    """按接口规则独立计算动作费和可见性，不信任环境返回costs。

    可见性使用向量点积，与环境的方位角差实现不同；方位噪声只校验
    题面误差包络，不借模拟器noise_deg的相同公式冒充独立复核。
    """
    def __init__(self, scene):
        self.sources = {s.channel: s for s in scene.sources}
        self.position = (0.0, 0.0)
        self.channel = 1
        self.cleared = set()
        self.virtual_time_s = 0.0
        self.ledger = dict(move_s=0.0, switch_s=0.0, measure_s=0.0,
                           success_clear_s=0.0, failed_clear_s=0.0)

    def update(self, action, response):
        kind, q, j = action["kind"], tuple(action["position"]), action["channel"]
        if kind not in ("measure", "clear") or type(j) is not int or not 1 <= j <= 20:
            raise AssertionError("动作类型或频道违反接口")
        if len(q) != 2 or any(not math.isfinite(v) or abs(v) > 2_000_000 for v in q):
            raise AssertionError("动作坐标违反接口")
        if response.get("accepted") is not True:
            raise AssertionError("自建有效动作未被接受")
        source = self.sources.get(j) if j not in self.cleared else None
        distance = math.dist(q, source.position) if source else math.inf
        charges = dict(move_s=math.dist(self.position, q) / 5, switch_s=0,
                       measure_s=0, success_clear_s=0, failed_clear_s=0)
        if kind == "measure":
            visible = bool(source and distance <= source.radius)
            if visible and source.orientation is not None:
                angle = math.radians(source.orientation)
                vx, vy = q[0] - source.position[0], q[1] - source.position[1]
                # 与本地环境atan2(0,0)=0的退化约定一致；此单点无真实方位。
                if distance == 0:
                    vx, vy = 1.0, 0.0
                visible = vx * math.cos(angle) + vy * math.sin(angle) >= -max(1, distance) * 2e-12
            expected = "no_signal" if not visible else "near" if distance <= 5 else "direction"
            if response.get("measure_result") != expected:
                raise AssertionError(f"可见性反馈错误: {expected} != {response}")
            if expected == "direction":
                reported = response["svd_deg"]
                true = math.degrees(math.atan2(source.position[1] - q[1], source.position[0] - q[0])) % 360
                delta = (reported - true + 180) % 360 - 180
                if not 0 <= reported < 360 or abs(delta) > 1.0050001:
                    raise AssertionError("示向度超出1度误差及0.005度舍入包络")
            elif "svd_deg" in response:
                raise AssertionError("无示向度结果不应返回svd_deg")
            charges.update(switch_s=int(j != self.channel), measure_s=5)
            self.channel = j
        else:
            success = distance <= 20
            expected = "success" if success else "no_target_in_range"
            if response.get("clear_result") != expected:
                raise AssertionError("清除反馈与20米真值不符")
            charges["success_clear_s" if success else "failed_clear_s"] = 5 if success else 3
            if success:
                self.cleared.add(j)
        for key, value in charges.items():
            self.ledger[key] += value
        self.virtual_time_s += sum(charges.values())
        if abs(self.virtual_time_s - response["virtual_time_s"]) > 1e-5:
            raise AssertionError("独立计费与返回虚拟时间不一致")
        self.position = q
        return charges


def audit_joint_truth(state, env):
    audit_state(state, env)
    for j, source in env.sources.items():
        channel = state.channels[j]
        if channel.status != "found" or source.orientation is None:
            continue
        candidates = [cell for cell in channel.joint_last_details
                      if common.g.contains(cell["polygon"], source.position)]
        if candidates and not any(not c["discarded"] and orientation_in(c["orientation_intervals"], source.orientation) for c in candidates):
            raise AssertionError((j, "联合格证书未包含真实方向"))


def run_case(scene, policy_spec, output_dir, overrides=None, expected_hashes=None,
             max_wall_s=1200.0, max_actions=5000, max_virtual_s=360000.0):
    scene = validate_scene(scene)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    policy = state = env = None
    audit = IndependentAudit(scene)
    error, rows = None, []
    planning_s = update_s = checking_s = 0.0
    counts = {"measure_count": 0, "failed_clears": 0, "no_signal_count": 0}
    error_phase = "initialization"
    dump(output_dir / "case.json", scene.to_dict())
    with (output_dir / "actions.jsonl").open("w", encoding="utf-8") as trace, \
         (output_dir / "proposals.jsonl").open("w", encoding="utf-8") as proposals:
        try:
            if expected_hashes:
                verify_hashes(expected_hashes)
            policy = make_policy(policy_spec, overrides)
            state, env = Q4State(), LocalEnvironment(scene)
            dump(output_dir / "metadata.json", dict(schema_version=SCHEMA_VERSION, policy=policy_name(policy_spec),
                 policy_spec=policy_spec, config=serial_config(policy), case=scene.name, seed=scene.seed,
                 source_sha256=expected_hashes, truth_access="环境和独立审计器；策略只接收公开状态及标准反馈",
                 max_wall_s=max_wall_s, max_actions=max_actions, max_virtual_s=max_virtual_s))
            while not state.complete:
                if len(rows) >= max_actions or time.perf_counter() - started > max_wall_s:
                    raise TimeoutError("整局动作数或现实耗时超过限制")
                error_phase = "policy_choose"
                stamp = time.perf_counter()
                action = policy.choose(state)
                planning_s += time.perf_counter() - stamp
                if action is None:
                    raise AssertionError("未完成时策略未返回动作")
                proposals.write(json.dumps(dict(step=len(rows) + 1, action=action), ensure_ascii=False, allow_nan=False) + "\n")
                proposals.flush()
                error_phase = "environment"
                raw_response = env.act(action)
                response = public_response(raw_response)
                row = dict(step=len(rows) + 1, **action, response=response,
                           planning_s=time.perf_counter() - stamp)
                rows.append(row)
                # 先落盘动作及环境反馈，再做审计；失败动作不会消失。
                trace.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
                trace.flush()
                error_phase = "independent_feedback_audit"
                stamp = time.perf_counter()
                charges = audit.update(action, response)
                checking_s += time.perf_counter() - stamp
                row["charges"] = charges
                error_phase = "state_update"
                stamp = time.perf_counter()
                state.update(action, response)
                update_s += time.perf_counter() - stamp
                error_phase = "truth_state_audit"
                stamp = time.perf_counter()
                audit_joint_truth(state, env)
                checking_s += time.perf_counter() - stamp
                if env.virtual_time_s > max_virtual_s:
                    raise TimeoutError("虚拟耗时超过接口上限")
            if len(env.cleared) != len(scene.sources):
                raise AssertionError("策略宣称完成但真值未全清")
            if expected_hashes:
                verify_hashes(expected_hashes)
            error_phase = None
        except Exception:
            error = traceback.format_exc()
    wall_s = time.perf_counter() - started
    virtual_s = env.virtual_time_s if env else 0.0
    cleared = len(env.cleared) if env else 0
    measures = [r for r in rows if r["kind"] == "measure"]
    result = dict(case=scene.name, seed=scene.seed, layout=scene.layout, noise=scene.noise,
                  policy=policy_name(policy_spec), source_count=len(scene.sources),
                  directional_count=sum(s.orientation is not None for s in scene.sources),
                  cleared=cleared, cleared_ratio=cleared / len(scene.sources),
                  success=error is None and cleared == len(scene.sources) and state is not None and state.complete,
                  error=error, error_phase=error_phase, virtual_time_s=virtual_s,
                  average_localization_clear_s=virtual_s / cleared if cleared else None,
                  wall_time_s=wall_s, planning_s=planning_s, state_update_s=update_s, checking_s=checking_s,
                  actions=len(rows), measure_count=len(measures),
                  scan_position_count=len({tuple(r["position"]) for r in measures}),
                  failed_clears=sum(r["kind"] == "clear" and r["response"]["clear_result"] != "success" for r in rows),
                  no_signal_count=sum(r["response"]["measure_result"] == "no_signal" for r in measures),
                  fallback=getattr(policy, "fallback_started", None),
                  absence_proofs=getattr(state, "absence_proofs", {}),
                  ledger=audit.ledger, move_s=audit.ledger["move_s"], switch_s=audit.ledger["switch_s"],
                  measure_s=audit.ledger["measure_s"], clear_s=audit.ledger["success_clear_s"] + audit.ledger["failed_clear_s"],
                  independent_audit_passed=error is None,
                  joint_statistics=state.joint_statistics() if state else {})
    if policy and callable(getattr(policy, "metadata", None)):
        try:
            result["policy_metadata"] = policy.metadata()
        except Exception:
            result["metadata_error"] = traceback.format_exc()
    if state:
        dump(output_dir / "final_state.json", {j: dict(status=c.status, observations=c.observations,
              exclusions=c.exclusions, clear_history=getattr(c, "clear_history", [])) for j, c in state.channels.items()})
    # 审计成功后完整动作文件另留计费；中途崩溃仍有流式actions文件。
    dump(output_dir / "ledger.json", [dict(step=r["step"], charges=r.get("charges")) for r in rows])
    dump(output_dir / "result.json", result)
    return result


def _worker(payload):
    scene = Scenario.from_dict(payload.pop("scene"))
    return run_case(scene, **payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("smoke", "develop", "holdout", "pressure"), default="smoke")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--seed-offset", type=int, default=0)
    parser.add_argument("--cases", type=Path)
    parser.add_argument("--policies", nargs="+", default=["selected"])
    parser.add_argument("--config-json", type=Path, help="按策略名分组的配置覆盖JSON")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, choices=(1, 2, 3), default=2)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-wall-s", type=float, default=1200)
    parser.add_argument("--max-actions", type=int, default=5000)
    args = parser.parse_args()
    output = args.output.resolve()
    output_root = (PROJECT / "outputs/q4").resolve()
    if output_root not in output.parents:
        raise ValueError("结果必须放outputs/q4/<run-id>/子目录")
    if len(set(map(policy_name, args.policies))) != len(args.policies):
        raise ValueError("策略名不可重复")
    scenes = ([validate_scene(Scenario.from_dict(v)) for v in json.loads(args.cases.read_text(encoding="utf-8-sig"))]
              if args.cases else build_cases(args.split, seed_offset=args.seed_offset))
    if args.limit is not None:
        scenes = scenes[:args.limit]
    if not scenes or len({s.name for s in scenes}) != len(scenes):
        raise ValueError("场景为空或名称重复")
    overrides = json.loads(args.config_json.read_text(encoding="utf-8-sig")) if args.config_json else {}
    configs = {policy_name(spec): serial_config(make_policy(spec, overrides.get(policy_name(spec)))) for spec in args.policies}
    paths = source_paths()
    hashes = hash_paths(paths)
    contract = dict(schema_version=SCHEMA_VERSION, code_sha256=hashes,
                    cases=[s.to_dict() for s in scenes], policies=args.policies, configs=configs,
                    overrides=overrides, max_wall_s=args.max_wall_s, max_actions=args.max_actions,
                    max_virtual_s=360000, python=sys.version)
    signature = digest(contract)
    manifest_path = output / "manifest.json"
    if output.exists():
        if not args.resume or not manifest_path.exists():
            raise ValueError("已有输出必须使用--resume且具有manifest；不得覆盖旧结果")
        if json.loads(manifest_path.read_text(encoding="utf-8"))["run_signature"] != signature:
            raise ValueError("恢复要求源码、案例、策略配置、时限和Python完全一致，请新建批次")
    else:
        output.mkdir(parents=True)
        dump(manifest_path, dict(**contract, run_signature=signature,
             created_at_utc=datetime.now(timezone.utc).isoformat(), workers=args.workers,
             platform=platform.platform(), purpose="第四问自建混合源整局配对比较；非官方成绩"))
        dump(output / "cases.json", [s.to_dict() for s in scenes])
        for path in paths:
            destination = output / "source" / path.relative_to(PROJECT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(path.read_bytes())
    results, jobs = [], []
    for scene in scenes:
        for spec in args.policies:
            folder = output / "cases" / scene.name / policy_name(spec)
            saved = folder / "result.json"
            if args.resume and saved.exists():
                results.append(json.loads(saved.read_text(encoding="utf-8")))
            else:
                # 没有result的中断尝试也保留，不复写动作日志。
                if folder.exists():
                    folder = folder / f"retry_{time.time_ns()}"
                jobs.append(dict(scene=scene.to_dict(), policy_spec=spec, output_dir=str(folder),
                     overrides=overrides.get(policy_name(spec)), expected_hashes=hashes,
                     max_wall_s=args.max_wall_s, max_actions=args.max_actions))
    def save(result):
        results.append(result)
        results.sort(key=lambda r: (r["case"], r["policy"]))
        dump(output / "cases" / result["case"] / result["policy"] / "result.json", result)
        dump(output / "results.json", results)
        print(json.dumps({k: result[k] for k in ("case", "policy", "success", "cleared", "source_count",
                                               "virtual_time_s", "wall_time_s", "failed_clears", "error_phase")}, ensure_ascii=False), flush=True)
    if args.workers == 1:
        for payload in jobs:
            save(_worker(payload))
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            futures = [executor.submit(_worker, payload) for payload in jobs]
            for future in as_completed(futures):
                save(future.result())
    dump(output / "results.json", results)
    from analyze import write_report
    write_report(output)
    if not all(r["success"] for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
