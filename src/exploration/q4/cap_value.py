"""只回放公开动作，诊断服务停点全扫触发16源上限的条件价值；不改策略。"""
import argparse
from collections import Counter
import hashlib
from itertools import combinations
import json
import math
from pathlib import Path
import random
import time

import common
from common import PROJECT, Q4State, Q4_SYMMETRIC25_ANCHORS
from belief import make_pool, reception_mass
from planner import optimize_route, route_length


def elementary_symmetric(values):
    coefficients = [1.0] + [0.0] * len(values)
    for value in values:
        for k in range(len(values), 0, -1):
            coefficients[k] += value * coefficients[k - 1]
    return coefficients


def cap_probability(masses, detection, known):
    """工作先验下的DP计算，未包含整套源至少两种类型的额外条件化。"""
    if len(masses) != len(detection) or not 0 <= known <= 16:
        raise ValueError("维数或已发现源数无效")
    if any(not math.isfinite(x) or x < 0 for x in masses):
        raise ValueError("相容质量必须非负有限")
    if any(not math.isfinite(p) or not 0 <= p <= 1 for p in detection):
        raise ValueError("接收概率必须在0至1")
    coefficients = elementary_symmetric(masses)
    kmin, kmax = max(0, 10 - known), min(len(masses), 16 - known)
    terms = {k: coefficients[k] / math.comb(20, known + k) for k in range(kmin, kmax + 1)}
    normalizer = sum(terms.values())
    if normalizer <= 0:
        raise ValueError("源数后验质量为空")
    remaining = 16 - known
    if remaining > len(masses):
        numerator, p16 = 0.0, 0.0
    else:
        visible_coefficients = elementary_symmetric([x * p for x, p in zip(masses, detection)])
        numerator = visible_coefficients[remaining] / math.comb(20, 16)
        p16 = terms.get(remaining, 0.0) / normalizer
    cap = numerator / normalizer
    return dict(p_cap=cap, p_total16=p16,
                p_all_detected_given16=cap / p16 if p16 > 0 else 0.0,
                numerator=numerator, normalizer=normalizer,
                source_count_posterior={str(known + k): value / normalizer for k, value in terms.items()})


def validate_probability_formula():
    # 独立小规模子集枚举，不复用被测系数递推。
    masses, detection, known = [0.2, 0.6, 0.08, 0.5], [0.7, 0.1, 0.9, 0.3], 12
    denominator, numerator = 0.0, 0.0
    for k in range(5):
        for subset in combinations(range(4), k):
            weight = math.prod(masses[j] for j in subset) / math.comb(20, known + k)
            denominator += weight
            if known + k == 16:
                numerator += weight * math.prod(detection[j] for j in subset)
    actual = cap_probability(masses, detection, known)
    assert math.isclose(actual["p_cap"], numerator / denominator, rel_tol=1e-12)
    assert cap_probability([1.0] * 20, [1.0] * 20, 0)["p_cap"] == 1 / 7
    assert cap_probability([0.2, 0.4], [0.0, 0.0], 15)["p_cap"] == 0
    expected = 3.2 * 0.3 / (1 + 3.2 * 0.3) * 0.6
    assert math.isclose(cap_probability([0.3], [0.6], 15)["p_cap"], expected, rel_tol=1e-12)
    return dict(passed=True, checks=4)


def public_stamp(channel, salt):
    value = json.dumps([channel.channel, channel.observations, salt], sort_keys=True).encode()
    return int.from_bytes(hashlib.sha256(value).digest()[:8], "big")


class PoolCache:
    def __init__(self, size, salt):
        self.size, self.salt = size, salt
        self.cache = {}

    def get(self, state, channel):
        stamp = public_stamp(channel, self.salt)
        key = channel.channel, stamp
        if key not in self.cache:
            try:
                pool = make_pool(state, channel, random.Random(stamp), self.size, 0.5)
            except ValueError:
                pool = make_pool(state, channel, random.Random(stamp), self.size * 4, 0.5)
            self.cache[key] = pool
        return self.cache[key]


