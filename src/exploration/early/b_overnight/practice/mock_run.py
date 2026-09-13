"""冻结策略经本进程假 HTTP 服务跑完整反馈闭环，不连接官方端口。"""
import argparse
import hashlib
import json
from pathlib import Path
import time

from adapter import NIGHT, ROOT, PracticeClient, dump, run_session, strategy
from mock_service import MockAuthorization, MockService
from provenance import capture_sources, save_sources, source_hashes, sources_unchanged
from simulation import generate
from q4run import generate_q4, audit_orientation
from state import audit_state
from astra_guard import check_cached


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--suite", choices=("joint25", "sweep", "legacy"), default="joint25")
    parser.add_argument("--configured", type=Path, default=NIGHT / "runs/configuration_search/selected_config.json")
    args = parser.parse_args()
    check_cached()
    out = args.output.resolve()
    if ROOT not in out.parents:
        raise ValueError("假服务产物必须放 practice 子目录")
    out.mkdir(parents=True, exist_ok=False)
    if args.suite == "legacy":
        configured = json.loads(args.configured.read_text(encoding="utf-8"))
        cases = [(3, "completion", generate(42100, "uniform", "smooth"), None),
                 (3, "configured", generate(42101, "cluster", "hashed"), configured),
                 (4, "directional", generate_q4(42102, "edge", "biased", "outward"), None)]
    elif args.suite == "sweep":
        cases = [(3, "sweep", generate(98100, "uniform", "smooth"), None)]
    else:
        cases = [(3, "completion", generate(42100, "uniform", "smooth"), None),
                 (4, "joint25", generate_q4(96100, "edge", "biased", "outward"), None),
                 (4, "joint25", generate_q4(96101, "uniform", "hashed", "tangent"), None)]
    dump(out / "cases.json", [scene.to_dict() for _, _, scene, _ in cases])
    bundle = capture_sources()
    save_sources(out, bundle)
    manifest = {"created_at": time.time(), "code_sha256": source_hashes(bundle), "suite": args.suite,
                "cases_sha256": hashlib.sha256((out / "cases.json").read_bytes()).hexdigest(),
                "source_capture": "运行前保存字节和散列，运行后核对未改变",
                "scope": "本进程自建HTTP假服务，未访问官方端口或启动官方测试"}
    if args.suite == "legacy":
        manifest["configured_sha256"] = hashlib.sha256(args.configured.read_bytes()).hexdigest()
    dump(out / "manifest.json", manifest)
    results = []
    for problem, name, scene, config in cases:
        check_cached()
        policy, state = strategy(problem, name, config)
        case_out = out / f"{name}_{scene.name}"
        with MockService(scene, drop_once_path="/measure") as service:
            client = PracticeClient("MOCK_ONLY", port=service.port, timeout=2, retries=2)
            audit_count = guard_count = 0
            def guard():
                nonlocal guard_count
                guard_count += 1
                check_cached()
            def audit(current):
                nonlocal audit_count
                audit_count += 1
                audit_state(current, service.environment)
                if problem == 4:
                    audit_orientation(current, service.environment)
            result = run_session(client, policy, state, problem, MockAuthorization(service, problem), case_out,
                                 guard=guard, audit_hook=audit)
            result["case"] = scene.name
            result["strategy_name"] = name
            result["mock_source_count"] = len(scene.sources)
            result["mock_directional_count"] = sum(s.orientation is not None for s in scene.sources)
            result["mock_cleared"] = len(service.environment.cleared)
            result["mock_all_cleared"] = len(service.environment.cleared) == len(scene.sources)
            grouped = {}
            for call in service.calls:
                grouped.setdefault(call["request_id"], []).append(call)
            repeats = [calls for calls in grouped.values() if len(calls) > 1]
            retry_ok = (service.dropped and len(repeats) == 1 and len(repeats[0]) == 2
                        and repeats[0][0] == repeats[0][1] and result["retry_count"] == 1)
            unique_ok = len(service.cache) == result["actions"] + 2 == len(client.records)
            ledger_ok = abs(sum(client.ledger.values()) - service.environment.virtual_time_s) < 1e-5
            result["dropped_response_was_retried"] = retry_ok
            result["service_execution_count"] = len(service.cache)
            result["retry_executed_once"] = unique_ok
            result["independent_ledger_matches_environment"] = ledger_ok
            result["public_feedback_audit_count"] = audit_count
            result["guard_checks"] = guard_count
            result["sources_unchanged"] = sources_unchanged(bundle)
            dump(case_out / "service_calls.json", service.calls)
            dump(case_out / "retry_evidence.json", {"repeated_request_calls": repeats, "identical_path_id_body_sha256": retry_ok,
                "executed_unique_requests": len(service.cache), "expected_unique_requests": result["actions"] + 2,
                "wire_requests": len(service.calls), "independent_ledger_matches_environment": ledger_ok})
            dump(case_out / "summary.json", result)
            results.append(result)
            dump(out / "results.json", results)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    manifest["sources_unchanged_at_end"] = sources_unchanged(bundle)
    manifest["completed_at"] = time.time()
    dump(out / "manifest.json", manifest)
    if not all(r["complete_by_evidence"] and r["mock_all_cleared"] and r["exited"] and not r["error_type"]
               and r["dropped_response_was_retried"] and r["retry_executed_once"]
               and r["independent_ledger_matches_environment"] and r["public_feedback_audit_count"] == r["actions"]
               and r["sources_unchanged"] for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
