"""Q4 各继承策略共同案例整局比较，原接口不改。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

from q4run import generate_q4, run_case, dump
from q4 import Q4Config, Q4InformationState, Q4DirectionalPolicy
from q4_coverage import Q4CoverageInformationState
from q4_anchor_design import Q4ReducedAnchorPolicy
from simulation import Scenario
from astra_guard import check_cached

ROOT = Path(__file__).resolve().parent


def factories(name):
    if name == "directional":
        return Q4DirectionalPolicy, Q4InformationState, Q4Config()
    if name == "anchors31":
        return Q4ReducedAnchorPolicy, Q4CoverageInformationState, Q4Config()
    raise ValueError(name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--policies", nargs="+", required=True)
    parser.add_argument("--seed", type=int, default=43100)
    parser.add_argument("--cases", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    check_cached()
    out = args.output.resolve()
    if ROOT / "runs" not in out.parents:
        raise ValueError("结果放本夜runs内")
    out.mkdir(parents=True, exist_ok=False)
    specs = [(layout, noise, ("random", "outward", "tangent", "aligned")[(i + j) % 4])
             for i, layout in enumerate(("uniform", "edge", "cluster", "line"))
             for j, noise in enumerate(("smooth", "biased", "hashed"))]
    scenes = ([Scenario.from_dict(v) for v in json.loads(args.cases.read_text(encoding="utf-8"))] if args.cases else
              [generate_q4(args.seed + i, *spec) for i, spec in enumerate(specs)])
    dump(out / "cases.json", [s.to_dict() for s in scenes])
    versions = {}
    for prefix, folder in (("night", ROOT), ("base", ROOT.parent / "b_adaptive_q3")):
        for path in folder.glob("*.py"):
            if path.name == "astra_guard.py":
                continue
            relative = f"{prefix}/{path.name}"
            data = path.read_bytes()
            versions[relative] = hashlib.sha256(data).hexdigest()
            dest = out / "source" / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
    configs = {name: factories(name)[2].to_dict() for name in args.policies}
    dump(out / "configs.json", configs)
    dump(out / "manifest.json", dict(created_at=time.time(), python=sys.version, policies=args.policies,
        cases_sha256=hashlib.sha256((out / "cases.json").read_bytes()).hexdigest(), code_sha256=versions,
        purpose="第四问不同布局、误差与方向的共同完整案例"))
    results = []
    for scene in scenes:
        for name in args.policies:
            check_cached()
            policy, state, config = factories(name)
            result = run_case(scene, name, out / "actions" / f"{scene.name}_{name}.jsonl", config=config,
                              policy_factory=policy, state_factory=state)
            results.append(result)
            dump(out / "results.json", results)
            print(json.dumps({k: result[k] for k in ("case", "policy", "success", "cleared", "source_count", "virtual_time_s", "wall_time_s", "failed_clears")}), flush=True)
            if result["error"] and "ASTRA_STOP" in result["error"]:
                raise SystemExit(3)
    if not all(r["success"] for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
