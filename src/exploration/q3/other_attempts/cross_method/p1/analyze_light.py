"""只审计已完成轨迹；指标与筛选门槛按冻结设计计算。"""
import argparse
import collections
import hashlib
import json
import math
import statistics as st
from pathlib import Path
from analyze_results import audit,different,clearance_segments
from light_run import ROOT,read,check,a


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def stops_and_search(rows,extra):
    stops=[]
    for row in rows:
        if not stops or math.dist(stops[-1]['position'],row['position'])>1e-7:
            stops.append(dict(position=row['position'],rows=[]))
        stops[-1]['rows'].append(row)
    for stop in stops:
        rr=stop.pop('rows');stop['start']=rr[0]['step'];stop['end']=rr[-1]['step']
        stop['unknown_measures']=sum(r['kind']=='measure' and r['before']['selected_channel']['status']=='unknown' for r in rr)
        stop['discovered']=any(r['kind']=='measure' and r['before']['selected_channel']['status']=='unknown'
            and r['after']['selected_channel']['status']=='found' for r in rr)
        service=any(r['kind']=='clear' or (r['kind']=='measure' and r['before']['selected_channel']['status']=='found') for r in rr)
        initial=any(r.get('phase')=='initial' for r in rr)
        stop['type']='initial' if initial else 'service' if service else 'discovery' if stop['discovered'] else 'pure_scan'
        stop['travel_in_m']=sum(r['independent_costs']['move_s']*5 for r in rr)
    # 事后服务含新发现站；单独保存发现转换，避免把它当成无效纯扫描。
    service_indices=[i for i,s in enumerate(stops) if s['type'] in ('service','discovery')]
    detours=[]
    for i,j in zip(service_indices,service_indices[1:]):
        pure=[s for s in stops[i+1:j] if s['type']=='pure_scan']
        if not pure:continue
        actual=sum(s['travel_in_m'] for s in stops[i+1:j+1])
        detours.append(dict(from_step=stops[i]['end'],to_step=stops[j]['start'],
            pure_stops=len(pure),extra_m=actual-math.dist(stops[i]['position'],stops[j]['position'])))
    last=service_indices[-1] if service_indices else -1
    search=[r for r in rows if r.get('phase')!='initial' and r['before']['counts']['found']==0
            and r['before']['counts']['unknown']>0]
    last_clear=extra['last_clear_s']
    intermediate=[r for r in search if last_clear is not None and r['response']['virtual_time_s']<=last_clear+1e-7]
    return dict(stops=stops,pure_scan_stops=sum(s['type']=='pure_scan' for s in stops),
        discovery_stops=sum(s['type']=='discovery' for s in stops),
        service_unknown_measures=sum(s['unknown_measures'] for s in stops if s['type']=='service'),
        search_without_found_s=sum(sum(r['independent_costs'].values()) for r in search),
        intermediate_search_s=sum(sum(r['independent_costs'].values()) for r in intermediate),
        between_service_scan_detour_m=sum(d['extra_m'] for d in detours),detours=detours,
        open_end_travel_m=sum(s['travel_in_m'] for s in stops[last+1:]))


