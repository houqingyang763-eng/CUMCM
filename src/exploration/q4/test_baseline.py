"""B0 的关键闭环检查与少量自建整局冒烟；不接官方接口。"""
import argparse
import hashlib
from itertools import permutations
import json
import math
from pathlib import Path
import random
import time
import unittest

from baseline import BaselineConfig, BaselinePolicy, center_route, fixed_discovery_route, make_state
from common import PROJECT, Q4_SYMMETRIC25_ANCHORS
from q4_coverage import q4_coverage_certificate
from simulation import LocalEnvironment, Scenario, Source, generate
from state import audit_state


class BaselineChecks(unittest.TestCase):
    def test_frozen_route_preserves_certified_discovery_set(self):
        route = fixed_discovery_route()
        self.assertEqual(route[0], (0.0, 0.0))
        self.assertEqual(len(route), 25)
        self.assertEqual(set(route), set(Q4_SYMMETRIC25_ANCHORS))
        certificate = q4_coverage_certificate(route)
        self.assertTrue(certificate.complete and certificate.rational_verified)

    def test_center_route_matches_enumeration(self):
        start = (-2.0, 1.0)
        points = [(0.0, 0.0), (9.0, 0.0), (4.0, 7.0)]
        channels = [2, 11, 19]
        order, proxy = center_route(start, channels, points)
        positions = {j: p for j, p in zip(channels, points)}
        actual = sum(math.dist(a, b) for a, b in zip(
            [start] + [positions[j] for j in order], [positions[j] for j in order]))
        best = min(sum(math.dist(a, b) for a, b in zip([start] + list(xs), xs))
                   for xs in permutations(points))
        self.assertAlmostEqual(actual, best)
        self.assertLessEqual(proxy, actual + 1e-9)
        self.assertLessEqual(actual - proxy, 3e-6)

    def test_directional_negative_does_not_delete_nearby_true_source(self):
        source = Source(1, (900.0, 0.0), 1000.0, 180.0)
        env = LocalEnvironment(Scenario("negative_case", 100, "custom", "zero", (source,)))
        state = make_state()
        for q in ((0.0, 0.0), (1000.0, 0.0)):
            action = dict(kind="measure", position=q, channel=1)
            state.update(action, env.act(action))
            audit_state(state, env)
        self.assertEqual(state.channels[1].observations[-1][1], "no_signal")
        self.assertEqual(state.channels[1].status, "found")

    def test_forced_strip_has_finite_clearance_with_fixed_error(self):
        source = Source(1, (1400.0, 0.0), 1500.0, 180.0)
        env = LocalEnvironment(Scenario("strip_case", 100, "custom", "biased", (source,)))
        state = make_state()
        first = dict(kind="measure", position=(0.0, 0.0), channel=1)
        state.update(first, env.act(first))
        for j, c in state.channels.items():
            if j != 1:
                c.status = "absent"  # 独立单源局部夹具，其余频道由夹具声明不存在。
        policy = BaselinePolicy(BaselineConfig(local_measurement_limit=0))
        policy.phase = "service"
        clear_count = 0
        while not state.complete and clear_count <= 100:
            action = policy.choose(state)
            self.assertEqual(action["kind"], "clear")
            state.update(action, env.act(action))
            audit_state(state, env)
            clear_count += 1
        self.assertTrue(state.complete)
        self.assertEqual(env.cleared, {1})
        self.assertLessEqual(clear_count, 100)
        self.assertIn(1, policy.fallback_targets)


def smoke():
    output = PROJECT / "outputs" / "experiments" / "q4" / "baseline_smoke"
    output.mkdir(parents=True, exist_ok=False)

    def dump(name, data):
        (output / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    configs, cases, results = BaselineConfig().to_dict(), [], []
    for seed, layout, noise, mode in ((913301, "uniform", "smooth", "random"),
                                    (913302, "edge", "biased", "outward")):
        raw = generate(seed, layout, noise)
        rng = random.Random(seed + 970000)
        sources = []
        for i, source in enumerate(raw.sources):
            orientation = None
            if i % 3:
                orientation = (rng.uniform(0, 360) if mode == "random" else
                               math.degrees(math.atan2(source.position[1], source.position[0])) % 360)
            sources.append(Source(source.channel, source.position,
                                  source.radius if mode == "random" else 1000.0, orientation))
        scene = Scenario(f"b0_{layout}_{mode}_{noise}_{seed}", seed, layout, noise, tuple(sources))
        cases.append(scene.to_dict())
        env, state, policy = LocalEnvironment(scene), make_state(), BaselinePolicy()
        actions, error = [], None
        started = time.perf_counter()
        try:
            while not state.complete:
                if len(actions) >= 2500:
                    raise AssertionError("冒烟动作超限")
                action = policy.choose(state)
                response = env.act(action)
                state.update(action, response)
                audit_state(state, env)
                actions.append(dict(step=len(actions) + 1, **action, response=response))
        except Exception as exc:
            error = repr(exc)
        wall = time.perf_counter() - started
        success = state.complete and len(env.cleared) == len(scene.sources)
        result = dict(case=scene.name, success=success, error=error, cleared=len(env.cleared),
                      source_count=len(scene.sources), virtual_time_s=env.virtual_time_s,
                      per_source_s=env.virtual_time_s / len(env.cleared) if env.cleared else None,
                      wall_time_s=wall, actions=len(actions),
                      failed_clears=sum(row["kind"] == "clear" and
                          row["response"]["clear_result"] != "success" for row in actions),
                      metadata=policy.metadata())
        results.append(result)
        (output / f"{scene.name}.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in actions), encoding="utf-8")
        dump("results.json", results)
        print(json.dumps({k: result[k] for k in ("case", "success", "error", "cleared", "source_count",
              "virtual_time_s", "per_source_s", "wall_time_s", "failed_clears")}, ensure_ascii=False), flush=True)
    dump("cases.json", cases)
    dump("config.json", configs)
    local_files = [Path(__file__), Path(__file__).with_name("baseline.py"),
                   Path(__file__).with_name("BASELINE.md"), Path(__file__).with_name("common.py")]
    dump("manifest.json", dict(kind="B0独立少量冒烟，不是官方结果", files={
        str(path.relative_to(PROJECT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in local_files}))
    if not all(row["success"] for row in results):
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if args.smoke:
        smoke()
    else:
        unittest.main(argv=[__file__])
