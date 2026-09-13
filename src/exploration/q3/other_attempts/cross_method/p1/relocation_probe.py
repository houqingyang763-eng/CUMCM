"""在三条旧A长尾的公开规划状态上检查几何空间；不运行新策略。"""
import hashlib
import json
import time
from pathlib import Path
from relocate import lr,relocation

ROOT=lr.ROOT
BASE=ROOT/'outputs/experiments/b_q3_p1/light_screening_20260913'
OUT=ROOT/'outputs/experiments/b_q3_p1/relocation_probe_20260913'
NAMES=('cluster_biased_320115','line_smooth_320118','line_biased_320121')
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    OUT.mkdir(parents=True,exist_ok=False)
    frozen=read(BASE/'manifest.json')
    for p,h in frozen['code_hashes'].items():assert sha(ROOT/p)==h,p
    results=[];hashes={};started=time.perf_counter()
    for name in NAMES:
        path=BASE/'A'/name;rows=[json.loads(x) for x in (path/'actions.jsonl').read_text().splitlines()]
        plans=read(path/'metadata.json')['lightweight']['online_plans']
        by_action={p['at_action']:p for p in plans}
        last_clear=max(r['step'] for r in rows if r['kind']=='clear' and r['response'].get('clear_result')=='success')
        s=lr.a.CoverageInformationState();records=[]
        for row in rows:
            if s.actions>=last_clear and s.actions in by_action:
                plan=by_action[s.actions]
                assert not any(c.status=='found' for c in s.channels.values())
                assert tuple(plan['position'])==tuple(s.position)
                jobs=[{k:v for k,v in j.items() if k!='_light_id'} for j in plan['after_route']]
                original_history=lr.a.history_seed(s)
                route,record=relocation(s,jobs)
                assert original_history==lr.a.history_seed(s)
                records.append(record)
            s.update(row,row['response'])
        assert records,name
        result=dict(case=name,last_clear_step=last_clear,first_plan_saving_s=records[0]['nominal_saving_s'],
            first_plan=records[0],later_plans=records[1:])
        results.append(result)
        for filename in ('actions.jsonl','metadata.json','result.json'):hashes[(path/filename).relative_to(ROOT).as_posix()]=sha(path/filename)
        print(name,round(result['first_plan_saving_s'],3),'seconds of conditional route saving',flush=True)
    report=dict(scope='old public states and conditional plans only; no new environment trajectory',
        gate=any(r['first_plan_saving_s']>=30 for r in results),gate_threshold_s=30,
        cases=results,wall_s=time.perf_counter()-started,source_hashes=hashes,
        code_hashes={p.relative_to(ROOT).as_posix():sha(p) for p in [Path(__file__),Path(__file__).with_name('relocate.py'),Path(__file__).with_name('RELOCATION_DESIGN.md')]})
    lr.a.base.dump(OUT/'probe.json',report)
    print(json.dumps(dict(gate=report['gate'],wall_s=report['wall_s'])))

if __name__=='__main__':main()
