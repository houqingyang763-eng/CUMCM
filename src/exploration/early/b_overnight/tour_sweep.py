"""发现网络开放路线：Q3精确动态规划，Q4多起点最近邻+有界2-opt。"""
import argparse
from functools import lru_cache
import hashlib
import itertools
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent / "b_adaptive_q3"
sys.path.insert(0, str(BASE))
from sweep_policy import Q3SweepPolicy, Q4SweepPolicy
from q4_anchor_design import Q4Symmetric25Policy
from q4_joint_state import Q4JointCoverageInformationState
from q4 import Q4Config
import geometry as g
from astra_guard import check_cached


def distance_table(start, nodes):
    points = list(nodes) + [start]
    return [[g.distance(a, b) for b in points] for a in points]


def route_length(route, distances, start_index):
    return sum(distances[a][b] for a, b in zip([start_index] + list(route), route))


def nearest_route(distances, start_index, first=None):
    remaining, route, current = set(range(start_index)), [], start_index
    if first is not None:
        route.append(first)
        remaining.remove(first)
        current = first
    while remaining:
        nxt = min(remaining, key=lambda i: (distances[current][i], i))
        route.append(nxt)
        remaining.remove(nxt)
        current = nxt
    return tuple(route)


def exact_open_route(distances, n):
    """固定起点、自由终点的Held–Karp；节点索引在相同距离时确定性破平局。"""
    @lru_cache(None)
    def solve(current, mask):
        if not mask:
            return 0.0, ()
        choices = []
        for j in range(n):
            if mask & (1 << j):
                cost, tail = solve(j, mask ^ (1 << j))
                choices.append((distances[current][j] + cost, (j,) + tail))
        return min(choices)
    cost, route = solve(n, (1 << n) - 1)
    return route, cost


def two_opt_open(route, distances, start_index, max_passes):
    """固定起点、可变终点的反转邻域；最后一个节点后没有回到起点的边。"""
    route = list(route)
    swaps = 0
    for _ in range(max_passes):
        best = (0.0, None, None)
        for i in range(len(route) - 1):
            a = start_index if i == 0 else route[i - 1]
            b = route[i]
            for j in range(i + 1, len(route)):
                c = route[j]
                delta = distances[a][c] - distances[a][b]
                if j + 1 < len(route):
                    d = route[j + 1]
                    delta += distances[b][d] - distances[c][d]
                if delta < best[0] - 1e-9:
                    best = (delta, i, j)
        if best[1] is None:
            break
        _, i, j = best
        route[i:j + 1] = reversed(route[i:j + 1])
        swaps += 1
    return tuple(route), swaps


def optimize_open_route(start, nodes, previous=(), exact_limit=8):
    nodes = tuple(sorted(set(tuple(p) for p in nodes)))
    n = len(nodes)
    if not n:
        return dict(route=[], route_length_m=0.0, nearest_length_m=0.0,
                    method="empty", two_opt_swaps=0, starts=0)
    distances = distance_table(start, nodes)
    nearest = nearest_route(distances, n)
    nearest_length = route_length(nearest, distances, n)
    if n <= exact_limit:
        route, length = exact_open_route(distances, n)
        method, starts, swaps = "held_karp_exact", 1, 0
    else:
        initial = {nearest}
        initial.update(nearest_route(distances, n, first=j) for j in range(n))
        lookup = {p: i for i, p in enumerate(nodes)}
        old = tuple(lookup[tuple(p)] for p in previous if tuple(p) in lookup)
        if len(old) == n and len(set(old)) == n:
            initial.add(old)
        best = (nearest_length, nearest)
        swaps = 0
        for candidate in sorted(initial):
            # 原剩余路线本身亦入选，浮点反转不得使重规划结果更差。
            best = min(best, (route_length(candidate, distances, n), candidate))
            improved, count = two_opt_open(candidate, distances, n, max_passes=2 * n)
            swaps += count
            best = min(best, (route_length(improved, distances, n), improved))
        length, route = best
        method, starts = "multistart_nn_open_2opt", len(initial)
    assert set(route) == set(range(n)) and len(route) == n
    assert length <= nearest_length + 1e-7
    return dict(route=[nodes[i] for i in route], route_length_m=length,
                nearest_length_m=nearest_length, method=method, two_opt_swaps=swaps, starts=starts)


