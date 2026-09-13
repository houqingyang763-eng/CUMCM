"""重放Sweep反例的全部公开日志，分解发现阶段、收尾及移动费用。"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics

from task_cost import g
from state import InformationState
from astra_guard import check_cached
from runner import dump

ROOT = Path(__file__).resolve().parent
INPUT = ROOT / "runs/q3_sweep_validation"


def replay(path):
    state = InformationState()
    phases = {name: dict(move_s=0.0, switch_s=0.0, measure_s=0.0, clear_s=0.0, actions=0)
              for name in ("discovery", "cleanup")}
    moves, node_stops = [], []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    transition = None
    for row in rows:
        action = {key: value for key, value in row.items() if key not in ("response", "step")}
        q = tuple(action["position"])
        unknown = sum(c.status == "unknown" for c in state.channels.values())
        phase = "discovery" if unknown else "cleanup"
        charges = phases[phase]
        move = g.distance(state.position, q) / 5
        switch = int(action["kind"] == "measure" and action["channel"] != state.measuring_channel)
        operation = 5 if action["kind"] == "measure" or row["response"]["clear_result"] == "success" else 3
        assert abs(row["response"]["virtual_time_s"]-state.virtual_time_s-move-switch-operation) < 1e-6
        charges["move_s"] += move
        charges["switch_s"] += switch
        charges["measure_s" if action["kind"] == "measure" else "clear_s"] += operation
        charges["actions"] += 1
        if move > 1e-6:
            moves.append(dict(step=row["step"], position=q, move_s=move, reason=action["reason"],
                              unknown_before=unknown, found_before=sum(c.status == "found" for c in state.channels.values()),
                              channel=action["channel"]))
            if node_stops:
                node_stops[-1]["ever_seen_at_departure"] = len(state.ever_seen)
            if action["reason"] == "sweep_next_discovery_node":
                node_stops.append(dict(step=row["step"], position=q, ever_seen_before_arrival=len(state.ever_seen)))
        state.update(action, row["response"])
        if unknown and not any(c.status == "unknown" for c in state.channels.values()):
            transition = dict(step=row["step"], virtual_time_s=state.virtual_time_s, position=state.position,
                              seen=len(state.ever_seen), cleared=sum(c.status == "cleared" for c in state.channels.values()))
    if node_stops and "ever_seen_at_departure" not in node_stops[-1]:
        node_stops[-1]["ever_seen_at_departure"] = len(state.ever_seen)
    assert state.complete
    return dict(trace_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), actions=len(rows), phases=phases,
                discovery_finished=transition, moves=moves, discovery_nodes=node_stops, virtual_time_s=state.virtual_time_s)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "runs/sweep_counterexample/trace_analysis")
    args = parser.parse_args()
    check_cached()
    args.output.mkdir(parents=True, exist_ok=False)
    results = json.loads((INPUT / "results.json").read_text(encoding="utf-8"))
    cases = list(dict.fromkeys(row["case"] for row in results))
    traces = {}
    for case in cases:
        check_cached()
        traces[case] = {name: replay(INPUT / "actions" / f"{case}_{name}.jsonl") for name in ("completion", "sweep")}
    groups = {}
    for name in ("completion", "sweep"):
        selected = [row for row in results if row["policy"] == name]
        times = sorted((r["virtual_time_s"] for r in selected), reverse=True)
        groups[name] = dict(mean_s=statistics.mean(times), worst_s=times[0], slowest_quarter_mean_s=statistics.mean(times[:3]),
                            failed_clears=sum(r["failed_clears"] for r in selected),
                            layout_means={layout:statistics.mean(r["virtual_time_s"] for r in selected if r["layout"]==layout)
                                          for layout in ("uniform", "edge", "cluster", "line")})
    deltas = {case:traces[case]["sweep"]["virtual_time_s"]-traces[case]["completion"]["virtual_time_s"] for case in cases}
    target = {r["policy"]:r for r in results if r["case"] == "line_biased_48110"}
    differences = {key:target["sweep"][key]-target["completion"][key]
                   for key in ("move_s", "switch_s", "measure_s", "clear_s", "virtual_time_s")}
    dump(args.output / "analysis.json", dict(groups=groups, paired_differences_s=deltas,
         counterexample_cost_differences=differences, sweep_wins=sum(v<0 for v in deltas.values()),
         sweep_losses=sum(v>0 for v in deltas.values()), public_trace_replays=traces))
    print(json.dumps(dict(groups=groups, paired_differences_s=deltas, counterexample_cost_differences=differences),ensure_ascii=False))


if __name__ == "__main__":
    main()
