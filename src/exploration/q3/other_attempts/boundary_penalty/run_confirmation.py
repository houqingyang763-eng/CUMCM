"""开发后冻结 λ=60 秒，在六个未运行的新种子上独立配对。"""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from boundary_policy import BoundaryPolicy, RefinedPolicy, a
from diagnose import replay

HERE = Path(__file__).resolve().parent
OUT = HERE/'runs/confirmation'
STRENGTH = 60.


def task(case_data):
    case = a.Scenario.from_dict(case_data)
    directory = OUT/case.name
    cache = directory/'selection.json'
    state = a.first_state(case)
    if cache.exists():
        saved = json.loads(cache.read_text(encoding='utf-8'))
        assert saved['history_seed'] == a.history_seed(state)
        selected = saved['selected']
    else:
        print(json.dumps({'case':case.name, 'stage':'selecting_second_point'}), flush=True)
        selection = a.select(state, 16)
        selected = next(x for x in selection['candidates'] if x['id'] == selection['position'])
        a.base.dump(cache, dict(selection, selected=selected, history_seed=a.history_seed(state)))
    original = a.base.create_policy
    for mode in ('f3','penalty60'):
        path = directory/mode
        if (path/'result.json').exists():
            continue
        try:
            if mode == 'f3':
                a.base.create_policy = lambda name, config: (RefinedPolicy(selected, 3, 4), a.CoverageInformationState())
            else:
                a.base.create_policy = lambda name, config: (BoundaryPolicy(selected, STRENGTH), a.CoverageInformationState())
            a.base.execute_case(case_data, 'patrol', a.CONFIG, path,
                                {'action_limit':3000, 'wall_limit_s':1200, 'virtual_limit_s':10800})
        finally:
            a.base.create_policy = original
        result = json.loads((path/'result.json').read_text(encoding='utf-8'))
        if result['success']:
            a.base.dump(path/'audit.json', {'replayed':replay(path, case)})
        print(json.dumps({'case':case.name, 'mode':mode, 'success':result['success'],
                          'minutes':result['total_s']/60, 'error':result['failreason']}), flush=True)
    return case.name


def main():
    cases = []
    specs = [('uniform','hashed',12), ('uniform','hashed',16),
             ('edge','biased',12), ('edge','biased',16),
             ('cluster','smooth',14), ('line','hashed',10)]
    for i, (layout, noise, n) in enumerate(specs):
        seed = 2026091200 + i*10
        seed += (n-10-seed%7)%7
        data = a.base.generate(seed, layout, noise).to_dict()
        assert len(data['sources']) == n
        cases.append(data)
    OUT.mkdir(parents=True, exist_ok=True)
    a.base.dump(OUT/'cases.json', cases)
    a.base.dump(OUT/'manifest.json', {
        'strengths_s':[STRENGTH],
        'baselines_relative_to_repository':{c['name']:str((OUT/c['name']/'f3').relative_to(HERE.parents[2])) for c in cases},
        'design':'frozen after development; independent new scenarios; no retuning; original F3 paired on same initial selection',
        'hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (HERE/'boundary_policy.py', HERE/'run_confirmation.py', HERE.parent/'refinement/refined.py', HERE.parent/'refinement/posterior.py')},
    })
    with concurrent.futures.ProcessPoolExecutor(max_workers=3) as pool:
        for value in pool.map(task, cases):
            print(value, flush=True)


if __name__ == '__main__':
    main()
