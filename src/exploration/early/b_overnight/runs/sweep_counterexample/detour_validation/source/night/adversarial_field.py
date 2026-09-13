"""固定误差场的有限存在性挑战：生成后严格重放，不改共享环境或驱动。"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent / "b_adaptive_q3"
sys.path.insert(0, str(BASE))
import geometry as g
from simulation import LocalEnvironment, Scenario, Source, generate
from state import InformationState, audit_state
from task_cost import CompletionCostPolicy, CompletionCostConfig
from q4 import Q4Config
from q4run import generate_q4, audit_orientation
from q4_anchor_design import Q4Symmetric25Policy
from q4_joint_state import Q4JointCoverageInformationState
from test_q4_joint_state import audit_joint
from astra_guard import check_cached

ERRORS = (-1.0, -0.5, 0.0, 0.5, 1.0)


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def location_key(q, channel):
    # 二进制浮点的精确坐标作键，正负零按同一个物理地点处理。
    return f"{channel}:" + ":".join(float(v if v else 0).hex() for v in q)


def diameter(poly):
    return max((g.distance(a, b) for a in poly for b in poly), default=0.0)


def direction_update(poly, first, q, bearing):
    if first is None:
        e = g.unit(bearing)
        poly = g.rectangle(poly, q, e, (-e[1], e[0]), 0, 1500,
                           -g.STRIP_HALF_WIDTH, g.STRIP_HALF_WIDTH)
    return g.intersect_disk_outer(g.wedge(poly, q, bearing), q, 1500)


class FixedHardFieldEnvironment(LocalEnvironment):
    """真值只能在环境内访问；策略不持有本实例或误差表。

    半径、方向、near、清除与全部计费调用冻结 LocalEnvironment。
    基础场 zero 仅作物理载体，direction 返回值随后用这里的固定场替换。
    replay_entries 给出时禁止临时选值，发现未记录的检测点立即报错。
    """
    def __init__(self, scene, replay_entries=None):
        if scene.noise != "zero":
            raise ValueError("基础环境须用 zero；实际误差由固定表替换")
        super().__init__(scene)
        self.replay = replay_entries is not None
        self.entries = {} if replay_entries is None else {e["key"]: e for e in replay_entries}
        if replay_entries is not None and len(self.entries) != len(replay_entries):
            raise ValueError("误差表地点重复")
        self.polygons = {j: g.outer_disk((0, 0), 1800) for j in range(1, 21)}
        self.first = {j: None for j in range(1, 21)}
        self.reused = 0
        self.lookup_count = 0
        self.used_keys = set()
        self.selection_s = 0.0

    def act(self, action):
        response = super().act(action)
        if action["kind"] != "measure":
            return response
        q, j = tuple(action["position"]), action["channel"]
        key = location_key(q, j)
        self.lookup_count += 1
        result = response["measure_result"]
        bearing = None
        if result == "direction":
            s = self.sources[j].position
            bearing = math.degrees(math.atan2(s[1] - q[1], s[0] - q[0]))
        if key not in self.entries:
            if self.replay:
                raise AssertionError(f"严格重放出现新检测点 {key}")
            alternatives = []
            stamp = time.perf_counter()
            if result == "direction":
                for error in ERRORS:
                    observed = round((bearing + error) % 360, 2) % 360
                    poly = direction_update(self.polygons[j], self.first[j], q, observed)
                    assert g.contains(poly, self.sources[j].position), "合法候选方向竟排除真值"
                    returned_error = abs(g.angle_delta(observed, bearing))
                    alternatives.append(dict(error_deg=error, observed_deg=observed,
                                             returned_error_deg=returned_error,
                                             legal_return=returned_error <= 1 + 1e-12,
                                             area_m2=g.area(poly), diameter_m=diameter(poly)))
                # 同时满足加性场误差和最终两位小数返回误差均不超过1度。
                # 附件2直接约束返回值，不能把舍入扩展场冒充严格合法场。
                best = max((a for a in alternatives if a["legal_return"]),
                           key=lambda a: (a["area_m2"], a["diameter_m"],
                                                       abs(a["error_deg"]), a["error_deg"]))
                error = best["error_deg"]
            else:
                error = 0.0
            self.selection_s += time.perf_counter() - stamp
            self.entries[key] = dict(key=key, position=q, channel=j, error_deg=error,
                                     first_result=result, alternatives=alternatives)
        else:
            self.reused += int(key in self.used_keys)
        self.used_keys.add(key)
        error = self.entries[key]["error_deg"]
        assert error in ERRORS and -1 <= error <= 1
        if result == "direction":
            response["svd_deg"] = round((bearing + error) % 360, 2) % 360
            assert abs(g.angle_delta(response["svd_deg"], bearing)) <= 1 + 1e-12
            self.polygons[j] = direction_update(self.polygons[j], self.first[j], q,
                                                 response["svd_deg"])
            if self.first[j] is None:
                self.first[j] = (q, response["svd_deg"])
        elif result == "near":
            self.polygons[j] = g.intersect_disk_outer(self.polygons[j], q, 5)
        return response


def make_cases():
    q3 = [generate(75100 + i, layout, "zero")
          for i, layout in enumerate(("uniform", "edge", "cluster", "line"))]
    q4 = [generate_q4(75200 + i, layout, "zero", direction)
          for i, (layout, direction) in enumerate((("uniform", "random"), ("edge", "outward"),
                                                   ("edge", "tangent"), ("line", "aligned")))]
    return [("q3", s) for s in q3] + [("q4", s) for s in q4]


def physical_trace(rows):
    return [dict(kind=r["kind"], position=r["position"], channel=r["channel"], response=r["response"])
            for r in rows]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


def run_case(scene, problem, out, replay_entries=None, policy_factory=None,
             environment_factory=FixedHardFieldEnvironment, policy_name=None, mode_override=None):
    check_cached()
    mode = mode_override or ("replay" if replay_entries is not None else "generation")
    policy = (policy_factory or (CompletionCostPolicy if problem == "q3" else Q4Symmetric25Policy))()
    state = InformationState() if problem == "q3" else Q4JointCoverageInformationState()
    state.action_history = []
    env = environment_factory(scene, replay_entries)
    started = time.perf_counter()
    planning = checking = 0.0
    rows, error = [], None
    ledger = dict(move_s=0.0, switch_s=0.0, measure_s=0.0, clear_s=0.0)
    previous, channel = (0, 0), 1
    fallback_start = None
    try:
        while not state.complete:
            if len(rows) % 10 == 0:
                check_cached()
            if len(rows) >= (3000 if problem == "q3" else 5000) or time.perf_counter() - started > 1200:
                raise TimeoutError("整局动作或现实耗时上限")
            stamp = time.perf_counter()
            action = policy.choose(state)
            planning += time.perf_counter() - stamp
            assert action is not None and math.hypot(*action["position"]) <= 5000 + 1e-6
            if policy.fallback_started and fallback_start is None:
                fallback_start = dict(step=len(rows) + 1, virtual_time_s=env.virtual_time_s)
            response = env.act(action)
            row = dict(step=len(rows) + 1, **action, response=response)
            rows.append(row)
            q, j = action["position"], action["channel"]
            ledger["move_s"] += math.hypot(q[0] - previous[0], q[1] - previous[1]) / 5
            if action["kind"] == "measure":
                ledger["switch_s"] += int(j != channel)
                ledger["measure_s"] += 5
                channel = j
            else:
                ledger["clear_s"] += 5 if response["clear_result"] == "success" else 3
            previous = q
            assert abs(sum(ledger.values()) - env.virtual_time_s) < 1e-5
            stamp = time.perf_counter()
            state.update(action, response)
            state.action_history.append(row)
            audit_state(state, env)
            if problem == "q4":
                audit_orientation(state, env)
                audit_joint(state, env)
            checking += time.perf_counter() - stamp
            assert env.virtual_time_s <= 100 * 3600
    except Exception:
        error = traceback.format_exc()
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{mode}_actions.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    if mode == "generation":
        dump(out / "field.json", dict(unlisted_locations_error_deg=0.0,
                                      key_rule="channel and exact float.hex x/y; signed zero normalized",
                                      entries=list(env.entries.values())))
    measures = [r for r in rows if r["kind"] == "measure"]
    result = dict(case=scene.name, problem=problem, mode=mode, layout=scene.layout, seed=scene.seed,
                  policy=policy_name or ("completion" if problem == "q3" else "symmetric25_joint_coverage"),
                  source_count=len(scene.sources), cleared=len(env.cleared),
                  success=error is None and state.complete, error=error,
                  virtual_time_s=env.virtual_time_s, wall_time_s=time.perf_counter() - started,
                  planning_s=planning, checking_s=checking, environment_selection_s=env.selection_s,
                  actions=len(rows), measure_count=len(measures),
                  no_signal_count=sum(r["response"]["measure_result"] == "no_signal" for r in measures),
                  failed_clears=sum(r["kind"] == "clear" and r["response"]["clear_result"] != "success" for r in rows),
                  fallback=policy.fallback_started, fallback_start=fallback_start,
                  field_entries=len(env.entries), field_lookups=env.lookup_count,
                  field_repeated_lookups=env.reused, used_field_entries=len(env.used_keys),
                  physical_trace_sha256=digest(physical_trace(rows)),
                  joint_stats=state.joint_statistics() if problem == "q4" else None, **ledger)
    dump(out / f"{mode}_result.json", result)
    return result, rows


def self_test():
    # 小环境仅核对误差场注入；整局另外强制10—16源。
    scene = Scenario("self_test", 1, "single", "zero", (Source(1, (800, 250), 1000),))
    env = FixedHardFieldEnvironment(scene)
    actions = [dict(kind="measure", position=(0.0, 0.0), channel=1),
               dict(kind="measure", position=(100, -200), channel=1),
               dict(kind="measure", position=(-0.0, 0), channel=1),
               dict(kind="measure", position=(1800, 250), channel=1),
               dict(kind="measure", position=(800, 250), channel=1),
               dict(kind="measure", position=(0, 0), channel=20),
               dict(kind="clear", position=(800, 250), channel=1)]
    generated = [env.act(action) for action in actions]
    replay = FixedHardFieldEnvironment(scene, list(env.entries.values()))
    replayed = [replay.act(action) for action in actions]
    assert generated == replayed
    assert generated[0]["svd_deg"] == generated[2]["svd_deg"] and env.reused == 1
    assert generated[3]["measure_result"] == "direction", "1000米含边界"
    assert generated[4]["measure_result"] == "near"
    assert generated[5]["measure_result"] == "no_signal"
    assert generated[6]["clear_result"] == "success"
    for entry in env.entries.values():
        if entry["alternatives"]:
            best = max((a for a in entry["alternatives"] if a["legal_return"]),
                       key=lambda a: (a["area_m2"], a["diameter_m"],
                                                           abs(a["error_deg"]), a["error_deg"]))
            assert entry["error_deg"] == best["error_deg"]
    try:
        replay.act(dict(kind="measure", position=(99, 99), channel=1))
    except AssertionError as exc:
        assert "新检测点" in str(exc)
    else:
        raise AssertionError("严格重放未拒绝新地点")
    return dict(passed=True, checks=["固定地点含正负零", "面积/直径最大候选", "同序列反馈逐项一致",
                                     "1000米边界", "near/阴性/清除不改变", "新地点拒绝"])


def summarize(results, comparisons):
    groups = {}
    for problem in ("q3", "q4"):
        rows = [r for r in results if r["problem"] == problem and r["mode"] == "generation"]
        if not rows:
            continue
        worst = max(rows, key=lambda r: r["virtual_time_s"])
        groups[problem] = dict(runs=len(rows), completed=sum(r["success"] for r in rows),
                               cleared=sum(r["cleared"] for r in rows), sources=sum(r["source_count"] for r in rows),
                               mean_virtual_s=sum(r["virtual_time_s"] for r in rows) / len(rows),
                               worst_case=worst["case"], worst_virtual_s=worst["virtual_time_s"],
                               failed_clears=sum(r["failed_clears"] for r in rows),
                               fallback_runs=sum(r["fallback"] for r in rows),
                               max_wall_s=max(r["wall_time_s"] for r in rows))
    return dict(groups=groups, strict_replays=len(comparisons),
                all_physical_replays_match=all(c["physical_match"] for c in comparisons),
                failures=[r for r in results if not r["success"]],
                evidence_scope="按查询轨迹生成再冻结的存在性困难场；不是普通误差分布或公平速度排名")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "runs/adversarial/strict_fixed_field_75100")
    args = parser.parse_args()
    check_cached()
    checks = self_test()
    if args.self_test:
        print(json.dumps(checks, ensure_ascii=False))
        return
    out = args.output.resolve()
    if ROOT / "runs" / "adversarial" not in out.parents:
        raise ValueError("产物须在 runs/adversarial 子目录")
    out.mkdir(parents=True, exist_ok=False)
    cases = make_cases()
    for problem, scene in cases:
        assert 10 <= len(scene.sources) <= 16
        assert all(g.distance(s.position, (0, 0)) <= 1800 and 1000 <= s.radius <= 1500 for s in scene.sources)
        assert len({s.channel for s in scene.sources}) == len(scene.sources)
    dump(out / "cases.json", [dict(problem=p, scenario=s.to_dict()) for p, s in cases])
    dump(out / "self_test.json", checks)
    dump(out / "configs.json", dict(q3=CompletionCostConfig().to_dict(), q4=Q4Config().to_dict()))
    versions = {}
    for folder, prefix in ((BASE, "base"), (ROOT, "night")):
        for path in folder.glob("*.py"):
            if path.name == "astra_guard.py":
                continue
            data = path.read_bytes()
            key = f"{prefix}/{path.name}"
            versions[key] = hashlib.sha256(data).hexdigest()
            target = out / "source" / key
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    manifest = dict(created_at=time.time(), python=sys.version, code_sha256=versions,
                    cases_sha256=hashlib.sha256((out / "cases.json").read_bytes()).hexdigest(),
                    error_contract="additive error in {-1,-.5,0,.5,1}; rounded return error <=1deg",
                    planned_cases=8, planned_runs=16, status="running")
    dump(out / "manifest.json", manifest)
    results, comparisons = [], []
    try:
        for problem, scene in cases:
            check_cached()
            folder = out / scene.name
            generated, first = run_case(scene, problem, folder)
            results.append(generated)
            dump(out / "results.json", results)
            print(json.dumps(generated, ensure_ascii=False), flush=True)
            check_cached()
            field = json.loads((folder / "field.json").read_text(encoding="utf-8"))
            replayed, second = run_case(scene, problem, folder, field["entries"])
            results.append(replayed)
            a, b = physical_trace(first), physical_trace(second)
            mismatch = next((i + 1 for i, (x, y) in enumerate(zip(a, b)) if x != y), None)
            comparison = dict(case=scene.name, physical_match=a == b,
                              full_trace_match=first == second, generation_actions=len(a), replay_actions=len(b),
                              first_mismatch_step=mismatch, generation_sha256=digest(a), replay_sha256=digest(b),
                              field_sha256=hashlib.sha256((folder / "field.json").read_bytes()).hexdigest(),
                              success_matches=generated["success"] == replayed["success"])
            comparisons.append(comparison)
            dump(folder / "replay_comparison.json", comparison)
            dump(out / "replay_comparisons.json", comparisons)
            dump(out / "results.json", results)
            dump(out / "summary.json", summarize(results, comparisons))
            print(json.dumps(comparison, ensure_ascii=False), flush=True)
            check_cached()
        manifest["status"] = "completed"
    except Exception:
        manifest.update(status="interrupted", error=traceback.format_exc())
        raise
    finally:
        manifest.update(finished_at=time.time(), completed_runs=len(results))
        dump(out / "manifest.json", manifest)
        dump(out / "summary.json", summarize(results, comparisons))


if __name__ == "__main__":
    main()