def main():
    p=argparse.ArgumentParser();p.add_argument('run',type=Path);args=p.parse_args();run=args.run.resolve()
    manifest,cases,receipt=check();frozen=read(run/'manifest.json')
    assert frozen['baseline_manifest']==manifest
    assert read(run/'cases.json')==cases
    for rel,digest in frozen['code_hashes'].items():assert sha(ROOT/rel)==digest,rel
    assert read(run/'completion.json')['finished']==24
    items={v['name']:v for v in manifest['cases']};data={};source_hashes={};actions=0
    for case in cases:
        name=case['name'];data[name]={}
        for mode in ('F3','A','B','AB'):
            directory=(ROOT/items[name]['baseline_result']).parent if mode=='F3' else run/mode/name
            result,rows,extra=audit(case,directory);actions+=len(rows)
            meta=read(directory/'metadata.json')
            data[name][mode]=dict(result=result,extra=extra,diagnostics=stops_and_search(rows,extra),
                segments=clearance_segments(rows),rows=rows,decisions=meta['refinement_decisions'],
                fallback_counts=dict(collections.Counter(d['fallback'] for d in meta['refinement_decisions'] if 'fallback' in d)))
            if mode!='F3':data[name][mode]['lightweight']=meta['lightweight']
            for fn in ('result.json','metadata.json','actions.jsonl'):source_hashes[(directory/fn).relative_to(ROOT).as_posix()]=sha(directory/fn)
    groups={};keys=('total_s','per_source_s','move_s','measure_s','switch_s','success_clear_s','fail_clear_s')
    for mode in ('A','B','AB'):
        pairs=[]
        for case in cases:
            name=case['name'];old,new=data[name]['F3'],data[name][mode]
            first=next((i for i,(x,y) in enumerate(zip(old['rows'],new['rows'])) if different(x,y)),None)
            divergence=None if first is None else dict(step=first+1,old=old['rows'][first],new=new['rows'][first])
            pair=dict(case=name,n=len(case['sources']),first_divergence=divergence)
            if first is not None:
                pair['first_divergence_decisions']={label:next((d for d in obj['decisions'] if d['at_action']==first),None) for label,obj in [('F3',old),(mode,new)]}
                pair['first_divergence_route_plans']=[p for p in new['lightweight']['online_plans'] if p['at_action']==first]
            if old['result']['success'] and new['result']['success']:
                pair['saving']={k:old['result'][k]-new['result'][k] for k in keys}
            pairs.append(pair)
        complete=all('saving' in x for x in pairs)
        summary=dict(all_clear=complete,screening_pass=False)
        if complete:
            means={k:st.mean(x['saving'][k] for x in pairs) for k in keys}
            loo={k:min(st.mean(x['saving'][k] for j,x in enumerate(pairs) if j!=i) for i in range(8)) for k in ('total_s','per_source_s')}
            summary.update(mean_saving=means,leave_one_out_min=loo,
                mean_min=st.mean(data[c['name']][mode]['result']['total_s']/60 for c in cases),
                per_source_min=st.mean(data[c['name']][mode]['result']['per_source_s']/60 for c in cases),
                wins=sum(x['saving']['total_s']>1e-6 for x in pairs),losses=sum(x['saving']['total_s']<-1e-6 for x in pairs),
                ties=sum(abs(x['saving']['total_s'])<=1e-6 for x in pairs),
                worst_regression_s=max(0,-min(x['saving']['total_s'] for x in pairs)),
                screening_pass=means['total_s']>=30 and means['per_source_s']>0 and means['move_s']>0 and min(loo.values())>0)
        groups[mode]=dict(summary=summary,pairs=pairs)
    metrics={}
    for mode in ('F3','A','B','AB'):
        vals=[data[c['name']][mode] for c in cases]
        metrics[mode]=dict(mean_min=st.mean(v['result']['total_s']/60 for v in vals),
            all_clear=sum(v['result']['success'] for v in vals),
            mean_tail_s=st.mean(v['extra']['tail_s'] for v in vals) if all(v['extra']['tail_s'] is not None for v in vals) else None,
            mean_unknown_measures=st.mean(v['extra']['unknown_scan_count'] for v in vals),
            **{'mean_'+k:st.mean(v['diagnostics'][k] for v in vals) for k in ('pure_scan_stops','discovery_stops','service_unknown_measures',
                'intermediate_search_s','search_without_found_s','between_service_scan_detour_m','open_end_travel_m')})
        if mode!='F3':
            metrics[mode].update(mean_accounted_wall_s=st.mean(v['result']['accounted_wall_s'] for v in vals),
                max_accounted_wall_s=max(v['result']['accounted_wall_s'] for v in vals),
                rollout_calls=sum(v['lightweight']['rollout_calls'] for v in vals),
                counts={scope:dict(sum((collections.Counter(v['lightweight']['counts'][scope]) for v in vals),collections.Counter())) for scope in ('online','rollout')})
    interaction={}
    if all(g['summary']['all_clear'] for g in groups.values()):
        interaction={m:st.mean(data[c['name']][m]['result']['total_s']-data[c['name']]['AB']['result']['total_s'] for c in cases) for m in ('A','B')}
    for v in data.values():
        for d in v.values():d.pop('rows');d.pop('decisions')
    report=dict(groups=groups,metrics=metrics,AB_saving_vs_single_s=interaction,data=data,source_hashes=source_hashes,
        validation=dict(trajectories=32,actions=actions,feedback_cost_geometry_replay_passed=True,model_hashes_unchanged=True,
            baseline_check=receipt),analysis_sha256=sha(Path(__file__)))
    a.base.dump(run/'analysis.json',report)
    lines=['# P1轻量第二轮固定八例结果','',
        '用户批准的A（少设站）、B（少绕路）、AB（先A后B）各8例，复用同案冻结F3。所有结果来自本地开发案例。','',
        '| 组别 | 全清 | 平均整局/分钟 | 每源/分钟 | 胜/负/平 | 平均节省/秒 | 筛选 |','| --- | ---: | ---: | ---: | --- | ---: | --- |',
        f"| F3 | 8/8 | {metrics['F3']['mean_min']:.3f} | {st.mean(data[c['name']]['F3']['result']['per_source_s']/60 for c in cases):.3f} | — | — | 基准 |"]
    for mode,g in groups.items():
        s=g['summary']
        if s['all_clear']:lines.append(f"| {mode} | 8/8 | {s['mean_min']:.3f} | {s['per_source_min']:.3f} | {s['wins']}/{s['losses']}/{s['ties']} | {s['mean_saving']['total_s']:+.3f} | {'通过' if s['screening_pass'] else '未通过'} |")
        else:lines.append(f"| {mode} | {metrics[mode]['all_clear']}/8 | 不作成功子集排名 | — | — | — | 未通过 |")
    lines+=['','正数表示F3减候选，即候选节省；每源指标为每局T/N后等权平均。','',
        '| 案例 | F3/分钟 | A节省/分钟 | B节省/分钟 | AB节省/分钟 |','| --- | ---: | ---: | ---: | ---: |']
    for i,c in enumerate(cases):
        values=[f"{groups[m]['pairs'][i]['saving']['total_s']/60:+.3f}" if 'saving' in groups[m]['pairs'][i] else '失败' for m in ('A','B','AB')]
        lines.append(f"| {c['name']} | {data[c['name']]['F3']['result']['total_s']/60:.3f} | "+' | '.join(values)+' |')
    lines+=['','## 费用与查漏诊断','', '| 指标（每局均值） | F3 | A | B | AB |','| --- | ---: | ---: | ---: | ---: |']
    for k,label in [('mean_tail_s','最后清除后尾段/秒'),('mean_intermediate_search_s','中途无已发现待清源的排查/秒'),
        ('mean_unknown_measures','未知频道检测/次'),('mean_pure_scan_stops','纯扫描停点/个'),('mean_service_unknown_measures','服务点附带未知扫描/次'),
        ('mean_between_service_scan_detour_m','服务点间纯扫描额外路程/米'),('mean_open_end_travel_m','最后服务点后开放路程/米')]:
        lines.append('| '+label+' | '+' | '.join(f'{metrics[m][k]:.3f}' if metrics[m][k] is not None else '不可用' for m in ('F3','A','B','AB'))+' |')
    lines+=['','同位置连续操作合并为停点；有实际清除或对已发现源检测视为服务。仅由未知变已发现的停点单列为发现站，并作为服务链端点。开局排除在专门扫描和中途排查之外。相邻服务点直线差只用于事后定位绕路，不能视为可全部省去的费用；开放尾段不虚构返程。尾段、排查与移动费用重叠，不相加。','']
    for mode,g in groups.items():
        s=g['summary'];mm=metrics[mode]
        lines += [f'## {mode}的归因与门槛','',f"在线计划算子统计：`{mm['counts']['online']}`；内部预演统计：`{mm['counts']['rollout']}`。这些是计划修改次数，不是实际取消站数，预计收益不能累加成整局收益。",
            f"现实用时（含缓存开局历史费用）均值{mm['mean_accounted_wall_s']:.1f}秒，最大{mm['max_accounted_wall_s']:.1f}秒；内部场景模拟共{mm['rollout_calls']}次。",
            '逐例原F3回退/本组回退：'+str({c['name']:{'F3':data[c['name']]['F3']['fallback_counts'],mode:data[c['name']][mode]['fallback_counts']} for c in cases})]
        if s['all_clear']:
            lines += [f"平均费用节省/秒：`{s['mean_saving']}`。",
                f"删除任意一例后的最小平均节省/秒：`{s['leave_one_out_min']}`；最大退步{s['worst_regression_s']/60:.3f}分钟。"]
        for pair in g['pairs']:
            if 'saving' in pair and pair['saving']['total_s']>-60:continue
            name=pair['case'];d=pair['first_divergence'];old,new=data[name]['F3'],data[name][mode]
            lines += ['',f"### 分钟级退步复查：{name}"]
            if 'saving' in pair:lines += [f"费用变化（本组减F3，正数为多耗）：整局{-pair['saving']['total_s']/60:+.3f}分钟，移动{-pair['saving']['move_s']/60:+.3f}分钟，检测{-pair['saving']['measure_s']/60:+.3f}分钟。"]
            if d:lines += [f"首次分歧第{d['step']}步：F3到{d['old']['position']}操作频道{d['old']['channel']}（{d['old']['reason']}），本组到{d['new']['position']}操作频道{d['new']['channel']}（{d['new']['reason']}）。"]
            same=[x['channel'] for x in old['segments']]==[x['channel'] for x in new['segments']]
            lines += [f"成功清除顺序{'相同' if same else '不同'}；F3/本组最后清除后尾段{old['extra']['tail_s']:.3f}/{new['extra']['tail_s']:.3f}秒。"]
            if same:
                worst=sorted(zip(old['segments'],new['segments']),key=lambda x:x[1]['move_s']-x[0]['move_s'],reverse=True)[:2]
                for os,ns in worst:lines += [f"到频道{ns['channel']}的清除区间：F3/本组移动{os['move_s']:.3f}/{ns['move_s']:.3f}秒。"]
            lines += ['具体移动链见analysis.json的segments及各组actions.jsonl；首次分歧不能独自解释其后所有损失。']
    lines+=['','## 核验与边界','',f'6项接口检查通过；32条轨迹共{actions}个动作独立重算计费、重放环境反馈、检查状态几何。运行前后源码与输入指纹一致。AI核验，未声称人工复核。',
        f'AB相对单项的平均节省/秒：`{interaction}`。',
        '原F3四场景非递归预演机制仍保留，A/B同时用于实际规划和原预演里的路线。固定8例是开发筛选，不能外推到独立案例或官方测试。本轮未增参数、未按中途结果调规则。','',
        '各组最好/最差案例实际路线：[A](routes_A.png)、[B](routes_B.png)、[AB](routes_AB.png)。','']
    (run/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(dict(groups={k:v['summary'] for k,v in groups.items()},metrics=metrics,validation=report['validation']),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
