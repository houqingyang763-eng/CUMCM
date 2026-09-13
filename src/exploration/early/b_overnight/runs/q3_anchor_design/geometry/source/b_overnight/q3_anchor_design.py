"""第三问1130米六点环：连续覆盖证明及少量完整开发对照。"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time

from task_cost import CompletionCostConfig, CompletionCostPolicy
from coverage import CoverageInformationState, coverage_certificate, verify_certificate
from astra_guard import check_cached
import geometry as g
from simulation import generate, LocalEnvironment, Scenario, Source
from runner import dump

ROOT = Path(__file__).resolve().parent
Q3_RING_RADIUS_M = 1130.0
Q3_RING_ANCHORS = ((0.0, 0.0),) + tuple(g.mul(g.unit(k * 60), Q3_RING_RADIUS_M) for k in range(6))


def ring_covering_radius(ring_radius, domain_radius=1800.0):
    """中心加规则六点环的连续最远最近点距离；环半径须在目标半径内。"""
    if not 0 < ring_radius <= domain_radius:
        raise ValueError("此解析式要求0<环半径<=目标半径")
    return max(ring_radius / math.sqrt(3),
               math.sqrt(domain_radius ** 2 + ring_radius ** 2
                         - math.sqrt(3) * domain_radius * ring_radius))


class Q3RingCompletionPolicy(CompletionCostPolicy):
    """仅调整未知发现参照及对应回退，已发现目标沿用Completion。"""
    def __init__(self, config=None, reference_only=False):
        super().__init__(config, reference_only)
        self.search_anchors = Q3_RING_ANCHORS
        self.anchor_certificate = coverage_certificate([(q, 1000) for q in self.search_anchors])
        if not self.anchor_certificate.complete or not self.anchor_certificate.rational_verified:
            raise ValueError("1130米发现环未取得完整连续覆盖证书")

    def candidate_positions(self, state):
        points = super().candidate_positions(state)
        if any(c.status == "found" for c in state.channels.values()):
            # 已发现源的定位候选保持原样，避免将点位设计混入定位改动。
            return points
        return list(dict.fromkeys([state.position] + [q for q in points if q not in g.ANCHORS]
                                  + list(self.search_anchors)))

    def utility(self, c, q, mask):
        if c.status != "unknown":
            return super().utility(c, q, mask)
        if q in c.measured:
            return 0.0
        gain = (c.sample_mask & mask).bit_count() / len(g.GRID)
        due = q in self.search_anchors
        return self.config.discovery_weight * self.config.discovery_value_s * (gain + (.015 if due else 0))

    def fallback(self, state):
        self.fallback_started = True
        near = [c for c in state.channels.values() if c.status == "found" and c.near_position is not None]
        if near:
            c = min(near, key=lambda c: g.distance(state.position, c.near_position))
            return self.action("clear", c.near_position, c.channel, "q3_ring_fallback_near")
        needed = [(g.distance(state.position, q) / 5 + 5 + int(j != state.measuring_channel), q, j)
                  for j, c in state.channels.items() if c.status == "unknown"
                  for q in self.search_anchors if q not in c.measured]
        if needed:
            _, q, j = min(needed)
            return self.action("measure", q, j, "q3_ring_fallback_discovery")
        return super().fallback(state)


def snapshot(output, purpose):
    paths = [ROOT / n for n in ("q3_anchor_design.py", "coverage.py", "task_cost.py", "runner.py")]
    paths += [ROOT.parent / "b_adaptive_q3" / n for n in ("geometry.py", "state.py", "policy.py", "simulation.py")]
    hashes = {}
    for path in paths:
        data, relative = path.read_bytes(), path.relative_to(ROOT.parent)
        hashes[str(relative)] = hashlib.sha256(data).hexdigest()
        destination = output / "source" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    dump(output / "manifest.json", dict(code_sha256=hashes, created_at=time.time(), python=sys.version, purpose=purpose))


def geometry_evidence(output):
    check_cached()
    output.mkdir(parents=True, exist_ok=False)
    original = tuple(g.ANCHORS)
    cert = coverage_certificate([(q, 1000) for q in Q3_RING_ANCHORS])
    assert cert.complete and verify_certificate(cert, require_complete=True)
    state = CoverageInformationState()
    for q in Q3_RING_ANCHORS:
        state.update(dict(kind="measure", position=q, channel=1),
                     dict(accepted=True, measure_result="no_signal", virtual_time_s=state.virtual_time_s + 5))
    assert state.channels[1].status == "absent"
    assert state.absence_reasons[1] == "negative_disk_union"
    assert len(state.channels[1].anchors_missed) == 1
    assert tuple(g.ANCHORS) == original
    policy = Q3RingCompletionPolicy()
    initial = CoverageInformationState()
    assert set(policy.candidate_positions(initial)) == set(Q3_RING_ANCHORS)
    # 已知源情况下，候选及收益必须和父类一致。
    known = CoverageInformationState()
    known.update(dict(kind="measure", position=(0, 0), channel=1),
                 dict(accepted=True, measure_result="direction", svd_deg=0, virtual_time_s=5))
    baseline = CompletionCostPolicy()
    assert policy.candidate_positions(known) == baseline.candidate_positions(known)
    policy._prepare(known)
    baseline._prepare(known)
    for q in policy.candidate_positions(known):
        assert policy.utility(known.channels[1], q, g.coverage_mask(q)) == baseline.utility(known.channels[1], q, g.coverage_mask(q))
    # 环再向内到1120米时，目标边界30度方向确有盲区。
    invalid_ring = ((0, 0),) + tuple(g.mul(g.unit(k * 60), 1120) for k in range(6))
    witness = g.mul(g.unit(30), 1800)
    env = LocalEnvironment(Scenario("q3_ring_blind_unit", 0, "unit", "zero", (Source(1, witness, 1000),)))
    responses = [env.act(dict(kind="measure", position=q, channel=1))["measure_result"] for q in invalid_ring]
    assert all(r == "no_signal" for r in responses)
    assert not coverage_certificate([(q, 1000) for q in invalid_ring]).complete
    theoretical_minimum = 1800 * math.cos(math.pi / 6) - math.sqrt(1000 ** 2 - (1800 * math.sin(math.pi / 6)) ** 2)
    result = dict(points=Q3_RING_ANCHORS, theoretical_minimum_ring_m=theoretical_minimum,
                  selected_ring_m=1130, maximum_nearest_distance_m=ring_covering_radius(1130),
                  original_maximum_nearest_distance_m=ring_covering_radius(1200),
                  nominal_open_route_m=6 * 1130, original_nominal_open_route_m=6 * 1200,
                  reception_margin_m=1000 - ring_covering_radius(1130),
                  certificate=cert.to_dict(include_leaves=True),
                  checks=dict(new_state_absent=True, old_anchor_hits=1, original_constants_unchanged=True,
                              known_candidates_and_utility_unchanged=True),
                  invalid1120=dict(source_position=witness, nearest_distance_m=ring_covering_radius(1120),
                                   reception_radius_m=1000, all_no_signal=True))
    dump(output / "geometry.json", result)
    snapshot(output, "Q3 1130米六点环连续证书、已知策略不变和1120米盲区构造")
    print(json.dumps({k:v for k,v in result.items() if k not in ("certificate", "points")}, ensure_ascii=False))


def batch(output, seed):
    import runner
    check_cached()
    output.mkdir(parents=True, exist_ok=False)
    specs = [("uniform", "smooth"), ("edge", "biased"), ("cluster", "hashed"), ("line", "hashed")]
    scenes = [generate(seed+i, *spec) for i, spec in enumerate(specs)]
    dump(output / "cases.json", [s.to_dict() for s in scenes])
    dump(output / "config.json", CompletionCostConfig().to_dict())
    snapshot(output, "Q3 1130米发现环与原Completion的四布局新种子完整对照")
    original_factories = runner.factories
    def local_factories(name, overrides=None):
        if name == "ring1130":
            return lambda: Q3RingCompletionPolicy(CompletionCostConfig(**(overrides or {}))), CoverageInformationState
        return original_factories(name, overrides)
    # 只在当前实验进程注册额外策略，复用冻结runner的计费与逐步审计。
    runner.factories = local_factories
    results = []
    try:
        for scene in scenes:
            for name in ("completion", "ring1130"):
                check_cached()
                result = runner.run_case(scene, name, trace_path=output / "actions" / f"{scene.name}_{name}.jsonl")
                results.append(result)
                dump(output / "results.json", results)
                print(json.dumps(result, ensure_ascii=False), flush=True)
                if result["error"] and "ASTRA_STOP" in result["error"]:
                    raise SystemExit(3)
    finally:
        runner.factories = original_factories
    if not all(r["success"] for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--geometry", type=Path)
    parser.add_argument("--batch", type=Path)
    parser.add_argument("--seed", type=int, default=31580)
    args = parser.parse_args()
    target = args.geometry or args.batch
    output = target.resolve() if target else None
    allowed = ROOT / "runs" / "q3_anchor_design"
    if output is None or allowed not in output.parents:
        raise ValueError("必须指定geometry或batch，产物限 runs/q3_anchor_design/ 子目录")
    if args.geometry:
        geometry_evidence(output)
    else:
        batch(output, args.seed)
