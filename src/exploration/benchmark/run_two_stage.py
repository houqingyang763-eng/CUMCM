"""两阶段基线配对实验；自建环境、固定种子、逐动作核验。"""
import argparse
import csv
import hashlib
import json
import math
import platform
import statistics
import time
import traceback
from pathlib import Path

from two_stage import ROOT, CONFIGS, TwoStagePolicy, g
from simulation import LocalEnvironment, Scenario, Source, generate
from state import InformationState, audit_state


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scenarios(stage):
    if stage == 'replay':
        path = ROOT/'experiments/b_overnight/runs/q3_sweep_validation/cases.json'
        return [Scenario.from_dict(c) for c in json.loads(path.read_text(encoding='utf-8'))]
    if stage == 'stress':
        result = []
        for i in range(8):
            n = 10 if i%2 == 0 else 16
            sources=[]
            for k in range(n):
                if i < 4:
                    a = 2*math.pi*k/n + (i//2)*math.pi/6
                    q = (1800*math.cos(a),1800*math.sin(a))
                elif i < 6:
                    q = (0.,0.) if k < 3 else (1200 + (k-3)*0.01, 0.)
                else:
                    q = (-1799+3598*k/(n-1), (k%2)*0.01)
                sources.append(Source(k+1,q,1000.))
            result.append(Scenario(f'stress_{i}',150000+i,'stress', 'biased' if i%2 else 'zero',tuple(sources)))
        return result
    base, repeats = (130100,1) if stage=='development' else (140100,2)
    cases=[]
    for layout in ('uniform','edge','cluster','line'):
        for noise in ('smooth','biased','hashed'):
            for _ in range(repeats):
                cases.append(generate(base+len(cases),layout,noise))
    return cases


def run_case(case, name, out):
    assert 10 <= len(case.sources) <= 16
    assert all(s.orientation is None and 1000 <= s.radius <= 1500 and math.hypot(*s.position)<=1800+1e-6 for s in case.sources)
    policy = TwoStagePolicy(CONFIGS[name])
    env, state = LocalEnvironment(case), InformationState()
    ledger=dict(move_s=0., measure_s=0., switch_s=0., success_clear_s=0., fail_clear_s=0.)
    began=time.perf_counter()
    previous=(0.,0.)
    channel=1
    actions=[]
    error=None
    try:
        while not state.complete:
            if len(actions)>=3000 or time.perf_counter()-began>1200:
                raise TimeoutError('动作或现实时间保护，不计成功')
            action=policy.choose(state)
            assert action is not None
            assert math.hypot(*action['position']) <= 5000+1e-5
            response=env.act(action)
            row=dict(step=len(actions)+1,**action,response=response)
            actions.append(row)
            ledger['move_s']+=math.dist(previous,action['position'])/5
            if action['kind']=='measure':
                ledger['switch_s']+=int(channel!=action['channel'])
                ledger['measure_s']+=5
                channel=action['channel']
            else:
                ledger['success_clear_s' if response['clear_result']=='success' else 'fail_clear_s']+=5 if response['clear_result']=='success' else 3
            previous=action['position']
            assert abs(sum(ledger.values())-env.virtual_time_s)<1e-5
            state.update(action,response)
            audit_state(state,env)
            assert env.virtual_time_s<360000
        assert len(env.cleared)==len(case.sources)
        assert policy.phase_change is not None
        scan=[a for a in actions if a['phase']=='scan']
        assert all(a['kind']=='measure' for a in scan)
        assert len({(tuple(a['position']),a['channel']) for a in scan})==len(scan)
        assert len(scan)<=20*CONFIGS[name].point_count
    except Exception:
        error=traceback.format_exc()
    (out/'actions'/f'{case.name}_{name}.jsonl').write_text(''.join(json.dumps(a,ensure_ascii=False)+'\n' for a in actions),encoding='utf-8')
    metadata=policy.metadata()
    dump(out/'plans'/f'{case.name}_{name}.json',metadata)
    scan_time=metadata['phase_change']['time_s'] if metadata['phase_change'] else None
    result=dict(case=case.name,seed=case.seed,layout=case.layout,noise=case.noise,policy=name,
        success=error is None and state.complete,source_count=len(case.sources),cleared=len(env.cleared),
        total_s=env.virtual_time_s,per_source_s=env.virtual_time_s/len(case.sources) if state.complete else None,
        scan_s=scan_time,service_s=env.virtual_time_s-scan_time if scan_time is not None else None,
        stage1_radii_m=list(metadata['phase_change']['radii_m'].values()) if metadata['phase_change'] else [],
        scan_measures=sum(a['phase']=='scan' for a in actions),
        service_measures=sum(a['phase']=='service' and a['kind']=='measure' for a in actions),
        fail_clears=int(ledger['fail_clear_s']/3),fallback_targets=len(policy.fallback_targets),
        center_tries=sum(a['reason']=='small_region_center_try' for a in actions),
        center_successes=sum(a['reason']=='small_region_center_try' and a['response']['clear_result']=='success' for a in actions),
        actions=len(actions),wall_s=time.perf_counter()-began,error=error,**ledger)
    return result


def report(rows,out):
    summary={}
    lines=['# 两阶段基线测试结果','','固定扫描后允许区域仍大于20米；访问目标时补测或小范围试清。全部为自建案例结果，不是官方成绩。','',
           '| 策略 | 全清局 | 平均整局/分 | 每源均值/秒 | 最慢四分之一每源/秒 | 扫描/分 | 服务/分 | 失败试清/局 |',
           '|---|---:|---:|---:|---:|---:|---:|---:|']
    for name in sorted({r['policy'] for r in rows}):
        rs=[r for r in rows if r['policy']==name]
        good=[r for r in rs if r['success']]
        stats={'cases':len(rs),'successes':len(good),'sources':sum(r['source_count'] for r in rs)}
        if len(good)==len(rs):
            for key in ('total_s','per_source_s','scan_s','service_s','fail_clears','service_measures','scan_measures','wall_s'):
                stats[key]=statistics.mean(r[key] for r in rs)
            stats['worst_quarter_per_source_s']=statistics.mean(sorted((r['per_source_s'] for r in rs),reverse=True)[:math.ceil(len(rs)/4)])
            stats['max_per_source_s']=max(r['per_source_s'] for r in rs)
            stats['min_total_s']=min(r['total_s'] for r in rs)
            stats['max_total_s']=max(r['total_s'] for r in rs)
            stats['fallback_targets']=sum(r['fallback_targets'] for r in rs)
            stats['center_tries']=sum(r['center_tries'] for r in rs)
            stats['center_successes']=sum(r['center_successes'] for r in rs)
            radii=[x for r in rs for x in r['stage1_radii_m']]
            stats['stage1_radius_median_m']=statistics.median(radii)
            stats['stage1_radius_max_m']=max(radii)
            stats['stage1_radius_gt60_count']=sum(x>60 for x in radii)
            lines.append(f'| {name} | {len(good)}/{len(rs)} | {stats["total_s"]/60:.2f} | {stats["per_source_s"]:.2f} | {stats["worst_quarter_per_source_s"]:.2f} | {stats["scan_s"]/60:.2f} | {stats["service_s"]/60:.2f} | {stats["fail_clears"]:.2f} |')
        else:
            lines.append(f'| {name} | {len(good)}/{len(rs)} | 失败，不给成功局选择性均值 | — | — | — | — | — |')
        summary[name]=stats
    lines+=['','逐例数据见 results.csv/json，逐动作检查见 actions/，估计区域与每次路线见 plans/。样本最大值及尾部均值不是总体最坏保证。','']
    (out/'RESULTS.md').write_text('\n'.join(lines),encoding='utf-8')
    dump(out/'summary.json',summary)
    flat=[{k:v for k,v in r.items() if k!='stage1_radii_m'} for r in rows]
    with (out/'results.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=list(flat[0]));writer.writeheader();writer.writerows(flat)
    return summary


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--stage',choices=['development','holdout','replay','stress'],required=True)
    p.add_argument('--policies',nargs='+',choices=list(CONFIGS),required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    out=args.output.resolve()
    assert ROOT/'experiments/b_benchmark_scale' in out.parents
    out.mkdir(parents=True,exist_ok=False)
    for name in ['actions','plans','source']: (out/name).mkdir()
    folders=['b_adaptive_q3','b_benchmark_scale']
    files=[p for folder in folders for p in (ROOT/'experiments'/folder).glob('*.py')]
    files += [ROOT/'experiments/b_overnight/task_cost.py',ROOT/'experiments/b_oracle_q3/oracle.py']
    hashes={}
    for path in files:
        relative=path.relative_to(ROOT/'experiments')
        target=out/'source'/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(path.read_bytes())
        hashes[str(relative)]=sha(path)
    cases=scenarios(args.stage)
    dump(out/'cases.json',[c.to_dict() for c in cases])
    dump(out/'manifest.json',dict(stage=args.stage,policies=args.policies,python=platform.python_version(),
        case_sha256=sha(out/'cases.json'),source_sha256=hashes,created=time.strftime('%Y-%m-%d %H:%M:%S %z'),
        environment='自建固定空间误差场，舍入两位小数；不读取官方隐藏案例',
        configs={name:vars(CONFIGS[name]) for name in args.policies}))
    rows=[]
    for case in cases:
        for name in args.policies:
            result=run_case(case,name,out)
            rows.append(result)
            dump(out/'results.json',rows)
            print(json.dumps({k:result[k] for k in ['case','policy','success','total_s','fail_clears','wall_s','error']},ensure_ascii=False),flush=True)
    print(json.dumps(report(rows,out),ensure_ascii=False),flush=True)
    if not all(r['success'] for r in rows):raise SystemExit(1)


if __name__=='__main__':main()
