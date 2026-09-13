"""三个冻结策略经本进程假 HTTP 服务跑完整反馈闭环。"""
import argparse
import hashlib
import json
from pathlib import Path
import time

from adapter import NIGHT, ROOT, PracticeClient, dump, run_session, strategy
from mock_service import MockAuthorization, MockService
from simulation import generate
from q4run import generate_q4, audit_orientation
from state import audit_state
from astra_guard import check_cached


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--configured", type=Path, default=NIGHT / "runs/configuration_search/selected_config.json")
    args = parser.parse_args()
    check_cached()
    out = args.output.resolve()
    if ROOT not in out.parents:
        raise ValueError("假服务产物必须放 practice 子目录")
    out.mkdir(parents=True, exist_ok=False)
    configured = json.loads(args.configured.read_text(encoding="utf-8"))
    cases = [(3, "completion", generate(42100, "uniform", "smooth"), None),
             (3, "configured", generate(42101, "cluster", "hashed"), configured),
             (4, "directional", generate_q4(42102, "edge", "biased", "outward"), None)]
    dump(out / "cases.json", [scene.to_dict() for _, _, scene, _ in cases])
    results = []
    for problem, name, scene, config in cases:
        check_cached()
        policy, state = strategy(problem, name, config)
        with MockService(scene, drop_once_path="/measure") as service:
            client = PracticeClient("MOCK_ONLY", port=service.port, timeout=2, retries=2)
            def audit(current):
                audit_state(current, service.environment)
                if problem == 4:
                    audit_orientation(current, service.environment)
            result = run_session(client, policy, state, problem, MockAuthorization(service, problem), out / name, audit_hook=audit)
            result["mock_source_count"] = len(scene.sources)
            result["mock_cleared"] = len(service.environment.cleared)
            result["mock_all_cleared"] = len(service.environment.cleared) == len(scene.sources)
            result["dropped_response_was_retried"] = result["retry_count"] == 1
            result["service_execution_count"] = len(service.cache)
            dump(out / name / "summary.json", result)
            results.append(result)
            dump(out / "results.json", results)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    paths = [*ROOT.glob("*.py"), NIGHT / "task_cost.py", NIGHT / "q4.py", NIGHT.parent / "b_env_probe/client.py",
             *(NIGHT.parent / "b_adaptive_q3").glob("*.py")]
    hashes = {}
    for path in paths:
        relative = path.relative_to(NIGHT.parent)
        data = path.read_bytes()
        hashes[str(relative)] = hashlib.sha256(data).hexdigest()
        dest = out / "source" / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    dump(out / "manifest.json", {"created_at": time.time(), "code_sha256": hashes,
                                 "configured_sha256": hashlib.sha256(args.configured.read_bytes()).hexdigest(),
                                 "scope": "本进程自建HTTP假服务，未访问官方端口或启动官方测试"})
    if not all(r["complete_by_evidence"] and r["mock_all_cleared"] and r["exited"] and not r["error_type"] for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
