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


def objective(rows):
    if not rows or not all(r["success"] for r in rows):
        return math.inf
    values = [r["virtual_time_s"] for r in rows]
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
    args = parser.parse_args()
    check_cached()
    out = args.output.resolve()
    if ROOT not in out.parents:
        raise ValueError("输出须位于当前夜间实验目录")
    out.mkdir(parents=True, exist_ok=False)
    rng = random.Random(args.seed)
    configs = {"default": {}}
    configs.update({f"candidate_{i:02}": sample_config(rng) for i in range(args.candidates-1)})
    dump(out/"candidates.json", configs)
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
    dump(out/"manifest.json", dict(seed=args.seed, policy="completion", code_sha256=snapshots,
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
        ranked = sorted(active, key=lambda name: objective(records[name]))
        stages.append(dict(stage=index, ranking=[dict(name=n, score=objective(records[n]),
                            cases=len(records[n]), complete=all(r["success"] for r in records[n])) for n in ranked]))
        dump(out/"stages.json", stages)
        print(json.dumps(stages[-1], ensure_ascii=False), flush=True)
        # 仅淘汰，不做模块逐个关闭的消融；少数有希望的配置获得更多案例。
        keep = max(2, math.ceil(len(ranked)/2))
        active = [n for n in ranked[:keep] if math.isfinite(objective(records[n]))]
        if not active:
            raise RuntimeError("没有通过完整案例检查的配置")
    winner = min(active, key=lambda name: objective(records[name]))
    dump(out/"selected_config.json", configs[winner])
    dump(out/"runner_config.json", {"completion": configs[winner]})
    dump(out/"selection.json", dict(winner=winner, selection_score=objective(records[winner]),
         selection_cases=len(records[winner]), elapsed_s=time.perf_counter()-started,
         next_step="冻结配置，用新的未查看案例与默认 Completion 和原基础策略比较；这是开发成绩"))
    print(json.dumps(read_json(out/"selection.json")), flush=True)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
