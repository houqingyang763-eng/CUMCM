"""只重放既有动作与重算配对结果，不调用任何策略。"""
import argparse
import collections
import hashlib
import json
import math
import statistics
from pathlib import Path

from p1_run import load, ROOT, a, sha


def audit(case, directory):
    result = load(directory/'result.json')
    rows = [json.loads(x) for x in (directory/'actions.jsonl').read_text(encoding='utf-8').splitlines()]
    env = a.LocalEnvironment(a.Scenario.from_dict(case))
    state = a.CoverageInformationState()
    position, measuring, total = (0., 0.), 1, 0.
    ledger = dict(move_s=0., measure_s=0., switch_s=0., success_clear_s=0., fail_clear_s=0.)
    last_clear = None
    for row in rows:
        replay = env.act(row); recorded = row['response']
        for key in ('accepted', 'measure_result', 'svd_deg', 'clear_result'):
            assert replay.get(key) == recorded.get(key), (case['name'], row['step'], key)
        costs = dict.fromkeys(ledger, 0.)
        costs['move_s'] = math.dist(position, row['position'])/5
        if row['kind'] == 'measure':
            costs['measure_s'] = 5.
            costs['switch_s'] = int(measuring != row['channel']); measuring = row['channel']
        else:
            success = row['response']['clear_result'] == 'success'
            costs['success_clear_s' if success else 'fail_clear_s'] = 5. if success else 3.
            if success: last_clear = row['response']['virtual_time_s']
        total += sum(costs.values()); position = tuple(row['position'])
        assert abs(total-recorded['virtual_time_s']) < 1e-5
        for key, value in costs.items(): ledger[key] += value
        state.update(row, recorded); a.audit_state(state, env)
    assert abs(result['total_s']-total) < 1e-5
    assert all(abs(result[k]-ledger[k]) < 1e-5 for k in ledger)
    if result['success']:
        assert state.complete and len(env.cleared) == len(case['sources'])
        assert abs(result['per_source_s']-total/len(case['sources'])) < 1e-5
    unknown = [r for r in rows if r['kind']=='measure' and r['before']['selected_channel']['status']=='unknown']
    extra = dict(action_count=len(rows), tail_s=total-last_clear if last_clear is not None else None,
                 last_clear_s=last_clear, unknown_scan_count=len(unknown),
                 pre_last_clear_unknown_scan_count=sum(r['response']['virtual_time_s'] <= last_clear for r in unknown) if last_clear is not None else None,
                 all_clear_replayed=state.complete and len(env.cleared)==len(case['sources']))
    return result, rows, extra


def different(x, y):
    return x['kind'] != y['kind'] or x['channel'] != y['channel'] or math.dist(x['position'],y['position']) > 1e-6


