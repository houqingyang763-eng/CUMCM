"""只读核对两次既有第三问演练；独立检查历史无信号覆盖证据。

不调用模拟器，不导入策略，不读取或执行资源保护程序。
覆盖判断使用 Fraction 精确计算已记录坐标，避免依赖原策略的几何实现。
"""
from collections import Counter
from fractions import Fraction as F
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
NIGHT = ROOT / "experiments/b_overnight"
OUT = Path(__file__).with_name("recorded_practice_audit.json")


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def exact_cover(measurements):
    """用有理数四叉树证明 D 完全被历史可靠接收圆覆盖，或返回未覆盖见证。

    只有整个闭矩形在某个 1000 米圆严格内部，才登记为已覆盖。
    只有整个矩形在 1800 米目标圆域外，才跳过。
    到达细分上限而不能判断时返回 unknown，绝不据此宣称覆盖。
    """
    circles = [(i, F(str(q[0])), F(str(q[1]))) for i, q in measurements]
    stack = [(F(-1800), F(-1800), F(1800), F(1800), 0)]
    leaves, checked = [], 0
    while stack:
        x0, y0, x1, y1, depth = stack.pop()
        checked += 1
        dx = F(0) if x0 <= 0 <= x1 else min(abs(x0), abs(x1))
        dy = F(0) if y0 <= 0 <= y1 else min(abs(y0), abs(y1))
        if dx * dx + dy * dy > 1800**2:
            continue
        cover = next((i for i, x, y in circles
                      if max((x0-x)**2, (x1-x)**2)
                      + max((y0-y)**2, (y1-y)**2) < 1000**2), None)
        if cover is not None:
            leaves.append({"box": [str(v) for v in (x0, y0, x1, y1)],
                           "covering_measurement_step": cover})
            continue
        xm, ym = (x0+x1)/2, (y0+y1)/2
        if xm*xm + ym*ym <= 1800**2 and all(
                (xm-x)**2 + (ym-y)**2 > 1000**2 for _, x, y in circles):
            return {"status": "uncovered_witness", "point": [str(xm), str(ym)],
                    "checked_boxes": checked}
        if depth >= 13 or checked >= 200000:
            return {"status": "unknown", "checked_boxes": checked}
        stack.extend([(x0, y0, xm, ym, depth+1), (xm, y0, x1, ym, depth+1),
                      (x0, ym, xm, y1, depth+1), (xm, ym, x1, y1, depth+1)])
    return {"status": "covered", "checked_boxes": checked, "cover_leaves": leaves}


def audit_case(case):
    directory = NIGHT / case["private_evidence_directory"]
    raw = (directory / "actions.jsonl").read_bytes()
    expected = case["evidence_hashes"]["actions.jsonl"]
    assert hashlib.sha256(raw).hexdigest() == expected
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
    p, ch, accumulated = (0.0, 0.0), 1, 0.0
    costs = Counter()
    largest_error = 0.0
    cleared, seen, reasons, failures = set(), set(), Counter(), []
    last_clear = None
    for step, row in enumerate(rows, 1):
        a, response = row["action"], row["response"]
        assert response["accepted"]
        delta = {"move_s": math.dist(p, a["position"])/5}
        if a["kind"] == "measure":
            delta.update(measure_s=5, switch_s=int(ch != a["channel"]))
            ch = a["channel"]
            if response["measure_result"] in ("direction", "near"):
                seen.add(ch)
        else:
            success = response["clear_result"] == "success"
            delta["clear_s"] = 5 if success else 3
            if success:
                cleared.add(a["channel"])
                last_clear = {"step": step, "time_s": response["virtual_time_s"]}
            else:
                failures.append({"step": step, "channel": a["channel"],
                                 "reason": a["reason"]})
        costs.update(delta)
        accumulated += sum(delta.values())
        largest_error = max(largest_error, abs(accumulated-response["virtual_time_s"]))
        reasons[a["reason"]] += 1
        p = a["position"]
    assert cleared == set(case["successful_clear_channels"])
    assert len(cleared) == case["official_source_count"]
    assert largest_error < 1e-4  # 原始反馈小数舍入的累计容差，不用于几何证书。
    total = rows[-1]["response"]["virtual_time_s"]
    return {
        "policy": case["policy"], "problem": case["problem"],
        "source_count": len(cleared), "actions": len(rows),
        "total_time_s": total, "recorded_wall_time_s": case["wall_time_s"],
        "costs": dict(costs), "maximum_cumulative_ledger_error_s": largest_error,
        "reasons": dict(reasons), "failed_clears": failures,
        "last_successful_clear": last_clear,
        "time_after_last_clear_s": total-last_clear["time_s"],
        "actions_sha256_verified": expected,
    }, rows


def main():
    cases = [case for case in load_json(
        NIGHT / "runs/official_practice/verified_results.json")["cases"]
        if case["problem"] == 3]
    result = {"scope": "existing_q3_official_practice_only", "cases": [],
              "q3_completion_exact_coverage": {}}
    completion_rows = None
    for case in cases:
        stats, rows = audit_case(case)
        result["cases"].append(stats)
        if case["policy"] == "CompletionCostPolicy":
            completion_rows = rows
    assert completion_rows is not None
    unknown_channels = (2, 5, 7, 10, 14, 15, 19, 20)
    for stop in (130, 178):
        measurements = {j: [] for j in unknown_channels}
        for step, row in enumerate(completion_rows[:stop], 1):
            a, response = row["action"], row["response"]
            if (a["channel"] in measurements and a["kind"] == "measure"
                    and response["measure_result"] == "no_signal"):
                measurements[a["channel"]].append((step, a["position"]))
        checks = {j: exact_cover(v) for j, v in measurements.items()}
        expected = "covered" if stop == 178 else "uncovered_witness"
        assert all(v["status"] == expected for v in checks.values())
        result["q3_completion_exact_coverage"][stop] = checks
    result["q3_completion_unnecessary_final_visit"] = {
        "evidence_complete_by_step": 178, "remaining_steps": [179, 186],
        "remaining_time_s": completion_rows[-1]["response"]["virtual_time_s"]
        - completion_rows[177]["response"]["virtual_time_s"],
        "meaning": "第178步历史反馈已足以覆盖排查；仅指其后的287秒，不指整个收尾阶段。",
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"output": str(OUT), "cases": len(cases),
                      "verified_actions": sum(c["actions"] for c in result["cases"]),
                      "coverage_arithmetic": "exact rational",
                      "q3_unnecessary_final_visit_s": result[
                          "q3_completion_unnecessary_final_visit"]["remaining_time_s"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
