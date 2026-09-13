"""小改法冻结对照；只调用自建环境，显式锁定实验及正式依赖。"""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT/'src/q4'))
import common
from cases import build_cases
from simulation import Scenario
from run import IndependentAudit, run_case, verify_hashes, dump

HERE = Path(__file__).resolve().parent
RESULT_ROOT = PROJECT/'outputs/experiments/q4/micro_changes'
SPECS = {'A':'A=micro_a:MicroAPolicy','B':'B=micro_b:MicroBPolicy','selected':'selected'}


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def load(path): return json.loads(Path(path).read_text(encoding='utf-8'))


def catalog():
    items=[]
    for split,batch in [('regression_regular','holdout01'),('regression_pressure','pressure01')]:
        manifest=load(PROJECT/f'outputs/q4/{batch}/manifest.json')
        verify_hashes(manifest['code_sha256'])
        for folder in sorted((PROJECT/f'outputs/q4/{batch}/cases').iterdir()):
            source=folder/'selected'
            items.append(dict(group=split,scene=load(source/'case.json'),
                              reference=str(source.relative_to(PROJECT))))
    new=build_cases('holdout',limit=8,seed_offset=2000)+build_cases('pressure',limit=8,seed_offset=2000)
    seeds={x['scene']['seed'] for x in items}
    for scene in new:
        assert scene.seed not in seeds
        seeds.add(scene.seed)
        items.append(dict(group='new_regular' if scene.seed<946000 else 'new_pressure',
                          scene=scene.to_dict(),reference=None))
    assert len(items)==48 and len(seeds)==48
    return json.loads(json.dumps(items,ensure_ascii=False))


def lock_catalog():
    items=catalog(); path=RESULT_ROOT/'catalog.json'
    if path.exists():
        assert load(path)==items, '冻结案例定义发生变化'
    else: dump(path,items)
    return items


def verify_references(items):
    checks=[]
    for item in items:
        if item['reference'] is None: continue
        folder=PROJECT/item['reference']; result=load(folder/'result.json')
        audit=IndependentAudit(Scenario.from_dict(item['scene']))
        rows=[json.loads(s) for s in (folder/'actions.jsonl').read_text(encoding='utf-8').splitlines()]
        for row in rows: audit.update(row,row['response'])
        assert result['success'] and result['independent_audit_passed']
        assert len(audit.cleared)==len(item['scene']['sources'])==result['cleared']
        assert abs(audit.virtual_time_s-result['virtual_time_s'])<1e-5
        checks.append(dict(case=result['case'],actions=len(rows),cleared=len(audit.cleared),
                           hashes={f:sha(folder/f) for f in ('case.json','result.json','actions.jsonl','ledger.json')},
                           time_s=audit.virtual_time_s,ledger=audit.ledger))
    dump(RESULT_ROOT/'reference_audit.json',checks)
    return checks


def dependencies(policy):
    hashes=load(PROJECT/'outputs/q4/holdout01/manifest.json')['code_sha256']
    verify_hashes(hashes)
    hashes=dict(hashes)
    for path in [Path(__file__)]+([HERE/f'micro_{policy.lower()}.py'] if policy!='selected' else []):
        hashes[str(path.relative_to(PROJECT)).replace('\\','/')]=sha(path)
    return hashes


def worker(payload):
    return run_case(Scenario.from_dict(payload['scene']),payload['spec'],payload['output'],
                    expected_hashes=payload['hashes'],max_wall_s=1200,max_actions=5000,max_virtual_s=360000)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--policy',choices=tuple(SPECS),default='A')
    p.add_argument('--group',choices=('all','regression','new'),default='all')
    p.add_argument('--workers',type=int,choices=(1,2,3),default=3)
    p.add_argument('--prepare',action='store_true')
    p.add_argument('--case-seeds',type=int,nargs='*')
    args=p.parse_args();items=lock_catalog()
    if args.prepare:
        checks=verify_references(items)
        print(json.dumps(dict(cases=len(items),reference_runs=len(checks),
              actions=sum(r['actions'] for r in checks),new_seeds=[x['scene']['seed'] for x in items if x['reference'] is None])))
        return
    hashes=dependencies(args.policy)
    root=RESULT_ROOT/args.policy
    manifest=dict(policy=args.policy,spec=SPECS[args.policy],hashes=hashes,catalog_sha256=sha(RESULT_ROOT/'catalog.json'),
                  max_wall_s=1200,max_actions=5000,max_virtual_s=360000,numerical_pair_tolerance_s=1e-4)
    if (root/'manifest.json').exists(): assert load(root/'manifest.json')==manifest
    else: dump(root/'manifest.json',manifest)
    chosen=[x for x in items if args.group=='all' or (args.group=='new')==(x['reference'] is None)]
    if args.case_seeds: chosen=[x for x in chosen if x['scene']['seed'] in args.case_seeds]
    pending=[]
    for item in chosen:
        folder=root/'cases'/item['scene']['name']
        if (folder/'result.json').exists():
            # 任何既有结果，包括失败，均保留且不在同目录覆盖重试。
            continue
        pending.append(dict(scene=item['scene'],spec=SPECS[args.policy],output=str(folder),hashes=hashes))
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures=[executor.submit(worker,payload) for payload in pending]
        for future in as_completed(futures):
            r=future.result()
            dump(root/'last_progress.json',dict(updated_utc=datetime.now(timezone.utc).isoformat(),
                                               case=r['case'],success=r['success']))
            print(json.dumps(dict(case=r['case'],success=r['success'],time_s=r['virtual_time_s'],
                                  wall_s=r['wall_time_s'],actions=r['actions'],error=r['error']),ensure_ascii=False),flush=True)
    verify_hashes(hashes)
    print('COMPLETE',args.policy,len(pending),flush=True)

if __name__=='__main__': main()