class TourSweepMixin:
    def __init__(self, config=None):
        super().__init__(config)
        self.previous_tour = ()
        self.tour_events = []

    def choose(self, state):
        action = super().choose(state)
        if action is None or action.get("reason") != "sweep_next_discovery_node":
            return action
        unknown = [c for c in state.channels.values() if c.status == "unknown"]
        needed = [q for q in self.sweep_anchors if any(q not in c.measured for c in unknown)]
        stamp = time.perf_counter()
        result = optimize_open_route(state.position, needed, self.previous_tour)
        planning_s = time.perf_counter() - stamp
        self.previous_tour = result["route"]
        q = tuple(result["route"][0])
        channels = [c.channel for c in unknown if q not in c.measured]
        j = state.measuring_channel if state.measuring_channel in channels else min(channels)
        self.tour_events.append(dict(step_before=state.actions, position=state.position,
                                     needed_count=len(needed), original_next=action["position"],
                                     chosen_next=q, changed=q != tuple(action["position"]),
                                     planning_s=planning_s, **result))
        self.stats["tour_replans"] = len(self.tour_events)
        self.stats["tour_changed_next"] = sum(e["changed"] for e in self.tour_events)
        self.stats["tour_planning_s"] = sum(e["planning_s"] for e in self.tour_events)
        return self.action("measure", q, j, "sweep_tour_next_discovery_node")


class Q3TourSweepPolicy(TourSweepMixin, Q3SweepPolicy):
    pass


class Q4TourSweepPolicy(TourSweepMixin, Q4SweepPolicy):
    pass


