"""逐动作审查；真实位置只在事后标注中使用，不返回给策略。"""
import argparse
import copy
import json
import math
from pathlib import Path

from refined import RefinedPolicy, dominated_negative, clearing_plans
from posterior import a, g


def inspect(directory,case):
    directory=Path(directory)
    actions=[json.loads(s) for s in (directory/'actions.jsonl').read_text().splitlines()]
    sources={s.channel:s for s in case.sources}
    s=a.CoverageInformationState()
    rows=[];stops=[];states={}
    for action in actions:
        i=action['step'];j=action['channel'];c=s.channels[j]
        q=tuple(action['position'])
        row={'step':i,'kind':action['kind'],'channel':j,'position':q,'reason':action['reason'],
             'cost_s':sum(action['independent_costs'].values()),'flags':[]}
        old_area=g.area(c.support()) if c.status=='found' else None
        row['before_radius_m']=c.circle()[1] if c.status=='found' else None
        if not stops or stops[-1]['position']!=q:
            stops.append({'position':q,'first_step':i,'actions':[], 'unknown_detectable_at_arrival':[
               k for k,src in sources.items() if s.channels[k].status=='unknown' and math.dist(q,src.position)<=src.radius]})
        prior=[p for p,_,_ in c.observations]
        row['nearest_previous_same_channel_m']=min((math.dist(q,p) for p in prior),default=None)
        if action['kind']=='measure':
            proof=dominated_negative(c,q)
            if proof:row['flags'].append('provably_redundant_no_signal')
            if c.status=='found' and c.circle()[1]>20:
                plans=clearing_plans(s,c)
                row['certified_clear_options']=[{'id':p['id'],'worst_local_s':p['worst_local_s']} for p in plans]
        s.update(action,action['response'])
        after=s.channels[j]
        row['response']=action['response'].get('measure_result',action['response'].get('clear_result'))
        row['after_radius_m']=after.circle()[1] if after.status=='found' else None
        if old_area is not None and after.status=='found':
            new_area=g.area(after.support())
            row['area_reduction_fraction']=1-new_area/old_area if old_area else None
            if abs(old_area-new_area)<1e-6 and action['kind']=='measure':
                row['flags'].append('no_geometric_reduction_observed')
        if action['kind']=='measure' and old_area is None and after.status=='found':
            row['flags'].append('new_source')
        row['known_found']=sorted(k for k,c in s.channels.items() if c.status=='found')
        row['cleared']=sorted(k for k,c in s.channels.items() if c.status=='cleared')
        rows.append(row);stops[-1]['actions'].append(i)
    for stop in stops:
        scans={r['channel'] for r in rows if r['step'] in stop['actions'] and r['kind']=='measure'}
        stop['detectable_unknown_not_scanned']=sorted(set(stop['unknown_detectable_at_arrival'])-scans)
    result={'case':case.name,'steps':rows,'stops':stops,'diagnostic_truth_only':True}
    a.base.dump(directory/'trace_audit.json',result)
    return result


def counterfactual(directory,case):
    """原候选与替代动作后都接F1；这是事后诊断，不是部署策略的实际后续。"""
    directory=Path(directory)
    metadata=json.loads((directory/'metadata.json').read_text())
    decisions={d['at_action']:d for d in metadata.get('refinement_decisions',[]) if 'original_action' in d and 'options' in d}
    actions=[json.loads(x) for x in (directory/'actions.jsonl').read_text().splitlines()]
    state=a.CoverageInformationState();tried=set();results=[]
    for action in actions:
        d=decisions.get(state.actions)
        if d:
            p=RefinedPolicy(metadata.get('selected_second'),level=1)
            p.initial_index=2;p.phase='service';p.tried_centers=set(tried)
            original=d['original_action'];reason=original['reason'];j=original['channel']
            p.pending_scan_unknown=d['scan_unknown']
            if original['kind']=='measure' and reason!='current_view':
                p.start_station(state,tuple(original['position']),reason,priority=j,scan_unknown=d['scan_unknown'])
                if j in p.station_channels:p.station_channels.remove(j)
            elif original['kind']=='clear':
                p.tried_centers.add(j)
                p.after_arrival_scan=(tuple(original['position']),d['scan_unknown'],j)
            remaining=tuple(src for src in case.sources if state.channels[src.channel].status!='cleared')
            world=a.Scenario(case.name,case.seed,case.layout,case.noise,remaining)
            values=[]
            for option in d['options']:
                try:cost=p.simulate(state,world,option,original);error=None
                except Exception as exc:cost=None;error=str(exc)
                values.append({'id':option['id'],'predicted_s':option['mean_s'],'actual_common_f1_s':cost,'error':error})
            if all(v['actual_common_f1_s'] is not None for v in values):
                best=min(values,key=lambda v:v['actual_common_f1_s'])
                chosen=next(v for v in values if v['id']==d['chosen'])
                results.append({'at_action':state.actions,'channel':j,'chosen':d['chosen'],'best_hindsight':best['id'],
                                'regret_s':chosen['actual_common_f1_s']-best['actual_common_f1_s'],
                                'chosen_vs_original_saving':values[0]['actual_common_f1_s']-chosen['actual_common_f1_s'],'options':values})
        if action['reason']=='single_center_try':tried.add(action['channel'])
        state.update(action,action['response'])
    a.base.dump(directory/'counterfactual_audit.json',{'case':case.name,'scope':'same_state_common_F1_hindsight_only','decisions':results})
    return results


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory');parser.add_argument('case_file');parser.add_argument('--counterfactual',action='store_true')
    args=parser.parse_args();data=json.loads(Path(args.case_file).read_text())
    if isinstance(data,list):data=next(c for c in data if c['name']==Path(args.directory).parent.name)
    case=a.Scenario.from_dict(data)
    result=inspect(args.directory,case)
    print(json.dumps({'case':case.name,'steps':len(result['steps']),'stops':len(result['stops']),
         'provable_redundancy':[r['step'] for r in result['steps'] if 'provably_redundant_no_signal' in r['flags']],
         'missed_opportunities':[{k:s[k] for k in ('first_step','detectable_unknown_not_scanned')} for s in result['stops'] if s['detectable_unknown_not_scanned']]},ensure_ascii=False))
    if args.counterfactual:
        result=counterfactual(args.directory,case)
        print(json.dumps(sorted(result,key=lambda d:-d['regret_s'])[:5],ensure_ascii=False))
