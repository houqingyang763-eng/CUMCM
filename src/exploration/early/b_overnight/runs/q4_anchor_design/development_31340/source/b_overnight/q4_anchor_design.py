"""Q4 31点严格发现参照：删去原37点中半径2700m的六个顶点。"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time

from q4 import (Q4_ANCHORS, Q4Config, Q4DirectionalPolicy, Q4InformationState,
                _arc, _subtract)
from q4_coverage import Q4CoverageInformationState, q4_coverage_certificate, verify_q4_certificate
from q4run import dump, generate_q4, report, run_case
from simulation import LocalEnvironment, Scenario, Source
from astra_guard import check_cached
import geometry as g


Q4_REDUCED_ANCHORS = tuple(q for q in Q4_ANCHORS if abs(math.hypot(*q) - 2700) > 1e-5)
REMOVED_ANCHORS = tuple(q for q in Q4_ANCHORS if q not in Q4_REDUCED_ANCHORS)


class Q4ReducedAnchorPolicy(Q4DirectionalPolicy):
    """定位规则不变；未知频道采用已严格验证的31点有限参照。"""
    def candidate_positions(self, state):
        return [q for q in super().candidate_positions(state) if q not in REMOVED_ANCHORS]

    def utility(self, c, q, mask):
        if c.status != "unknown":
            return super().utility(c, q, mask)
        return self.config.q4_anchor_value_s if q in Q4_REDUCED_ANCHORS and q not in c.measured else 0.0

    def fallback(self, state):
        self.fallback_started = True
        near = [c for c in state.channels.values() if c.status == "found" and c.near_position is not None]
        if near:
            c = min(near, key=lambda c: g.distance(state.position, c.near_position))
            return self.action("clear", c.near_position, c.channel, "q4_31_fallback_near")
        needed = [(g.distance(state.position, q) / 5 + 5 + int(j != state.measuring_channel), q, j)
                  for j, c in state.channels.items() if c.status == "unknown"
                  for q in Q4_REDUCED_ANCHORS if q not in c.measured]
        if needed:
            _, q, j = min(needed)
            return self.action("measure", q, j, "q4_31_fallback_discovery")
        # 使用不同状态实现或遇到保守证书未闭合时，仍保留原37点后备。
        return super().fallback(state)


def blind_witness(points, cert):
    """构造并在自建环境核对某位置和朝向能让全部测点返回无信号。"""
    for p in cert.witness_points():
        intervals = [(0.0, 360.0)]
        for q in points:
            if g.distance(p, q) <= 1000 + 1e-8:
                intervals = _subtract(intervals, _arc(math.degrees(math.atan2(q[1] - p[1], q[0] - p[0])) % 360))
        if not intervals:
            continue
        a, b = max(intervals, key=lambda pair: pair[1] - pair[0])
        if b - a <= 1e-5:
            continue
        angle = (a + b) / 2
        env = LocalEnvironment(Scenario("coverage_counterexample_unit", 0, "unit", "zero",
                                        (Source(1, p, 1000, angle),)))
        responses = [env.act(dict(kind="measure", position=q, channel=1))["measure_result"] for q in points]
        if all(response == "no_signal" for response in responses):
            return dict(position=p, orientation_deg=angle, reception_radius_m=1000,
                        feasible_orientation_interval=(a, b),
                        checked_points=len(points), no_signal_count=len(responses))
    return None


def design_evidence(output):
    check_cached()
    output.mkdir(parents=True, exist_ok=False)
    points25 = [q for q in Q4_REDUCED_ANCHORS if abs(math.hypot(*q) - 1800) > 1e-5]
    points750 = [(q[0] * 5 / 6, q[1] * 5 / 6) for q in Q4_REDUCED_ANCHORS]
    designs = [("original37", Q4_ANCHORS), ("reduced31", Q4_REDUCED_ANCHORS),
               ("remove_middle25", points25), ("shrunken750_31", points750)]
    records = []
    for name, points in designs:
        check_cached()
        started = time.perf_counter()
        cert = q4_coverage_certificate(points)
        if cert.complete:
            verify_q4_certificate(cert, require_complete=True)
        record = dict(name=name, point_count=len(points), points=points, complete=cert.complete,
                      certificate=cert.to_dict(include_leaves=True), wall_s=time.perf_counter() - started,
                      blind_witness=None if cert.complete else blind_witness(points, cert))
        records.append(record)
    attempts = []
    for i, q in sorted(enumerate(Q4_REDUCED_ANCHORS), key=lambda pair: math.hypot(*pair[1])):
        check_cached()
        points = Q4_REDUCED_ANCHORS[:i] + Q4_REDUCED_ANCHORS[i + 1:]
        cert = q4_coverage_certificate(points)
        attempts.append(dict(removed=q, complete=cert.complete, **cert.statistics))
    dump(output / "designs.json", records)
    dump(output / "single_deletion_checks.json", attempts)
    assert records[1]["complete"] and records[1]["certificate"]["rational_verified"]
    assert len(Q4_REDUCED_ANCHORS) == 31 and len(REMOVED_ANCHORS) == 6
    assert records[2]["blind_witness"] is not None and records[3]["blind_witness"] is not None
    summary = [dict(name=r["name"], point_count=r["point_count"], complete=r["complete"],
                    has_blind_witness=r["blind_witness"] is not None) for r in records]
    print(json.dumps(dict(designs=summary, deletion_certificates=sum(r["complete"] for r in attempts))))


def batch(output, seed):
    check_cached()
    output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parent
    specs = [("uniform", "smooth", "random"), ("edge", "biased", "outward"),
             ("cluster", "hashed", "tangent"), ("line", "hashed", "aligned")]
    scenes = [generate_q4(seed + i, *spec) for i, spec in enumerate(specs)]
    dump(output / "cases.json", [scene.to_dict() for scene in scenes])
    dump(output / "config.json", Q4Config().to_dict())
    hashes = {}
    sources = [root / name for name in ("q4_anchor_design.py", "q4.py", "q4_coverage.py",
                                        "coverage.py", "task_cost.py", "q4run.py")]
    sources += [root.parent / "b_adaptive_q3" / name for name in
                ("geometry.py", "state.py", "policy.py", "simulation.py")]
    for path in sources:
        relative, data = path.relative_to(root.parent), path.read_bytes()
        hashes[str(relative)] = hashlib.sha256(data).hexdigest()
        dest = output / "source" / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    dump(output / "manifest.json", dict(code_sha256=hashes, created_at=time.time(), python=sys.version,
                                         purpose="严格31点发现参照的四布局新种子完整对照",
                                         cases_sha256=hashlib.sha256((output / "cases.json").read_bytes()).hexdigest()))
    results = []
    for scene in scenes:
        for name, policy_cls, state_cls in (("directional", Q4DirectionalPolicy, Q4InformationState),
                                            ("anchors31", Q4ReducedAnchorPolicy, Q4CoverageInformationState)):
            check_cached()
            result = run_case(scene, name, output / "actions" / f"{scene.name}_{name}.jsonl",
                              policy_factory=policy_cls, state_factory=state_cls)
            results.append(result)
            dump(output / "results.json", results)
            report(results, output)
            compact = {k: v for k, v in result.items() if k != "absence_proofs"}
            compact["absence_proof_kinds"] = sorted({p["kind"] for p in result["absence_proofs"].values()})
            print(json.dumps(compact, ensure_ascii=False), flush=True)
            if result["error"] and "ASTRA_STOP" in result["error"]:
                raise SystemExit(3)
    if not all(row["success"] for row in results):
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--design", type=Path)
    parser.add_argument("--batch", type=Path)
    parser.add_argument("--seed", type=int, default=31340)
    args = parser.parse_args()
    output = (args.design or args.batch).resolve() if args.design or args.batch else None
    root = Path(__file__).resolve().parent / "runs" / "q4_anchor_design"
    if output is None or (output != root and root not in output.parents):
        raise ValueError("指定 --design/--batch，产物必须放 runs/q4_anchor_design/")
    if args.design:
        design_evidence(output)
    else:
        batch(output, args.seed)
