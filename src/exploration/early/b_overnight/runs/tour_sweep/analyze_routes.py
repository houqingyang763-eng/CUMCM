"""只读汇总完整配对与发现路线；真值仅用于检查本地返回误差口径。"""
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "development_76300"
results = json.loads((ROOT / "results.json").read_text(encoding="utf-8"))
cases = {s["name"]: s for s in json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))}
paired, route_audit, error_audit = [], [], []
for case in sorted(cases):
    group = {r["policy"]: r for r in results if r["case"] == case}
    base, tour = group["sweep25"], group["tour_sweep25"]
    paired.append(dict(case=case, joint25_s=group["joint25"]["virtual_time_s"],
                        sweep25_s=base["virtual_time_s"], tour_s=tour["virtual_time_s"],
                        delta_s=tour["virtual_time_s"]-base["virtual_time_s"],
                        move_delta_s=tour["move_s"]-base["move_s"]))
    for policy in group:
        rows = [json.loads(s) for s in (ROOT / "actions" / f"{case}_{policy}.jsonl").read_text(encoding="utf-8").splitlines()]
        moves = [r for r in rows if r["reason"] in ("sweep_next_discovery_node", "sweep_tour_next_discovery_node")]
        if policy != "joint25":
            route_audit.append(dict(case=case, policy=policy, discovery_moves=len(moves),
                                    discovery_distance_m=sum(r["response"]["costs"]["move_s"]*5 for r in moves)))
        sources = {s["channel"]: s for s in cases[case]["sources"]}
        errors = []
        for row in rows:
            if row["response"].get("measure_result") == "direction":
                q, s = row["position"], sources[row["channel"]]["position"]
                true = math.degrees(math.atan2(s[1]-q[1], s[0]-q[0]))
                errors.append(abs((row["response"]["svd_deg"]-true+180)%360-180))
        assert max(errors) <= 1.00500001
        error_audit.append(dict(case=case, policy=policy, direction_count=len(errors),
                                max_return_error_deg=max(errors), count_over_1=sum(e>1+1e-12 for e in errors)))
events = [e for path in (ROOT / "routes").glob("*.json") for e in json.loads(path.read_text(encoding="utf-8"))]
summary = dict(paired=paired, discovery_routes=route_audit, returned_error_audit=error_audit,
               replan_count=len(events), changed_next_count=sum(e["changed"] for e in events),
               improved_route_count=sum(e["nearest_length_m"]-e["route_length_m"]>1e-6 for e in events),
               max_route_gain_m=max(e["nearest_length_m"]-e["route_length_m"] for e in events),
               tour_planning_total_s=sum(e["planning_s"] for e in events),
               mean_delta_s=sum(r["delta_s"] for r in paired)/len(paired),
               faster=sum(r["delta_s"]<0 for r in paired), slower=sum(r["delta_s"]>0 for r in paired))
(ROOT / "route_analysis.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
print(json.dumps({k:v for k,v in summary.items() if k not in ("discovery_routes", "returned_error_audit")},ensure_ascii=False))
