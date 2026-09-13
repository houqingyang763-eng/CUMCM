"""合并实际UI源数和公开成功回执；不覆盖原始运行记录，不连接网络。"""
import hashlib
import json
import math
from pathlib import Path

from astra_guard import check_cached

ROOT = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def verify(directory):
    summary = read(directory / "summary.json")
    ui = read(directory / "official_result_ui.json")
    manifest = read(directory / "manifest.json")
    rows = [json.loads(line) for line in (directory / "actions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert summary["scope"] == "official_practice" and ui["mode"] == "practice"
    assert summary["error_type"] is None and summary["exited"] and summary["complete_by_evidence"]
    assert manifest["sources_unchanged_during_session"]
    assert manifest["official_ui_verification"]["case_code"] == ui["case_code"]
    assert summary["problem"] == ui["problem"] and ui["status"] == "测试已结束"
    completed = [r["action"]["channel"] for r in rows
                 if r["action"]["kind"] == "clear" and r["response"]["clear_result"] == "success"]
    assert len(completed) == len(set(completed)) == summary["cleared_count"] == ui["source_count"]
    current, channel, total, max_error = (0, 0), 1, 0., 0.
    for row in rows:
        action, response = row["action"], row["response"]
        assert response["accepted"]
        q, j = action["position"], action["channel"]
        total += math.hypot(q[0] - current[0], q[1] - current[1]) / 5
        if action["kind"] == "measure":
            total += 5 + int(channel != j)
            channel = j
        else:
            total += 5 if response["clear_result"] == "success" else 3
        current = q
        error = abs(total - response["virtual_time_s"])
        max_error = max(error, max_error)
        assert error < .001
    assert abs(total - summary["virtual_time_s"]) < .001
    measures = [r for r in rows if r["action"]["kind"] == "measure"]
    record = {k: summary[k] for k in ("problem", "policy", "state_class", "virtual_time_s", "wall_time_s",
              "actions", "requests", "retry_count", "move_s", "measure_s", "switch_s", "clear_s")}
    record.update(case_code=ui["case_code"], scope="official_practice", all_cleared_verified=True,
                  official_source_count=ui["source_count"], omni_count=ui["omni_count"], directional_count=ui["directional_count"],
                  successful_clear_channels=sorted(completed), measure_count=len(measures),
                  scan_position_count=len({tuple(r["action"]["position"]) for r in measures}),
                  failed_clears=sum(r["action"]["kind"] == "clear" and r["response"]["clear_result"] != "success" for r in rows),
                  max_ledger_error_s=max_error, mean_per_source_s=summary["virtual_time_s"] / ui["source_count"],
                  source_hashes=manifest["source_sha256"], ui_observed_at_utc=ui["observed_at_utc"],
                  private_evidence_directory=directory.relative_to(ROOT).as_posix(),
                  evidence_hashes={f: hashlib.sha256((directory / f).read_bytes()).hexdigest()
                                   for f in ("summary.json", "actions.jsonl", "manifest.json", "official_result_ui.json", "official_result_ui.txt")})
    return record


if __name__ == "__main__":
    check_cached()
    cases = ["q3_completion_20260911", "q4_joint25_20260911", "q3_sweep_20260911"]
    records = [verify(ROOT / "practice" / "local_runs" / name) for name in cases]
    out = ROOT / "runs" / "official_practice"
    out.mkdir(exist_ok=True)
    result = dict(cases=records, interpretation="三次不同案例的单局真实官方演练。源数由实际结束UI核对，全清由不同频道成功回执与该源数共同验证；不是正式成绩，也不能作跨策略配对比较。")
    (out / "verified_results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps([{k: v for k, v in r.items() if k not in ("source_hashes", "evidence_hashes")} for r in records], ensure_ascii=False))
