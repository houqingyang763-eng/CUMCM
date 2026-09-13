"""独立只读复核小改法批次：不导入bench，不执行策略或模拟器动作。

逐行使用IndependentAudit独立复算反馈与费用，使用正式Q4State重建
公开状态，并在每一步核对真值相容。几何复核共享原状态实现，不是
第二套独立几何证明。--partial只审计启动时已经有result.json的整局。
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import time
import traceback

PROJECT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT / "src/q4"))
from common import Q4State
from cases import build_cases, validate_scene
from run import IndependentAudit, audit_joint_truth
from simulation import Scenario

ROOT = PROJECT / "outputs/experiments/q4/micro_changes"
TOL = 1e-5
FILES = ("case.json", "metadata.json", "actions.jsonl", "proposals.jsonl",
         "ledger.json", "result.json", "final_state.json")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def normalized(value):
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def same_float(a, b, label):
    if not math.isfinite(a) or not math.isfinite(b) or abs(a-b) > TOL:
        raise AssertionError((label, a, b))


def json_lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def check_sources(hashes, snapshot):
    missing = []
    for relative, expected in hashes.items():
        source = PROJECT / relative
        if sha(source) != expected:
            raise AssertionError(f"当前源码指纹改变: {relative}")
        saved = snapshot / relative
        if saved.is_file():
            if sha(saved) != expected:
                raise AssertionError(f"归档源码指纹改变: {saved}")
        else:
            missing.append(relative)
    return missing


def check_catalog():
    path = ROOT / "catalog.json"
    items = read(path)
    for item in items:
        if item["reference"] is not None:
            item["reference"] = Path(item["reference"]).as_posix()
    expected = []
    sources = {}
    for group, batch in (("regression_regular", "holdout01"),
                         ("regression_pressure", "pressure01")):
        base = PROJECT / "outputs/q4" / batch
        manifest = read(base / "manifest.json")
        absent = check_sources(manifest["code_sha256"], base / "source")
        if absent:
            raise AssertionError((batch, "旧批源码快照不完整", absent))
        sources[batch] = manifest["code_sha256"]
        for scene in sorted(manifest["cases"], key=lambda x: x["name"]):
            expected.append(dict(group=group, scene=scene,
                reference=f"outputs/q4/{batch}/cases/{scene['name']}/selected"))
    for scene in build_cases("holdout", limit=8, seed_offset=2000):
        expected.append(dict(group="new_regular", scene=scene.to_dict(), reference=None))
    for scene in build_cases("pressure", limit=8, seed_offset=2000):
        expected.append(dict(group="new_pressure", scene=scene.to_dict(), reference=None))
    if items != normalized(expected):
        raise AssertionError("catalog不等于冻结的原32例及945000/946000起始各8例")
    if len(items) != 48 or len({i["scene"]["seed"] for i in items}) != 48:
        raise AssertionError("案例数量或种子唯一性错误")
    return items, sources


def check_run(task):
    began = time.perf_counter()
    folder = PROJECT / task["folder"]
    output = dict(case=task["scene"]["name"], group=task["group"],
                  policy=task["policy"], folder=task["folder"], passed=False)
    try:
        hashes = {name: sha(folder / name) for name in FILES}
        check_sources(task["source_hashes"], Path(task["snapshot"]))
        scene_data = read(folder / "case.json")
        if scene_data != task["scene"]:
            raise AssertionError("逐局case与冻结catalog不一致")
        scene = validate_scene(Scenario.from_dict(scene_data))
        metadata = read(folder / "metadata.json")
        result = read(folder / "result.json")
        if metadata["source_sha256"] != task["source_hashes"]:
            raise AssertionError("逐局源码指纹与批次不一致")
        for record in (metadata, result):
            if record["policy"] != task["policy"] or record["case"] != scene.name:
                raise AssertionError("逐局策略或案例标签错误")
        if not (result["success"] and result["independent_audit_passed"] and result["error"] is None):
            raise AssertionError(("原整局没有成功通过审计", result.get("error")))
        selected_config = read(PROJECT / "src/q4/selected_config.json")["parameters"]
        if metadata["config"] != selected_config or result["policy_metadata"]["config"] != selected_config:
            raise AssertionError("运行不使用冻结selected参数")
        rows = json_lines(folder / "actions.jsonl")
        proposals = json_lines(folder / "proposals.jsonl")
        ledger = read(folder / "ledger.json")
        if not len(rows) == len(proposals) == len(ledger) == result["actions"]:
            raise AssertionError("动作、提案、逐行账本和结果条数不同")
        audit, state = IndependentAudit(scene), Q4State()
        no_signal = failed_clear = measures = 0
        scan_positions = set()
        for step, (row, proposal, saved_ledger) in enumerate(zip(rows, proposals, ledger), 1):
            if row["step"] != step or proposal["step"] != step or saved_ledger["step"] != step:
                raise AssertionError(("step不连续", step))
            if state.complete:
                raise AssertionError(("完成后还有动作", step))
            action = proposal["action"]
            if any(row.get(k) != v for k, v in action.items()):
                raise AssertionError(("提案与实际动作不符", step))
            charges = audit.update(action, row["response"])
            if set(charges) != set(saved_ledger["charges"]):
                raise AssertionError(("账本分项名称错误", step))
            for key, value in charges.items():
                same_float(value, saved_ledger["charges"][key], f"step{step}:{key}")
            state.update(action, row["response"])
            # IndependentAudit提供真值/cleared/time视图，无需重跑环境。
            audit_joint_truth(state, audit)
            if action["kind"] == "measure":
                measures += 1
                scan_positions.add(tuple(action["position"]))
                no_signal += row["response"]["measure_result"] == "no_signal"
            else:
                failed_clear += row["response"]["clear_result"] != "success"
        count = len(scene.sources)
        if not (state.complete and len(audit.cleared) == count == result["cleared"] == result["source_count"]):
            raise AssertionError("终止状态/真实清除数不完整")
        if sum(c.status == "cleared" for c in state.channels.values()) != count:
            raise AssertionError("公开清除数不等于真值")
        same_float(audit.virtual_time_s, result["virtual_time_s"], "虚拟总时间")
        same_float(audit.virtual_time_s / count, result["average_localization_clear_s"], "每源用时")
        same_float(result["cleared_ratio"], 1.0, "全清比例")
        if set(audit.ledger) != set(result["ledger"]):
            raise AssertionError("总账本分项错误")
        for key, value in audit.ledger.items():
            same_float(value, result["ledger"][key], f"总账本:{key}")
        for key in ("move_s", "switch_s", "measure_s"):
            same_float(audit.ledger[key], result[key], key)
        same_float(audit.ledger["success_clear_s"] + audit.ledger["failed_clear_s"], result["clear_s"], "clear_s")
        if (measures, no_signal, failed_clear, len(scan_positions)) != (
                result["measure_count"], result["no_signal_count"], result["failed_clears"], result["scan_position_count"]):
            raise AssertionError("动作统计错误")
        final_state = {str(j): dict(status=c.status, observations=c.observations,
            exclusions=c.exclusions, clear_history=getattr(c, "clear_history", []))
            for j, c in state.channels.items()}
        if normalized(final_state) != read(folder / "final_state.json"):
            raise AssertionError("公开状态重建与final_state不符")
        if normalized(state.absence_proofs) != result["absence_proofs"]:
            raise AssertionError("不存在证据与日志重建不符")
        if hashes != {name: sha(folder / name) for name in FILES}:
            raise AssertionError("审计过程中原始运行文件发生变化")
        output.update(passed=True, actions=len(rows), sources=count,
                      virtual_time_s=audit.virtual_time_s, ledger=audit.ledger,
                      artifact_sha256=hashes)
    except Exception:
        output["error"] = traceback.format_exc()
    output["audit_wall_s"] = time.perf_counter() - began
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--partial", action="store_true")
    parser.add_argument("--policies", nargs="+", choices=("A", "B", "selected"), default=["A", "B", "selected"])
    parser.add_argument("--workers", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    target = args.output.resolve()
    if ROOT not in target.parents or target.exists():
        raise ValueError("独立审计只写本批次目录内的新JSON文件，不覆盖已有记录")
    items, reference_sources = check_catalog()
    tasks, missing, snapshots, manifests = [], [], {}, {}
    for item in items:
        if item["reference"] is not None:
            batch = item["reference"].split("/")[2]
            tasks.append(dict(scene=item["scene"], group=item["group"], policy="selected",
                folder=item["reference"], source_hashes=reference_sources[batch],
                snapshot=str(PROJECT / "outputs/q4" / batch / "source")))
    for policy in dict.fromkeys(args.policies):
        root = ROOT / policy
        manifest_path = root / "manifest.json"
        relevant = [item for item in items if policy != "selected" or item["reference"] is None]
        if not manifest_path.exists():
            missing.extend(dict(policy=policy, case=item["scene"]["name"]) for item in relevant)
            continue
        manifest = read(manifest_path)
        if manifest["policy"] != policy or manifest["catalog_sha256"] != sha(ROOT / "catalog.json"):
            raise AssertionError("批次标签或catalog指纹不一致")
        manifests[policy] = sha(manifest_path)
        snapshots[policy] = check_sources(manifest["hashes"], root / "source")
        for item in relevant:
            folder = root / "cases" / item["scene"]["name"]
            if not (folder / "result.json").exists():
                missing.append(dict(policy=policy, case=item["scene"]["name"]))
                continue
            tasks.append(dict(scene=item["scene"], group=item["group"], policy=policy,
                folder=folder.relative_to(PROJECT).as_posix(), source_hashes=manifest["hashes"],
                snapshot=str(root / "source")))
    rows = []
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        for future in as_completed([executor.submit(check_run, task) for task in tasks]):
            row = future.result()
            rows.append(row)
            print(json.dumps({key: row[key] for key in ("case", "policy", "passed")}, ensure_ascii=False), flush=True)
    rows.sort(key=lambda x: (x["group"], x["case"], x["policy"]))
    passed = all(r["passed"] for r in rows) and (args.partial or not missing)
    result = dict(passed=passed, partial=args.partial, requested_policies=args.policies,
        created_utc=datetime.now(timezone.utc).isoformat(), checked_runs=len(rows),
        checked_actions=sum(r.get("actions", 0) for r in rows),
        missing_runs=missing, failures=sum(not r["passed"] for r in rows),
        catalog_sha256=sha(ROOT / "catalog.json"), manifests_sha256=manifests,
        missing_source_snapshots=snapshots, auditor_sha256=sha(Path(__file__)),
        scope="独立反馈/费用复算及正式Q4公开状态逐步重建；几何核验共享原状态实现；不重跑策略、不使用官方接口", runs=rows)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("passed", "partial", "checked_runs", "checked_actions", "failures")}), flush=True)
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
