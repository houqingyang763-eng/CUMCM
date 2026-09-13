"""主比较后的单次随机审查与新种子复验；随机案例不按成绩重抽。"""
import argparse
import concurrent.futures
import hashlib
import importlib.util
import json
import secrets
import statistics
import time
from pathlib import Path

from refined import RefinedPolicy
from posterior import a
# adaptive的历史导入会改sys.path，必须明确载入本目录运行器。
_spec=importlib.util.spec_from_file_location('refinement_runner',Path(__file__).with_name('run.py'))
_runner=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_runner)
summarize=_runner.summarize


def position_selection(state):
    # 与原a.select的position分支完全相同；省去不会参与position选择的频道子集。
    worlds,info=a.sample_worlds(state,16)
    records=[]
    for option in a.candidates(state):
        if option['set']!='all':continue
        values=[a.rollout(state,w,option) for w in worlds]
        records.append(dict(option,costs_s=values,mean_s=statistics.mean(values),errors=[]))
    chosen=min(records,key=lambda x:x['mean_s'])
    return {'selected':chosen,'candidates':records,'posterior':info,'history_seed':a.history_seed(state),
            'origin':'same_position_rule_all_channel_candidates_only'}


def task(data):
    case_data,out,modes=data
    case=a.Scenario.from_dict(case_data);directory=Path(out)/case.name
    directory.mkdir(parents=True,exist_ok=True)
    path=directory/'selection.json'
    if path.exists():record=json.loads(path.read_text())
    else:
        start=time.perf_counter();record=position_selection(a.first_state(case));record['wall_s']=time.perf_counter()-start
        a.base.dump(path,record)
    selected=record['selected'];old=a.base.create_policy
    for mode in modes:
        path=directory/mode/'result.json'
        if path.exists():continue
        try:
            if mode=='current':
                a.base.create_policy=lambda name,config:(a.AdaptivePolicy(selected),a.CoverageInformationState());name='patrol'
            elif mode=='baseline':
                a.base.create_policy=old;name='baseline'
            elif mode=='f4':
                from verified import VerifiedPolicy
                a.base.create_policy=lambda name,config:(VerifiedPolicy(selected),a.CoverageInformationState());name='patrol'
            else:
                a.base.create_policy=lambda name,config:(RefinedPolicy(selected,int(mode[-1]),4),a.CoverageInformationState());name='patrol'
            a.base.execute_case(case_data,name,a.CONFIG,directory/mode,{'action_limit':3000,'wall_limit_s':1200,'virtual_limit_s':10800})
        finally:a.base.create_policy=old
        result=json.loads(path.read_text())
        print(json.dumps({'case':case.name,'mode':mode,'success':result['success'],'min':round(result['total_s']/60,3),
                          'wall_s':round(result['wall_s'],1),'error':result['failreason']},ensure_ascii=False),flush=True)
    return case.name


def main():
    p=argparse.ArgumentParser();p.add_argument('--stage',choices=['random','micro'],required=True)
    p.add_argument('--out',required=True,type=Path);p.add_argument('--modes',nargs='+',default=['current','f1','f3'])
    p.add_argument('--workers',type=int,default=3);args=p.parse_args();out=args.out
    out.mkdir(parents=True,exist_ok=True)
    if (out/'cases.json').exists():cases=[a.Scenario.from_dict(c) for c in json.loads((out/'cases.json').read_text())]
    elif args.stage=='random':
        seed=secrets.randbelow(2**31)
        cases=[a.base.generate(seed,'uniform','hashed')]
        a.base.dump(out/'random_draw.json',{'seed':seed,'unix_time':time.time(),'draws':1,'selection':'one_unfiltered_draw'})
    else:
        cases=[a.base.generate(320100+i,l,n) for i,(l,n) in enumerate(( (l,n) for l in ('uniform','edge','cluster','line') for n in ('smooth','biased','hashed') for _ in range(2)))]
    a.base.dump(out/'cases.json',[c.to_dict() for c in cases])
    source_paths=list(Path(__file__).parent.glob('*.py'))+list(a.HERE.glob('*.py'))+list((a.HERE.parent/'probability_patrol').glob('*.py'))+list((a.HERE.parents[1]/'b_adaptive_q3').glob('*.py'))+[a.HERE.parents[1]/'b_overnight/coverage.py']
    hashes={str(f.relative_to(a.base.ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in source_paths}
    # 每次扩展运行保留单独清单，不覆盖此前版本的源码指纹。
    a.base.dump(out/f'manifest_{"_".join(args.modes)}.json',{'stage':args.stage,'modes':args.modes,'hashes':hashes,'time':time.time()})
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as pool:
        jobs=[pool.submit(task,(c.to_dict(),str(out),args.modes)) for c in cases]
        for f in concurrent.futures.as_completed(jobs):
            print('completed '+f.result(),flush=True);summarize(out,args.modes)
    summarize(out,args.modes)


if __name__=='__main__':main()
