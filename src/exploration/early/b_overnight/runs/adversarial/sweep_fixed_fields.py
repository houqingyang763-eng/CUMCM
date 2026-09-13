"""将Sweep放入已冻结合法场；未知地点沿既定默认值0，不为Sweep再选误差。"""
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from adversarial_field import FixedHardFieldEnvironment, location_key, run_case, dump
from simulation import Scenario
from sweep_policy import Q3SweepPolicy
from astra_guard import check_cached


class FrozenTableEnvironment(FixedHardFieldEnvironment):
    def act(self, action):
        if action["kind"] == "measure":
            key = location_key(action["position"], action["channel"])
            if key not in self.entries:
                # 原始完整场已规定未列地点为0；这里只缓存查询，不做适应性选择。
                self.entries[key] = dict(key=key, position=action["position"], channel=action["channel"],
                                         error_deg=0.0, first_result="fixed_default", alternatives=[])
        return super().act(action)


def main():
    check_cached()
    source = ROOT / "runs/adversarial/strict_fixed_field_75100"
    out = ROOT / "runs/adversarial/sweep_on_strict_fixed_field_75100"
    out.mkdir(parents=True, exist_ok=False)
    cases = [r for r in json.loads((source / "cases.json").read_text(encoding="utf-8")) if r["problem"] == "q3"]
    original = {r["case"]: r for r in json.loads((source / "results.json").read_text(encoding="utf-8"))
                if r["problem"] == "q3" and r["mode"] == "generation"}
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in [ROOT / "adversarial_field.py", ROOT / "sweep_policy.py", Path(__file__)]}
    for relative in hashes:
        target = out / "source" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    manifest = dict(status="running", created_at=time.time(), source_fields=str(source.relative_to(ROOT)),
                    purpose="4局固定表跨策略检查；未列地点按原场定义取0；不是为Sweep定制的困难场",
                    code_sha256=hashes, config=Q3SweepPolicy().config.to_dict())
    dump(out / "manifest.json", manifest)
    results, paired = [], []
    try:
        for item in cases:
            check_cached()
            scene = Scenario.from_dict(item["scenario"])
            field_path = source / scene.name / "field.json"
            field = json.loads(field_path.read_text(encoding="utf-8"))
            assert field["unlisted_locations_error_deg"] == 0
            keys = {e["key"] for e in field["entries"]}
            result, rows = run_case(scene, "q3", out / scene.name, field["entries"],
                                    policy_factory=Q3SweepPolicy, environment_factory=FrozenTableEnvironment,
                                    policy_name="sweep_on_fixed_completion_field", mode_override="fixed_sweep")
            result["default_zero_measurements"] = sum(r["kind"] == "measure" and
                location_key(r["position"], r["channel"]) not in keys for r in rows)
            result["source_field_sha256"] = hashlib.sha256(field_path.read_bytes()).hexdigest()
            results.append(result)
            base = original[scene.name]
            paired.append(dict(case=scene.name, completion_s=base["virtual_time_s"], sweep_s=result["virtual_time_s"],
                               delta_s=result["virtual_time_s"]-base["virtual_time_s"], success=result["success"],
                               default_zero_measurements=result["default_zero_measurements"]))
            dump(out / "results.json", results)
            dump(out / "paired.json", paired)
            print(json.dumps(result, ensure_ascii=False), flush=True)
            check_cached()
        manifest["status"] = "completed"
    finally:
        manifest.update(completed_runs=len(results), finished_at=time.time())
        dump(out / "manifest.json", manifest)
        if results:
            dump(out / "summary.json", dict(runs=len(results), success=sum(r["success"] for r in results),
                 cleared=sum(r["cleared"] for r in results), sources=sum(r["source_count"] for r in results),
                 mean_sweep_s=sum(r["virtual_time_s"] for r in results)/len(results),
                 mean_completion_s=sum(r["completion_s"] for r in paired)/len(paired),
                 faster=sum(r["delta_s"]<0 for r in paired), slower=sum(r["delta_s"]>0 for r in paired),
                 tied=sum(r["delta_s"]==0 for r in paired),
                 evidence_scope="固定合法场跨策略检查，非为Sweep定制；不能作为无偏公平速度排名"))


if __name__ == "__main__":
    main()
