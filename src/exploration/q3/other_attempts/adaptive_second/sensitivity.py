"""预先按布局抽取首例，用独立后验样本检查既有选择；不重选实际策略。"""
import concurrent.futures
import json
import statistics
import sys
from pathlib import Path
import adaptive as a


def task(data):
    case_data,folder,prior=data
    case=a.Scenario.from_dict(case_data)
    directory=Path(folder)/case.name
    selection=json.loads((directory/'selection.json').read_text())
    state=a.first_state(case)
    worlds,posterior=a.sample_worlds(state,64,81723,prior)
    ids=list(dict.fromkeys(selection[m] for m in ('fixed','position','joint')))
    values={}
    for id in ids:
        candidate=next(c for c in selection['candidates'] if c['id']==id)
        values[id]=[a.rollout(state,world,candidate) for world in worlds]
    result={'case':case.name,'prior':prior,'samples':64,'posterior':posterior,'values':values,
            'independent_predicted_saving_min':{m:statistics.mean((x-y)/60 for x,y in zip(values[selection['fixed']],values[selection[m]])) for m in ('position','joint')}}
    a.base.dump(directory/f'sensitivity_{prior}.json',result)
    return {k:v for k,v in result.items() if k!='values'}


if __name__=='__main__':
    folder=Path(sys.argv[1])
    cases=json.loads((folder/'cases.json').read_text())
    chosen=[]
    layouts=set()
    for case in cases:
        if case['layout'] not in layouts:
            chosen.append(case)
            layouts.add(case['layout'])
    with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
        jobs=[pool.submit(task,(case,str(folder),prior)) for case in chosen for prior in ('uniform','minimum')]
        for job in concurrent.futures.as_completed(jobs):
            print(json.dumps(job.result(),ensure_ascii=False),flush=True)
