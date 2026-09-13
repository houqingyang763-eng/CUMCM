"""共同案例上的逐轮配置筛选；原创简化流程，不冒称已接入 irace。"""
import argparse
import json
import math
import random
import statistics
import time
from pathlib import Path

from runner import ROOT, BASE, dump, run_case
from simulation import generate
from astra_guard import check_cached


def objective(rows, metric="per_source"):
    if not rows or not all(r["success"] and r["cleared"] > 0 and r["cleared"] == r["source_count"] for r in rows):
        return math.inf
    if metric not in ("per_source", "total"):
        raise ValueError(metric)
    values = [r["virtual_time_s"] / r["cleared"] if metric == "per_source" else r["virtual_time_s"] for r in rows]
    tail = sorted(values)[-max(1, math.ceil(len(values)*.25)):]
    return statistics.mean(values)+.25*statistics.mean(tail)


def sample_config(rng, parent=None):
    bounds = {"current_probe_ratio": (.45, 2.5), "discovery_value_s": (60, 320),
              "work_gain_cap_s": (100, 500), "offset_scale": (.25, .9),
              "min_offset_m": (30, 100), "max_offset_m": (300, 900)}
    out = {}
    for name, (low, high) in bounds.items():
        if parent and name in parent:
            value = math.exp(rng.gauss(math.log(parent[name]), .25))
            out[name] = min(high, max(low, value))
        else:
            out[name] = math.exp(rng.uniform(math.log(low), math.log(high)))
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidates", type=int, default=12)
    parser.add_argument("--seed", type=int, default=30100)
    parser.add_argument("--max-wall-s", type=float, default=900)
    parser.add_argument("--parents", type=Path, help="既有筛选目录：保留精英、局部变异，并保留全局探索")
    parser.add_argument("--metric", choices=("per_source", "total"), default="per_source",
                        help="逐局平均每源秒为默认；历史两批使用total，保留原快照")
    args = parser.parse_args()
    check_cached()
    out = args.output.resolve()
    if ROOT not in out.parents:
        raise ValueError("输出须位于当前夜间实验目录")
    out.mkdir(parents=True, exist_ok=False)
    rng = random.Random(args.seed)
    configs = {"default": {}}
    lineage = {"default": {"kind": "default"}}
    if args.parents:
        old_configs = read_json(args.parents / "candidates.json")
        old_stages = read_json(args.parents / "stages.json")
        parents = [r["name"] for r in old_stages[-1]["ranking"][:3]]
        for i, name in enumerate(parents):
            key = f"elite_{i:02}"
            configs[key] = old_configs[name]
            lineage[key] = dict(kind="elite", prior_directory=str(args.parents), prior_name=name)
        global_count = max(1, (args.candidates - len(configs)) // 4)
        mutations = max(0, args.candidates - len(configs) - global_count)
        for i in range(mutations):
            parent = parents[i % len(parents)]
            key = f"mutation_{i:02}"
            configs[key] = sample_config(rng, old_configs[parent])
            lineage[key] = dict(kind="lognormal_mutation", prior_name=parent, log_sigma=.25)
        for i in range(global_count):
            key = f"exploration_{i:02}"
            configs[key] = sample_config(rng)
            lineage[key] = dict(kind="global_loguniform")
    else:
        configs.update({f"candidate_{i:02}": sample_config(rng) for i in range(args.candidates-1)})
        lineage.update({name: {"kind": "global_loguniform"} for name in configs if name != "default"})
    dump(out/"candidates.json", configs)
    dump(out/"lineage.json", lineage)
    snapshots = {}
    import hashlib
    for folder, prefix in ((BASE, "base"), (ROOT, "night")):
        for p in folder.glob("*.py"):
            if p.name == "astra_guard.py":
                continue
            data = p.read_bytes()
            target = out/"source"/prefix/p.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            snapshots[f"{prefix}/{p.name}"] = hashlib.sha256(data).hexdigest()
    dump(out/"manifest.json", dict(seed=args.seed, policy="completion", objective_metric=args.metric, code_sha256=snapshots,
        purpose="开发阶段逐轮筛选配置，未接入 irace，不把筛选成绩当独立验证"))
    # 每个区块覆盖四种布局；候选在同一批案例上配对，不用各自随机案例。
    blocks = []
    for block in range(3):
        blocks.append([generate(args.seed+block*100+i, layout, ("smooth", "biased", "hashed")[(block+i)%3])
                       for i, layout in enumerate(("uniform", "edge", "cluster", "line"))])
    dump(out/"cases.json", [[s.to_dict() for s in block] for block in blocks])
    records, stages = {name: [] for name in configs}, []
    active = list(configs)
    started = time.perf_counter()
    for index, block in enumerate(blocks):
        check_cached()
        previous = [r["wall_time_s"] for rs in records.values() for r in rs]
        estimated = (statistics.mean(previous) if previous else 2)*len(active)*len(block)
        if index and time.perf_counter()-started+estimated > args.max_wall_s:
            break
        for scene in block:
            for name in active:
                check_cached()
                result = run_case(scene, "completion", configs[name], out/"actions"/f"{scene.name}_{name}.jsonl")
                result["configuration"] = name
                records[name].append(result)
                dump(out/"records.json", records)
                if result["error"] and ("ASTRA_STOP" in result["error"] or "额度" in result["error"]):
                    raise SystemExit(3)
        ranked = sorted(active, key=lambda name: objective(records[name], args.metric))
        stages.append(dict(stage=index, ranking=[dict(name=n, score=objective(records[n], args.metric),
                            cases=len(records[n]), complete=all(r["success"] for r in records[n])) for n in ranked]))
        dump(out/"stages.json", stages)
        print(json.dumps(stages[-1], ensure_ascii=False), flush=True)
        # 仅淘汰，不做模块逐个关闭的消融；少数有希望的配置获得更多案例。
        keep = max(2, math.ceil(len(ranked)/2))
        active = [n for n in ranked[:keep] if math.isfinite(objective(records[n], args.metric))]
        if not active:
            raise RuntimeError("没有通过完整案例检查的配置")
    winner = min(active, key=lambda name: objective(records[name], args.metric))
    dump(out/"selected_config.json", configs[winner])
    dump(out/"runner_config.json", {"completion": configs[winner]})
    dump(out/"selection.json", dict(winner=winner, objective_metric=args.metric, selection_score=objective(records[winner], args.metric),
         selection_cases=len(records[winner]), elapsed_s=time.perf_counter()-started,
         next_step="冻结配置，用新的未查看案例与默认 Completion 和原基础策略比较；这是开发成绩"))
    print(json.dumps(read_json(out/"selection.json")), flush=True)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