def clearance_segments(rows):
    segments=[]; start=0
    for i,row in enumerate(rows):
        if row['kind']=='clear' and row['response']['clear_result']=='success':
            part=rows[start:i+1]
            segments.append(dict(channel=row['channel'],start_step=start+1,end_step=i+1,
                move_s=sum(x['independent_costs']['move_s'] for x in part),
                movement_steps=[dict(step=x['step'],position=x['position'],reason=x['reason'],channel=x['channel'])
                                for x in part if x['independent_costs']['move_s']>1 or x['kind']=='clear']))
            start=i+1
    return segments


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('run',type=Path); args=parser.parse_args()
    args.run=args.run.resolve()
    frozen=load(args.run/'manifest.json'); design=frozen['baseline_manifest']
    for path,digest in frozen['code_hashes'].items(): assert sha(ROOT/path)==digest, path
    artifacts=[design['scenario_source'],design['baseline']['config_artifact'],*design['baseline']['runtime_dependencies']]
    for item in design['screening_cases']: artifacts.extend(item['artifacts'].values())
    for item in artifacts: assert sha(ROOT/item['path'])==item['sha256'], item['path']
    cases={c['name']:c for c in load(args.run/'cases.json')}
    for item in design['screening_cases']:
        encoded=json.dumps(cases[item['name']],sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
        assert hashlib.sha256(encoded).hexdigest()==item['case_content_sha256'], item['name']
    pairs=[]; source_hashes={}; checked_actions=0
    for item in design['screening_cases']:
        name=item['name']; original=ROOT/item['artifacts']['f3/result.json']['path']
        oldpath=original.parent; newpath=args.run/name
        old,oldrows,oldextra=audit(cases[name],oldpath)
        new,newrows,newextra=audit(cases[name],newpath)
        checked_actions+=len(oldrows)+len(newrows)
        for p in (oldpath,newpath):
            for filename in ('result.json','metadata.json','actions.jsonl'):
                source_hashes[(p/filename).relative_to(ROOT).as_posix()]=sha(p/filename)
        md=load(newpath/'metadata.json'); decisions=md['refinement_decisions']
        first=next((i for i,(x,y) in enumerate(zip(oldrows,newrows)) if different(x,y)),None)
        divergence=None if first is None else dict(step=first+1,
            old={k:oldrows[first].get(k) for k in ('kind','position','channel','reason')},
            new={k:newrows[first].get(k) for k in ('kind','position','channel','reason','p1_choice')})
        row=dict(case=name,n=item['source_count'],layout=item['layout'],noise=item['noise'],
            baseline=old,candidate=new,baseline_extra=oldextra,candidate_extra=newextra,
            first_divergence=divergence,choice_counts=dict(collections.Counter(d['chosen'] for d in decisions)),
            fallback_counts=dict(collections.Counter(d['fallback'] for d in decisions if 'fallback' in d)),
            rollout_calls=sum(d['rollout_calls'] for d in decisions),
            completed_rollout_actions=sum(d['simulated_actions'] for d in decisions),
            continuation_fallbacks=sum(d.get('continuation_fallbacks',0) for d in decisions),
            max_decision_wall_s=max((d['wall_s'] for d in decisions),default=0))
        row['clearance_segments']={'baseline':clearance_segments(oldrows),'candidate':clearance_segments(newrows)}
        row['same_clearance_order']=([s['channel'] for s in row['clearance_segments']['baseline']]
                                     ==[s['channel'] for s in row['clearance_segments']['candidate']])
        initial_decision=next((d for d in decisions if first is not None and d['at_action']==first),None)
        if initial_decision:
            row['first_divergence_estimate']={k:initial_decision[k] for k in ('chosen','predicted_saving_s')}
            row['first_divergence_estimate']['options']=[{k:o[k] for k in ('id','mean_s','costs_s')}
                                                        for o in initial_decision['options']]
        if old['success'] and new['success']:
            row['saving']={k:old[k]-new[k] for k in ('total_s','per_source_s','move_s','measure_s','switch_s','success_clear_s','fail_clear_s')}
            row['tail_saving_s']=oldextra['tail_s']-newextra['tail_s']
        pairs.append(row)
    complete=all(p['baseline']['success'] and p['candidate']['success'] for p in pairs)
    report=dict(status='complete' if complete else 'contains_failed_cases',pairs=pairs,
        validation=dict(checked_trajectories=len(pairs)*2,checked_actions=checked_actions,
                        feedback_cost_geometry_replay_passed=True,model_hashes_unchanged=True,
                        baseline_artifacts_unchanged=True,checked_frozen_artifacts=len(artifacts),case_hashes_unchanged=True),
        source_hashes=source_hashes,analysis_code_sha256=sha(Path(__file__)))
    if complete:
        avg=lambda key: statistics.mean(p['saving'][key] for p in pairs)
        means={k:avg(k) for k in pairs[0]['saving']}
        loo={key:[statistics.mean(p['saving'][key] for j,p in enumerate(pairs) if j!=i)
                  for i in range(len(pairs))] for key in ('total_s','per_source_s')}
        summary=dict(mean_saving=means,
            baseline_mean_min=statistics.mean(p['baseline']['total_s']/60 for p in pairs),
            candidate_mean_min=statistics.mean(p['candidate']['total_s']/60 for p in pairs),
            baseline_per_source_min=statistics.mean(p['baseline']['per_source_s']/60 for p in pairs),
            candidate_per_source_min=statistics.mean(p['candidate']['per_source_s']/60 for p in pairs),
            wins=sum(p['saving']['total_s']>1e-6 for p in pairs),
            losses=sum(p['saving']['total_s']<-1e-6 for p in pairs),
            ties=sum(abs(p['saving']['total_s'])<=1e-6 for p in pairs),
            worst_regression_s=max(0,-min(p['saving']['total_s'] for p in pairs)),
            leave_one_out=loo,
            candidate_accounted_wall_mean_s=statistics.mean(p['candidate']['accounted_wall_s'] for p in pairs),
            candidate_accounted_wall_max_s=max(p['candidate']['accounted_wall_s'] for p in pairs))
        summary['screening_pass']=(means['total_s']>=30 and means['per_source_s']>0 and means['move_s']>0
                                  and all(min(v)>0 for v in loo.values()))
        report['summary']=summary
        report['by_layout']={layout:dict(cases=sum(p['layout']==layout for p in pairs),
            mean_saving_s=statistics.mean(p['saving']['total_s'] for p in pairs if p['layout']==layout),
            mean_move_saving_s=statistics.mean(p['saving']['move_s'] for p in pairs if p['layout']==layout))
            for layout in sorted({p['layout'] for p in pairs})}
    else:
        report['summary']={'screening_pass':False,'reason':'保留失败，不计算仅成功子集的性能均值'}
    a.base.dump(args.run/'analysis.json',report)
    lines=['# P1 固定八例筛选结果','',
           '用户于2026-09-13授权执行。只测试一个P1候选，复用冻结F3的同案轨迹；全部为本地自建案例。','',
           '**'+('P1通过本轮开发筛选，可作为后续P2候选底座。' if report['summary']['screening_pass'] else 'P1未通过本轮筛选，继续保留F3。')+'**','',
           '| 案例 | 源数 | F3/分钟 | P1/分钟 | 节省/分钟 | P1全清 |',
           '| --- | ---: | ---: | ---: | ---: | --- |']
    for p in pairs:
        saving=f"{p['saving']['total_s']/60:+.3f}" if 'saving' in p else '不计'
        lines.append(f"| {p['case']} | {p['n']} | {p['baseline']['total_s']/60:.3f} | {p['candidate']['total_s']/60:.3f} | {saving} | {'是' if p['candidate']['success'] else '否'} |")
    if complete:
        s=report['summary']; m=s['mean_saving']
        if min(s['leave_one_out']['total_s'])<=0:
            influential=max(pairs,key=lambda p:p['saving']['total_s'])
            lines+=['',f"未通过的具体原因：去掉最大收益例`{influential['case']}`（节省{influential['saving']['total_s']/60:.3f}分钟）后，其余7例平均反而慢{-min(s['leave_one_out']['total_s']):.3f}秒，不满足运行前规定的逐例删除稳健性条件。"]
        lines+=['',f"平均整局：F3 {s['baseline_mean_min']:.3f}分钟，P1 {s['candidate_mean_min']:.3f}分钟；节省{m['total_s']/60:+.3f}分钟。",
                f"每局T/N再等权平均：F3 {s['baseline_per_source_min']:.3f}分钟/源，P1 {s['candidate_per_source_min']:.3f}分钟/源。",
                f"胜/负/平={s['wins']}/{s['losses']}/{s['ties']}；最大退步{s['worst_regression_s']/60:.3f}分钟。",'',
                '| 费用分项 | 平均节省/秒（正为P1更快） |','| --- | ---: |']
        for k,label in [('move_s','移动'),('measure_s','检测'),('switch_s','切频'),('success_clear_s','成功清除'),('fail_clear_s','失败清除')]:
            lines.append(f'| {label} | {m[k]:+.3f} |')
        lines+=['',f"P1现实用时含历史开局选择费用：平均{s['candidate_accounted_wall_mean_s']:.1f}秒，最大{s['candidate_accounted_wall_max_s']:.1f}秒。旧F3墙钟属于历史运行，不作同机同期速度配对。",
                f"删去任一例后的最小平均节省：整局{min(s['leave_one_out']['total_s']):+.3f}秒；每源{min(s['leave_one_out']['per_source_s']):+.3f}秒。此检查不是统计置信证明。"]
        lines+=['','| 布局（各2例） | 平均整局节省/分钟 | 平均移动节省/分钟 |','| --- | ---: | ---: |']
        for layout,v in report['by_layout'].items():
            lines.append(f"| {layout} | {v['mean_saving_s']/60:+.3f} | {v['mean_move_saving_s']/60:+.3f} |")
    lines+=['','## 分歧与整局路线复盘','',
            '最后一次成功清除后的尾段与移动等费用交叉重叠，不相加。下列所有案例均保留首次分歧；分钟级退步结合路线图和逐动作日志复核。','',
            '| 案例 | 首次分歧动作 | F3尾段/分钟 | P1尾段/分钟 | 联合提案入选次数 | 回退次数 |',
            '| --- | ---: | ---: | ---: | ---: | ---: |']
    diagnostics=[]
    for p in pairs:
        oldtail=p['baseline_extra']['tail_s']; newtail=p['candidate_extra']['tail_s']
        fmt=lambda v:'无清除' if v is None else f'{v/60:.3f}'
        lines.append(f"| {p['case']} | {p['first_divergence']['step'] if p['first_divergence'] else '无'} | {fmt(oldtail)} | {fmt(newtail)} | {p['choice_counts'].get('channel_joint',0)} | {sum(p['fallback_counts'].values())} |")
        if p['first_divergence'] and ('saving' not in p or p['saving']['total_s']<=-60):
            d=p['first_divergence']
            diagnostics+=['',f"{p['case']}：首次分歧在第{d['step']}步；F3 `{d['old']}`，P1 `{d['new']}`。",'']
    lines+=diagnostics+['','详细退步复盘见[ROUTE_REVIEW.md](ROUTE_REVIEW.md)，全八例路线见[paired_routes.png](paired_routes.png)，最坏案例绕路对比见[worst_routes.png](worst_routes.png)。','', '## 核验与解释边界','',
        f"11项接口检查通过；本批{len(pairs)*2}条新旧动作轨迹共{checked_actions}个动作已独立重算费用、重放环境反馈并逐步检查保守状态。运行源码哈希保持不变。均为AI核验，未声称团队人工复核。",
        'P1同时改变任务表达、逐频道安排及未来非递归续行，收益或退步归于整个组合。未来关闭四场景比较，改按名义完整任务路线选行动，仍是近似。',
        '固定8例属于开发筛选，不是新的独立确认，不外推到官方隐藏测试；本轮没有运行P2/P3、额外参数组合或官方测试。',
        '逐例结果、所有候选费用、真实任务出口和源码指纹见本目录JSON与动作日志。当前分析器只重放已发生动作，没有重新执行策略。','']
    (args.run/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
    review=['# 分钟级退步案例的真实路线复盘','',
        '按运行前规则复查退步至少60秒的案例。移动时间与查漏尾段交叉重叠，不重复相加。下列仅重放已有轨迹，无策略重跑。','']
    for p in pairs:
        if 'saving' not in p or p['saving']['total_s']>-60: continue
        v=p['saving']; old=p['baseline']; new=p['candidate']; d=p['first_divergence']
        review += [f"## {p['case']}",'',
            f"整局退步{-v['total_s']/60:.3f}分钟；多移动{-v['move_s']/60:.3f}分钟（{-v['move_s']*5/1000:.3f}公里），检测节省{v['measure_s']/60:.3f}分钟，切频节省{v['switch_s']:.0f}秒，失败清除多耗{-v['fail_clear_s']:.0f}秒。",
            f"检测次数由{old['measure_count']}变为{new['measure_count']}，失败清除由{old['fail_clears']}次变为{new['fail_clears']}次。最终清除后尾段分别为{p['baseline_extra']['tail_s']:.3f}/{p['candidate_extra']['tail_s']:.3f}秒（F3/P1）。",
            f"首次动作分歧：第{d['step']}步；F3在{d['old']['position']}操作频道{d['old']['channel']}，P1在{d['new']['position']}操作频道{d['new']['channel']}。" if d else '无共同前缀中的动作分歧。']
        estimate=p.get('first_divergence_estimate')
        if estimate:
            review += [f"该时刻P1选择`{estimate['chosen']}`；四场景预计相对原候选省{estimate['predicted_saving_s']:.3f}秒。实际整局退步还包括后续各次决策，不能全部归因于这一个动作。"]
        review += [f"成功清除频道顺序{'相同' if p['same_clearance_order'] else '不同'}。以下按连续两次成功清除之间的全部移动统计；起始段从原点开始。"]
        if p['same_clearance_order']:
            segments=sorted(zip(p['clearance_segments']['baseline'],p['clearance_segments']['candidate']),key=lambda x:x[1]['move_s']-x[0]['move_s'],reverse=True)[:3]
            review += ['', '| 到达并清除的频道 | F3移动/秒 | P1移动/秒 | 多耗/秒 |','| --- | ---: | ---: | ---: |']
            for oldseg,newseg in segments:
                review.append(f"| {newseg['channel']} | {oldseg['move_s']:.3f} | {newseg['move_s']:.3f} | {newseg['move_s']-oldseg['move_s']:.3f} |")
        else:
            segments=[(None,s) for s in sorted(p['clearance_segments']['candidate'],key=lambda s:s['move_s'],reverse=True)[:3]]
            review += ['清除顺序不同，不能将同频道前的区间直接视为同段对照；仅列P1最长的三段用于定位绕路。']
        for oldseg,newseg in segments:
            review += ['',f"到频道{newseg['channel']}的实际移动链：",'']
            for label,seg in [('F3',oldseg),('P1',newseg)]:
                if seg:
                    chain=' → '.join(f"第{x['step']}步({x['position'][0]:.0f},{x['position'][1]:.0f}) {x['reason']}" for x in seg['movement_steps'])
                    review += [f'- {label}：{chain}。']
        review += ['', '判断：减少检测没有自动转化为整局节省，新增移动抵消了操作收益。日志支持费用与路径层面的定位；没有组件消融，不能将损失单独归因于某一个小方法。','']
    (args.run/'ROUTE_REVIEW.md').write_text('\n'.join(review),encoding='utf-8')
    print(json.dumps(report['summary'],ensure_ascii=False,indent=2))


if __name__=='__main__': main()