def route_checks():
    """小规模独立穷举、开放终点与Q4完整网络的必要核对。"""
    from q4_anchor_design import Q4_SYMMETRIC25_ANCHORS
    scenes = [((0, 0), [(1, 0), (3, 0), (10, 0)]),
              ((.2, -.3), [(0, 0), (1, 4), (-2, 3), (5, 1), (2, -3), (-4, -1)])]
    rows = []
    for start, nodes in scenes:
        result = optimize_open_route(start, nodes)
        brute = min(sum(g.distance(a, b) for a, b in zip((start,) + order, order))
                    for order in itertools.permutations(nodes))
        assert abs(result["route_length_m"] - brute) < 1e-10
        rows.append(dict(nodes=len(nodes), exact_length_m=brute, exact_matches_permutations=True))
    assert rows[0]["exact_length_m"] == 10, "开放路线不应回程"
    points = tuple(q for q in Q4_SYMMETRIC25_ANCHORS if q != (0, 0))
    first = optimize_open_route((0, 0), points)
    assert len(first["route"]) == 24 and first["method"] == "multistart_nn_open_2opt"
    second = optimize_open_route(first["route"][0], first["route"][1:], first["route"])
    previous_tail = sum(g.distance(a, b) for a, b in zip(first["route"], first["route"][1:]))
    assert second["route_length_m"] <= previous_tail + 1e-7
    # 显式对每种反转验证开放2-opt边差公式，不依赖优化函数的结果。
    matrix = distance_table((0, 0), [(2, 7), (8, 2), (-1, -4), (3, -6)])
    route = (0, 1, 2, 3)
    for i in range(3):
        for j in range(i + 1, 4):
            changed = route[:i] + tuple(reversed(route[i:j + 1])) + route[j + 1:]
            a, b, c = (4 if i == 0 else route[i - 1]), route[i], route[j]
            delta = matrix[a][c] - matrix[a][b]
            if j < 3:
                d = route[j + 1]
                delta += matrix[b][d] - matrix[c][d]
            assert abs(route_length(changed, matrix, 4) - route_length(route, matrix, 4) - delta) < 1e-10
    return dict(checks=rows, open_endpoint_delta_checked=True, previous_tail_retained=True,
                q4_first_nearest_m=first["nearest_length_m"], q4_first_tour_m=first["route_length_m"])


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def batch(out):
    import q4run
    from test_q4_joint_state import audit_joint
    check_cached()
    out.mkdir(parents=True, exist_ok=False)
    cases = [q4run.generate_q4(76300 + i, *spec) for i, spec in enumerate(
        (("uniform", "smooth", "random"), ("edge", "biased", "outward"),
         ("cluster", "hashed", "tangent"), ("line", "hashed", "aligned")))]
    policies = [("joint25", Q4Symmetric25Policy), ("sweep25", Q4SweepPolicy), ("tour_sweep25", Q4TourSweepPolicy)]
    dump(out / "cases.json", [s.to_dict() for s in cases])
    dump(out / "config.json", dict(q4=Q4Config().to_dict(), tour=dict(exact_limit=8, two_opt_pass_limit="2*n",
                                                                  starts="all first nodes and previous route", closed=False)))
    dump(out / "route_checks.json", route_checks())
    hashes = {}
    for folder, prefix in ((BASE, "base"), (ROOT, "night")):
        for path in folder.glob("*.py"):
            if path.name == "astra_guard.py":
                continue
            data, key = path.read_bytes(), f"{prefix}/{path.name}"
            hashes[key] = hashlib.sha256(data).hexdigest()
            target = out / "source" / key
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    manifest = dict(created_at=time.time(), python=sys.version, code_sha256=hashes, status="running",
                    planned_runs=12, cases_sha256=hashlib.sha256((out / "cases.json").read_bytes()).hexdigest(),
                    error_contract="frozen local model: additive <=1deg then rounding; final <=1.005deg")
    dump(out / "manifest.json", manifest)
    original_audit = q4run.audit_orientation
    def combined_audit(state, env):
        original_audit(state, env)
        audit_joint(state, env)
    # 只在本独立测试驱动额外调用审计，不改共享文件或策略输入。
    q4run.audit_orientation = combined_audit
    results = []
    try:
        for scene in cases:
            for name, cls in policies:
                check_cached()
                created = []
                def factory(config):
                    policy = cls(config)
                    created.append(policy)
                    return policy
                result = q4run.run_case(scene, name, out / "actions" / f"{scene.name}_{name}.jsonl",
                                        policy_factory=factory, state_factory=Q4JointCoverageInformationState)
                result["policy_stats"] = getattr(created[0], "stats", {})
                if name == "tour_sweep25":
                    dump(out / "routes" / f"{scene.name}.json", created[0].tour_events)
                results.append(result)
                dump(out / "results.json", results)
                compact = {k: v for k, v in result.items() if k != "absence_proofs"}
                print(json.dumps(compact, ensure_ascii=False), flush=True)
                check_cached()
        manifest["status"] = "completed"
    finally:
        q4run.audit_orientation = original_audit
        manifest.update(completed_runs=len(results), finished_at=time.time())
        dump(out / "manifest.json", manifest)
        summary = {}
        for name, _ in policies:
            rows = [r for r in results if r["policy"] == name]
            if rows:
                summary[name] = dict(runs=len(rows), successes=sum(r["success"] for r in rows),
                    sources=sum(r["source_count"] for r in rows), cleared=sum(r["cleared"] for r in rows),
                    mean_virtual_s=sum(r["virtual_time_s"] for r in rows)/len(rows),
                    worst_virtual_s=max(r["virtual_time_s"] for r in rows),
                    max_wall_s=max(r["wall_time_s"] for r in rows),
                    fallback_runs=sum(r["fallback"] for r in rows))
        dump(out / "summary.json", summary)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "runs/tour_sweep/development_76300")
    args = parser.parse_args()
    check_cached()
    if args.self_test:
        print(json.dumps(route_checks()))
    else:
        out = args.output.resolve()
        if ROOT / "runs/tour_sweep" not in out.parents:
            raise ValueError("产物须位于runs/tour_sweep子目录")
        batch(out)


if __name__ == "__main__":
    main()