def diagnose_state(state, cache, q=None):
    q = tuple(state.position if q is None else q)
    known = len(state.ever_seen)
    unknown = [c for c in state.channels.values() if c.status == "unknown"]
    masses, reception, details = [], [], []
    for c in unknown:
        pool = cache.get(state, c)
        denominator = sum(pool["weights"])
        p = sum(w * reception_mass(x, slices, q)
                for x, slices, w in zip(pool["points"], pool["slices"], pool["weights"]) if w > 0) / denominator
        # 历史阴性在同一点固定；去掉浮点角区间端点引入的极小残余概率。
        if q in c.measured:
            p = 0.0
        masses.append(pool["presence_mass"])
        reception.append(p)
        details.append(dict(channel=c.channel, presence_mass=pool["presence_mass"], reception_probability=p,
                            ess=pool["ess"], previously_measured_here=q in c.measured))
    result = cap_probability(masses, reception, known)
    past = set.intersection(*[{tuple(q) for q, r, _ in c.observations if r == "no_signal"}
                             for c in unknown]) if unknown else set()
    remaining = [q for q in Q4_SYMMETRIC25_ANCHORS if q not in past]
    route = optimize_route(q, [dict(position=anchor) for anchor in remaining])
    travel = route_length(q, route)
    u, eligible = len(unknown), sum(not row["previously_measured_here"] for row in details)
    proxy = travel / 5 + 6 * u * len(remaining)
    benefit = result["p_cap"] * proxy
    return dict(**result, position=q, known=known, unknown_count=u, eligible_unknown_count=eligible,
                unknown_details=details, remaining_anchor_count=len(remaining), remaining_route_m=travel,
                remaining_coverage_proxy_s=proxy, full_scan_cost_s=6 * u,
                incremental_scan_cost_s=6 * eligible, expected_coverage_saving_s=benefit,
                net_value_s=benefit - 6 * u, incremental_net_value_s=benefit - 6 * eligible)


class CapValueEstimator:
    """K=15停点增扫代理；工作先验概率不产生任何不存在/已清除事实。

    evaluate(state, q) 不移动state，q可为下一测量站或成功清除位置。
    返回prob/fee/scanproxy/net，其中三个费用单位为秒；fee只计q尚未
    测过的未知频道。scanproxy是独立完成剩余25点发现的代理，不是
    真正可取消的边际费用，不能据此承诺整局改善。失败返回None。
    实例可以跨行动复用；缓存仅依赖频道的公开观测记录。
    """

    def __init__(self, pool_size=512, salt=2026091316):
        if pool_size < 1:
            raise ValueError("pool_size必须为正")
        self.cache = PoolCache(pool_size, salt)

    def evaluate(self, state, q):
        if len(state.ever_seen) != 15:
            return None
        q = tuple(q)
        if len(q) != 2 or not all(math.isfinite(x) for x in q):
            raise ValueError("q必须是有限二维坐标")
        unknown = [c for c in state.channels.values() if c.status == "unknown"]
        if not unknown or all(q in c.measured for c in unknown):
            return None
        try:
            row = diagnose_state(state, self.cache, q)
        except ValueError:
            # 采样耗尽或保守区域退化不等于频道不存在。
            return None
        return dict(row, prob=row["p_cap"], fee=row["incremental_scan_cost_s"],
                    scanproxy=row["remaining_coverage_proxy_s"], net=row["incremental_net_value_s"],
                    min_ess=min(d["ess"] for d in row["unknown_details"]))


def service_checkpoint(action, before_status):
    if action["kind"] == "clear":
        return True
    return (action.get("reason") not in ("q4_initial_scan", "q4_joint_discovery_scan")
            and (before_status == "found" or action["response"]["measure_result"] in ("direction", "near")))


