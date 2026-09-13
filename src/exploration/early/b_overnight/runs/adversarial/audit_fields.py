"""读回固定表和完整轨迹，独立核对选择、重放与最终返回误差。"""
from collections import Counter
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def audit(folder):
    cases = json.loads((folder / "cases.json").read_text(encoding="utf-8"))
    reports = []
    for item in cases:
        scene = item["scenario"]
        sources = {s["channel"]: s for s in scene["sources"]}
        case = folder / scene["name"]
        entries = json.loads((case / "field.json").read_text(encoding="utf-8"))["entries"]
        direction = [e for e in entries if e["alternatives"]]
        greater, ratios = 0, []
        for entry in direction:
            legal = [a for a in entry["alternatives"] if a.get("legal_return", True)]
            best = max(legal, key=lambda a: (a["area_m2"], a["diameter_m"], abs(a["error_deg"]), a["error_deg"]))
            assert entry["error_deg"] == best["error_deg"]
            baseline = next(a for a in entry["alternatives"] if a["error_deg"] == 0)
            assert best["area_m2"] >= baseline["area_m2"]
            greater += best["area_m2"] > baseline["area_m2"] + 1e-6
            if baseline["area_m2"] > 1e-8:
                ratios.append(best["area_m2"] / baseline["area_m2"])
        assert len({e["key"] for e in entries}) == len(entries)
        assert all(-1 <= e["error_deg"] <= 1 for e in entries)
        first = [json.loads(line) for line in (case / "generation_actions.jsonl").read_text(encoding="utf-8").splitlines()]
        second = [json.loads(line) for line in (case / "replay_actions.jsonl").read_text(encoding="utf-8").splitlines()]
        assert first == second
        errors = []
        for row in first:
            if row["response"].get("measure_result") != "direction":
                continue
            q, s = row["position"], sources[row["channel"]]["position"]
            true = math.degrees(math.atan2(s[1] - q[1], s[0] - q[0]))
            errors.append(abs((row["response"]["svd_deg"] - true + 180) % 360 - 180))
        if "strict" in folder.name:
            assert max(errors) <= 1 + 1e-12
        reports.append(dict(case=scene["name"], entries=len(entries), direction_entries=len(direction),
            error_histogram=dict(Counter(str(e["error_deg"]) for e in direction)),
            strictly_larger_area_than_zero=greater, max_area_ratio_vs_zero=max(ratios, default=None),
            full_trace_exact_match=True, returned_error_exceeds_1_count=sum(e > 1 + 1e-12 for e in errors),
            max_returned_error_deg=max(errors), max_abs_coordinate_m=max(abs(v) for row in first for v in row["position"]),
            failed_clear_steps=[dict(step=r["step"], channel=r["channel"], reason=r.get("reason")) for r in first
                                if r["kind"] == "clear" and r["response"]["clear_result"] != "success"]))
    (folder / "saved_data_audit.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    boundary = dict(entries=sum(r["entries"] for r in reports), directions=sum(r["direction_entries"] for r in reports),
                    strictly_larger_area_than_zero=sum(r["strictly_larger_area_than_zero"] for r in reports),
                    returned_error_exceeds_1_count=sum(r["returned_error_exceeds_1_count"] for r in reports),
                    max_returned_error_deg=max(r["max_returned_error_deg"] for r in reports),
                    max_area_ratio_vs_zero=max(r["max_area_ratio_vs_zero"] for r in reports),
                    max_abs_coordinate_m=max(r["max_abs_coordinate_m"] for r in reports),
                    interpretation="strict returned-angle field" if "strict" in folder.name else "rounding-expanded pressure field; not strict interface-legal")
    (folder / "error_boundary.json").write_text(json.dumps(boundary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(folder.name, json.dumps(boundary, ensure_ascii=False))
    return reports


if __name__ == "__main__":
    for name in ("fixed_field_75100", "strict_fixed_field_75100"):
        audit(ROOT / name)
