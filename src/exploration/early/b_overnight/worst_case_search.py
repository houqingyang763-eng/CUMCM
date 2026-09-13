"""固定Q4联合25算法，在合法场景参数中主动寻找较大每源时间；最多16整局。"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import sys
import time

from q4 import Q4Config, Q4DirectionalPolicy, Q4InformationState
from q4_anchor_design import Q4Symmetric25Policy
from q4_joint_state import Q4JointCoverageInformationState
from q4run import run_case, dump
from simulation import Source, Scenario
from astra_guard import check_cached

ROOT=Path(__file__).resolve().parent


def polar(r, angle):
    a=math.radians(angle)
    return (r*math.cos(a),r*math.sin(a))


def initial_cases():
    specs=[('edge_outward10',10,15,'edge','outward'),
           ('edge_outward16',16,7.5,'edge','outward'),
           ('edge_tangent10',10,8,'edge','tangent'),
           ('edge_oblique16',16,20,'edge','oblique'),
           ('four_cluster10',10,13,'clusters','outward'),
           ('four_cluster16',16,0,'clusters','oblique'),
           ('radial_pairs10',10,17,'pairs','outward'),
           ('interlaced16',16,4,'interlaced','beam_edge')]
    result=[]
    for index,(name,n,rotation,layout,direction) in enumerate(specs):
        seed=78100+index
        channels=random.Random(seed).sample(range(1,21),n)
        sources=[]
        for i in range(n):
            if layout=='edge':
                p=polar(1799.9,rotation+360*i/n)
            elif layout=='clusters':
                center=polar(1670,rotation+90*(i%4))
                offset=polar(80,29*i)
                p=(center[0]+offset[0],center[1]+offset[1])
            elif layout=='pairs':
                p=polar(1750 if i%2==0 else 1000.01,rotation+72*(i//2))
            else:
                p=polar(1799.9 if i%2==0 else 1000.01,rotation+360*i/n)
            radial=math.degrees(math.atan2(p[1],p[0]))
            delta={'outward':0,'tangent':90,'oblique':35*(-1)**i,
                   'beam_edge':90+(-1)**i*.001}[direction]
            # 一个全向，其余为定向；合法地加重方向遮挡。
            orientation=None if i==0 else (radial+delta)%360
            sources.append(Source(channels[i],p,1000.01 if layout=='clusters' else 1000.0,orientation))
        scene=Scenario('wc_q4_'+name+'_'+str(seed),seed,name,'zero',tuple(sources))
        meta=dict(stage='initial',family=layout,direction_design=direction,
                  geometry_rotation_deg=rotation,source_count=n,omni_count=1,
                  fixed_noise='zero; only two-decimal bearing rounding',
                  purpose='主动寻找空间/朝向大开销，不代表抽样分布')
        result.append((scene,meta))
    return result


def perturb(parent, kind, slot):
    seed=78200+slot
    sources=[]
    channels=random.Random(seed).sample(range(1,21),len(parent.sources))
    for i,s in enumerate(parent.sources):
        p,phi,channel=s.position,s.orientation,s.channel
        if kind=='rigid_rotation':
            ca,sa=math.cos(math.radians(7.5)),math.sin(math.radians(7.5))
            p=(ca*p[0]-sa*p[1],sa*p[0]+ca*p[1])
            phi=None if phi is None else (phi+7.5)%360
        elif kind=='orientation_jitter':
            phi=None if phi is None else (phi+12*(-1)**i)%360
        elif kind=='channel_permutation':
            channel=channels[i]
        else:
            raise ValueError(kind)
        sources.append(Source(channel,p,s.radius,phi))
    scene=Scenario(parent.name+'_'+kind,seed,parent.layout+'_'+kind,'zero',tuple(sources))
    return scene,dict(stage='perturbation',parent=parent.name,kind=kind,
                     parameters={'rotation_deg':7.5,'alternating_orientation_deg':12,
                                 'channel_seed':seed}[{'rigid_rotation':'rotation_deg',
                                                      'orientation_jitter':'alternating_orientation_deg',
                                                      'channel_permutation':'channel_seed'}[kind]],
                     fixed_noise='zero; source-independent and channel-independent')


def validate(scene):
    assert 10<=len(scene.sources)<=16 and scene.noise=='zero'
    assert len({s.channel for s in scene.sources})==len(scene.sources)
    assert any(s.orientation is None for s in scene.sources)
    assert any(s.orientation is not None for s in scene.sources)
    for s in scene.sources:
        assert 1<=s.channel<=20 and 1000<=s.radius<=1500
        assert all(math.isfinite(v) for v in s.position) and math.hypot(*s.position)<=1800
        assert s.orientation is None or 0<=s.orientation<360


def rank(rows, metric='average_localization_clear_s'):
    return sorted(rows,key=lambda r:(r[metric],r['case']),reverse=True)


def main(output):
    check_cached()
    output=output.resolve()
    if ROOT/'runs'/'worst_case_search' not in output.parents:
        raise ValueError('产物必须在 runs/worst_case_search 子目录')
    output.mkdir(parents=True,exist_ok=False)
    frozen=[ROOT/n for n in ('q4.py','q4_anchor_design.py','q4_joint_state.py','q4_coverage.py',
                             'q4run.py','q2_geometry.py','task_cost.py','coverage.py')]
    frozen += [ROOT.parent/'b_adaptive_q3'/n for n in ('geometry.py','state.py','policy.py','simulation.py')]
    frozen_hashes={str(p.relative_to(ROOT.parent)):hashlib.sha256(p.read_bytes()).hexdigest() for p in frozen}
    for path in frozen+[Path(__file__)]:
        target=output/'source'/path.relative_to(ROOT.parent)
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(path.read_bytes())
    plan=dict(max_complete_runs=16,joint25_runs=14,baseline_runs=2,
              initial=8,selected_initial_parents=2,perturbations_per_parent=3,
              perturbations=['rigid rotation +7.5deg','alternating orientation +/-12deg','fixed channel permutation'],
              selection_metric='T / successful cleared sources, conditional on full clearance',
              noise='zero field with normal two-decimal return rounding',
              interpretation='定向困难搜索，不估计分布、失效率或总体均值；不改策略',
              code_sha256=frozen_hashes,script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              config=Q4Config().to_dict(),created_at=time.time(),python=sys.version)
    dump(output/'plan.json',plan)
    initial=initial_cases()
    scenes={s.name:s for s,m in initial}
    provenance={s.name:m for s,m in initial}
    results=[]
    dump(output/'cases.json',[s.to_dict() for s in scenes.values()])
    dump(output/'provenance.json',provenance)

    def execute(scene,name,stage):
        check_cached()
        validate(scene)
        assert len(results)<16
        for path in frozen:
            assert hashlib.sha256(path.read_bytes()).hexdigest()==frozen_hashes[str(path.relative_to(ROOT.parent))], path
        policy,state=(Q4Symmetric25Policy,Q4JointCoverageInformationState) if name=='joint25' else (Q4DirectionalPolicy,Q4InformationState)
        trace=output/'actions'/(scene.name+'_'+name+'.jsonl')
        result=run_case(scene,name,trace,config=Q4Config(),policy_factory=policy,state_factory=state)
        result['search_stage']=stage
        rows=[json.loads(line) for line in trace.read_text(encoding='utf-8').splitlines()]
        first=next((r for r in rows if 'fallback' in r['reason']),None)
        result['first_fallback_step']=first['step'] if first else None
        result['first_fallback_after_s']=first['response']['virtual_time_s'] if first else None
        result['trace_sha256']=hashlib.sha256(trace.read_bytes()).hexdigest()
        results.append(result)
        dump(output/'results.json',results)
        print(json.dumps({k:result[k] for k in ('case','policy','search_stage','success','virtual_time_s',
                                               'average_localization_clear_s','failed_clears','fallback',
                                               'first_fallback_step','wall_time_s')},ensure_ascii=False),flush=True)
        if not result['success']:
            dump(output/'FAILURE.json',result)
            raise SystemExit(3 if result['error'] and 'ASTRA_STOP' in result['error'] else 2)
        return result

    for scene,meta in initial:
        execute(scene,'joint25','initial')
    selected=rank(results)[:2]
    selection=dict(primary_metric='average_localization_clear_s',parents=[r['case'] for r in selected],
                   initial_order_per_source=[r['case'] for r in rank(results)],
                   initial_order_total_time=[r['case'] for r in rank(results,'virtual_time_s')])
    dump(output/'selection.json',selection)
    for parent_index,row in enumerate(selected):
        for k,kind in enumerate(('rigid_rotation','orientation_jitter','channel_permutation')):
            scene,meta=perturb(scenes[row['case']],kind,parent_index*3+k)
            scenes[scene.name]=scene
            provenance[scene.name]=meta
            dump(output/'cases.json',[s.to_dict() for s in scenes.values()])
            dump(output/'provenance.json',provenance)
            execute(scene,'joint25','perturbation')
    joint=[r for r in results if r['policy']=='joint25']
    worst=rank(joint)[:2]
    dump(output/'worst_selected_for_baseline.json',[r['case'] for r in worst])
    for row in worst:
        execute(scenes[row['case']],'directional','worst_pair_baseline')
    pairs=[]
    for row in worst:
        base=next(r for r in results if r['case']==row['case'] and r['policy']=='directional')
        pairs.append(dict(case=row['case'],source_count=row['source_count'],
                          joint_per_source_s=row['average_localization_clear_s'],
                          baseline_per_source_s=base['average_localization_clear_s'],
                          joint_total_s=row['virtual_time_s'],baseline_total_s=base['virtual_time_s'],
                          joint_fallback=row['fallback'],baseline_fallback=base['fallback']))
    dump(output/'summary.json',dict(primary_metric='per-source time; only full-clear runs ranked',
        complete_runs=len(results),joint_runs=len(joint),all_success=all(r['success'] for r in results),
        fallback_joint_count=sum(r['fallback'] for r in joint),
        order_per_source=[dict(case=r['case'],per_source_s=r['average_localization_clear_s'],total_s=r['virtual_time_s']) for r in rank(joint)],
        order_total_time=[dict(case=r['case'],per_source_s=r['average_localization_clear_s'],total_s=r['virtual_time_s']) for r in rank(joint,'virtual_time_s')],
        baseline_pairs=pairs))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    main(args.output)