def replay_case(case_root, source_count, cache, max_points=40):
    trace = case_root / "shared" / "actions.jsonl"
    actions = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    state, records, seen = Q4State(), [], set()
    for index, action in enumerate(actions):
        before_status = state.channels[action["channel"]].status
        state.update(action, action["response"])
        known = len(state.ever_seen)
        if not 12 <= known < 16 or not service_checkpoint(action, before_status):
            continue
        unknown = [c for c in state.channels.values() if c.status == "unknown"]
        eligible = {c.channel for c in unknown if tuple(state.position) not in c.measured}
        key = (tuple(state.position), known, tuple((c.channel, len(c.observations)) for c in unknown))
        if not eligible or key in seen or len(records) >= max_points:
            continue
        seen.add(key)
        row = dict(case=case_root.name, source_count_label=source_count,
                   after_step=action["step"], after_reason=action.get("reason"), position=state.position,
                   virtual_time_s=state.virtual_time_s, trace_sha256=hashlib.sha256(trace.read_bytes()).hexdigest())
        try:
            row.update(diagnose_state(state, cache))
        except ValueError as exc:
            row.update(error=str(exc), known=known)
        later = []
        for future in actions[index + 1:]:
            if tuple(future["position"]) != tuple(state.position):
                break
            later.append(future)
        scanned = {a["channel"] for a in later if a["kind"] == "measure" and a["channel"] in eligible}
        newly_found = {a["channel"] for a in later if a["kind"] == "measure" and a["channel"] in eligible
                       and a["response"]["measure_result"] in ("direction", "near")}
        # 下列是事后轨迹标签，绝不传给后验或决策公式。
        row.update(actual_later_scans_here=sorted(scanned), already_planned_full_scan=scanned == eligible,
                   actually_hits_cap_before_leaving=known + len(newly_found) >= 16)
        records.append(row)
    return records


def run(input_dir, output, pool_size=512, salt=2026091316):
    output.mkdir(parents=True, exist_ok=False)
    began = time.perf_counter()
    rows = [r for r in json.loads((input_dir / "results.json").read_text(encoding="utf-8")) if r["policy"] == "shared"]
    selected = [r for r in rows if r["source_count"] == 16]
    selected += [next(r for r in rows if r["source_count"] == count) for count in (12, 14, 15)]
    cache, records = PoolCache(pool_size, salt), []

    def dump(name, value):
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    dump("validation.json", validate_probability_formula())
    for case in selected:
        result = replay_case(input_dir / "cases" / case["case"], case["source_count"], cache)
        records.extend(result)
        dump("records.json", records)
        good = [r for r in result if "error" not in r]
        print(json.dumps(dict(case=case["case"], source_count=case["source_count"], points=len(result),
                             errors=len(result) - len(good), positive=sum(r["net_value_s"] > 0 for r in good),
                             missed_positive=sum(r["net_value_s"] > 0 and not r["already_planned_full_scan"] for r in good),
                             best_net_s=max((r["net_value_s"] for r in good), default=None)), ensure_ascii=False), flush=True)
    good = [r for r in records if "error" not in r]
    positive = [r for r in good if r["net_value_s"] > 0]
    missed = [r for r in positive if not r["already_planned_full_scan"]]
    summary = dict(points=len(records), errors=len(records) - len(good), positive=len(positive),
                   missed_positive=len(missed), selected_cases=[r["case"] for r in selected],
                   counts_by_known=dict(Counter(r["known"] for r in good)),
                   highest_missed=sorted(missed, key=lambda r: r["net_value_s"], reverse=True)[:10],
                   wall_s=time.perf_counter() - began)
    dump("summary.json", summary)
    files = [Path(__file__), Path(__file__).with_name("belief.py"), Path(__file__).with_name("common.py"),
             Path(__file__).with_name("planner.py"), PROJECT / "experiments/b_adaptive_q3/state.py",
             PROJECT / "experiments/b_overnight/q4_coverage.py"]
    dump("manifest.json", dict(pool_size=pool_size, salt=salt,
         assumption="uniform_position_radius_orientation_independent_type_prior_no_global_mixed_condition",
         source_counts_used_only_for_retrospective_case_selection=True,
         hashes={p.relative_to(PROJECT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}))
    (output / "source_snapshot.py").write_bytes(Path(__file__).read_bytes())
    print(json.dumps(dict(event="complete", **{k: summary[k] for k in ("points", "errors", "positive", "missed_positive", "wall_s")})), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=PROJECT / "outputs/experiments/q4/develop02")
    parser.add_argument("--output", type=Path, default=PROJECT / "outputs/experiments/q4/cap_diagnostic")
    parser.add_argument("--pool-size", type=int, default=512)
    parser.add_argument("--salt", type=int, default=2026091316)
    args = parser.parse_args()
    run(args.input, args.output, args.pool_size, args.salt)
