"""预定三个强度，用缓存初始选择与原 F3 配对；只运行本地模拟。"""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from boundary_policy import BoundaryPolicy, a
from diagnose import replay

HERE = Path(__file__).resolve().parent
OUT = HERE/'runs/development'
STRENGTHS = (60., 180., 600.)


def task(item):
    case, selection, strength = item
    directory = OUT/case['name']/f'penalty{strength:g}'
    if (directory/'result.json').exists():
        return str(directory)
    original = a.base.create_policy
    try:
        a.base.create_policy = lambda name, config: (BoundaryPolicy(selection['selected'], strength), a.CoverageInformationState())
        a.base.execute_case(case, 'patrol', a.CONFIG, directory,
                            {'action_limit':3000, 'wall_limit_s':1200, 'virtual_limit_s':10800})
    finally:
        a.base.create_policy = original
    result = json.loads((directory/'result.json').read_text(encoding='utf-8'))
    if result['success']:
        a.base.dump(directory/'audit.json', {'replayed':replay(directory, a.Scenario.from_dict(case))})
    return {'case':case['name'], 'strength_s':strength, 'success':result['success'],
            'minutes':result['total_s']/60, 'scans':result['measure_count'], 'error':result['failreason']}


def main():
    demo = HERE.parent/'refinement/runs/demo_f3_20260912'
    previous = HERE.parent/'clearability'
    cases = json.loads((demo/'cases.json').read_text(encoding='utf-8')) + json.loads((previous/'fresh_cases.json').read_text(encoding='utf-8'))
    OUT.mkdir(parents=True, exist_ok=True)
    items, baselines = [], {}
    for i, case in enumerate(cases):
        source = demo if i == 0 else previous/'runs/fresh_loaded'
        selection = json.loads((source/case['name']/'selection.json').read_text(encoding='utf-8'))
        a.base.dump(OUT/case['name']/'selection.json', selection)
        baselines[case['name']] = str((source/case['name']/'f3').relative_to(HERE.parents[2]))
        items.extend((case, selection, s) for s in STRENGTHS)
    a.base.dump(OUT/'cases.json', cases)
    a.base.dump(OUT/'manifest.json', {
        'strengths_s':STRENGTHS, 'baselines_relative_to_repository':baselines,
        'design':'isolated F3 candidate reranking; fixed initial choice, candidate set, F1 continuation, clearance and completion rules',
        'hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (HERE/'boundary_policy.py', HERE/'run_boundary.py', HERE.parent/'refinement/refined.py', HERE.parent/'refinement/posterior.py')},
    })
    with concurrent.futures.ProcessPoolExecutor(max_workers=3) as pool:
        for result in pool.map(task, items):
            print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
