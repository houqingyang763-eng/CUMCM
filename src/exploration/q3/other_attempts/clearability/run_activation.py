"""复用已保存初始选择，只对函数/筛选进行配对。"""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from activation_only import ActivationOnly,a
from diagnose import replay

HERE=Path(__file__).resolve().parent
OUT=HERE/'runs/activation_only'


def task(item):
    case,selected=item
    directory=OUT/case['name'];directory.mkdir(parents=True,exist_ok=True)
    a.base.dump(directory/'selection.json',selected)
    original=a.base.create_policy
    for mode in ('linear','sigmoid'):
        path=directory/mode
        if (path/'result.json').exists():continue
        try:
            a.base.create_policy=lambda name,config:(ActivationOnly(selected['selected'],mode),a.CoverageInformationState())
            a.base.execute_case(case,'patrol',a.CONFIG,path,{'action_limit':3000,'wall_limit_s':1200,'virtual_limit_s':10800})
        finally:a.base.create_policy=original
        r=json.loads((path/'result.json').read_text(encoding='utf-8'))
        if r['success']:a.base.dump(path/'audit.json',{'replayed':replay(path,a.Scenario.from_dict(case))})
        print(json.dumps({'case':case['name'],'shape':mode,'success':r['success'],'minutes':r['total_s']/60,'scans':r['measure_count'],'error':r['failreason']},ensure_ascii=False),flush=True)
    return case['name']


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    demo=HERE.parent/'refinement/runs/demo_f3_20260912'
    cases=json.loads((demo/'cases.json').read_text(encoding='utf-8'))+json.loads((HERE/'fresh_cases.json').read_text(encoding='utf-8'))
    items=[]
    for i,c in enumerate(cases):
        source=demo if i==0 else HERE/'runs/fresh_loaded'
        selection=json.loads((source/c['name']/'selection.json').read_text(encoding='utf-8'))
        items.append((c,selection))
    a.base.dump(OUT/'cases.json',cases)
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [HERE/'activation_only.py',HERE/'run_activation.py',HERE/'policy.py']}
    a.base.dump(OUT/'manifest.json',{'hashes':hashes,'design':'same gate, same candidates, same posterior; linear vs sigmoid; F3 without gate separately retained'})
    with concurrent.futures.ProcessPoolExecutor(max_workers=3) as pool:
        for f in concurrent.futures.as_completed([pool.submit(task,x) for x in items]):print(f.result(),flush=True)


if __name__=='__main__':main()
