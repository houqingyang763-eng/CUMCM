"""只审计既有轨迹：R=A加内移，以冻结A为主对照，F3旁列。"""
import argparse
import collections
import hashlib
import json
import math
import statistics as st
from pathlib import Path

from analyze_results import audit, different, clearance_segments
from analyze_light import stops_and_search
from light_run import ROOT, read, check, a

KEYS = ('total_s', 'per_source_s', 'move_s', 'measure_s', 'switch_s',
        'success_clear_s', 'fail_clear_s')
LONG_TAILS = ('cluster_biased_320115', 'line_smooth_320118', 'line_biased_320121')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(run):
    manifest, cases, receipt = check()
    frozen = read(run/'manifest.json')
    assert frozen['baseline_manifest'] == manifest
    assert read(run/'cases.json') == cases
    prior = ROOT/frozen['prior_run']
    assert read(prior/'manifest.json') == frozen['prior_freeze']
    assert read(prior/'cases.json') == cases
    assert frozen['prior_freeze']['baseline_manifest'] == manifest
    for freeze in (frozen, frozen['prior_freeze']):
        for rel, digest in freeze['code_hashes'].items():
            assert sha(ROOT/rel) == digest, rel
    old_analysis = read(prior/'analysis.json')
    checked_a = 0
    for case in cases:
        for fn in ('result.json', 'metadata.json', 'actions.jsonl'):
            path = prior/'A'/case['name']/fn
            rel = path.relative_to(ROOT).as_posix()
            assert rel in old_analysis['source_hashes'], rel
            assert sha(path) == old_analysis['source_hashes'][rel], rel
            checked_a += 1
    probe_path = next(ROOT/p for p in frozen['code_hashes'] if p.endswith('/probe.json'))
    probe = read(probe_path)
    assert probe['gate']
    for mapping in ('code_hashes', 'source_hashes'):
        for rel, digest in probe[mapping].items():
            assert sha(ROOT/rel) == digest, rel
    completion = read(run/'completion.json')
    assert completion['finished'] == len(cases) == 8
    receipt = dict(receipt, prior_A_artifacts=checked_a,
                   prior_freeze_equal=True, prior_A_hashes_unchanged=True,
                   probe_hashes_unchanged=True, new_code_hashes_unchanged=True,
                   completion=completion)
    return frozen, cases, prior, receipt


def compact(row):
    if row is None:
        return None
    return dict(step=row['step'], kind=row['kind'], channel=row['channel'],
                position=row['position'], reason=row.get('reason'),
                phase=row.get('phase'), before_counts=row['before']['counts'])


def divergence(old, new):
    index = next((i for i, (x, y) in enumerate(zip(old, new)) if different(x, y)), None)
    if index is None and len(old) != len(new):
        index = min(len(old), len(new))
    if index is None:
        return None
    return dict(step=index+1,
                old=compact(old[index]) if index < len(old) else None,
                new=compact(new[index]) if index < len(new) else None,
                common_prefix_actions=index)


def relocation_diagnostics(meta, rows):
    item = meta['relocation']
    records = []
    by_step = {r['step']: r for r in rows}
    for plan in item['online_plans']:
        before, after = plan['before_route'], plan['after_route']
        assert len(before) == len(after)
        assert all({k: v for k, v in x.items() if k != 'position'} ==
                   {k: v for k, v in y.items() if k != 'position'}
                   for x, y in zip(before, after))
        assert plan['after_m'] <= plan['before_m']+1e-6
        next_row = by_step.get(plan['at_action']+1)
        if next_row is not None:
            counts = next_row['before']['counts']
            assert counts['found'] == 0 and counts['unknown'] > 0
            assert math.dist(plan['position'], next_row['before']['position']) < 1e-6
        moved = math.dist(before[0]['position'], after[0]['position']) if before else 0.
        match = bool(next_row is not None and after and
                     math.dist(next_row['position'], after[0]['position']) < 1e-6)
        first_leg_saving = ((math.dist(plan['position'], before[0]['position']) -
                            math.dist(plan['position'], after[0]['position']))/5 if before else 0.)
        records.append(dict(at_action=plan['at_action'], accepted_events=len(plan['events']),
            first_station_displacement_m=moved, first_leg_plan_saving_s=first_leg_saving,
            nominal_route_saving_s=plan['nominal_saving_s'],
            first_station_before=before[0]['position'] if before else None,
            first_station_after=after[0]['position'] if after else None,
            next_actual_action=compact(next_row), next_actual_position_matches=match,
            moved_first_station_executed=bool(moved > 1e-3 and match), events=plan['events']))
    online = item['counts'].get('online', {})
    assert online.get('plans', 0) == len(records)
    assert online.get('accepted', 0) == sum(p['accepted_events'] for p in records)
    moved = [p for p in records if p['first_station_displacement_m'] > 1e-3]
    return dict(bisections=item['bisections'], counts=item['counts'], plans=records,
        moved_first_station_plans=len(moved),
        next_position_match_count=sum(p['next_actual_position_matches'] for p in records),
        moved_first_station_execution_count=sum(p['moved_first_station_executed'] for p in records),
        unique_moved_first_execution_steps=sorted({p['next_actual_action']['step'] for p in records
                                                  if p['moved_first_station_executed']}),
        max_first_station_displacement_m=max((p['first_station_displacement_m'] for p in moved), default=0.),
        mean_moved_first_station_displacement_m=st.mean(p['first_station_displacement_m'] for p in moved) if moved else 0.)


def comparison(pairs, data, baseline):
    complete = all(baseline+'_saving' in p for p in pairs)
    summary = dict(all_clear=complete, screening_pass=False)
    if not complete:
        summary['reason'] = '存在失败例，不计算仅成功子集的性能均值或筛选排名'
        return summary
    values = [p[baseline+'_saving'] for p in pairs]
    means = {k: st.mean(v[k] for v in values) for k in KEYS}
    loo = {k: [dict(omitted=pairs[i]['case'], mean_saving_s=st.mean(v[k] for j, v in enumerate(values) if j != i))
               for i in range(len(pairs))] for k in ('total_s', 'per_source_s')}
    minima = {k: min(v['mean_saving_s'] for v in vv) for k, vv in loo.items()}
    thresholds = dict(all_clear=True, mean_total_at_least_30_s=means['total_s'] >= 30,
        mean_per_source_positive=means['per_source_s'] > 0, mean_movement_positive=means['move_s'] > 0,
        leave_one_out_total_positive=minima['total_s'] > 0,
        leave_one_out_per_source_positive=minima['per_source_s'] > 0)
    worst = min(pairs, key=lambda p: p[baseline+'_saving']['total_s'])
    summary.update(mean_saving=means, leave_one_out=loo, leave_one_out_min=minima,
        thresholds=thresholds, screening_pass=all(thresholds.values()),
        wins=sum(v['total_s'] > 1e-6 for v in values),
        losses=sum(v['total_s'] < -1e-6 for v in values),
        ties=sum(abs(v['total_s']) <= 1e-6 for v in values),
        worst_case=worst['case'], worst_regression_s=max(0., -worst[baseline+'_saving']['total_s']))
    return summary


def metrics(values):
    result = dict(all_clear=sum(bool(v['result']['success']) for v in values), cases=len(values))
    if result['all_clear'] == len(values):
        result.update(mean_min=st.mean(v['result']['total_s']/60 for v in values),
            per_source_min=st.mean(v['result']['per_source_s']/60 for v in values),
            mean_tail_s=st.mean(v['extra']['tail_s'] for v in values),
            mean_unknown_measures=st.mean(v['extra']['unknown_scan_count'] for v in values),
            **{'mean_'+k: st.mean(v['diagnostics'][k] for v in values)
               for k in ('intermediate_search_s', 'search_without_found_s', 'pure_scan_stops',
                         'between_service_scan_detour_m', 'open_end_travel_m')})
    if all('accounted_wall_s' in v['result'] for v in values):
        result.update(mean_accounted_wall_s=st.mean(v['result']['accounted_wall_s'] for v in values),
                      max_accounted_wall_s=max(v['result']['accounted_wall_s'] for v in values))
    return result


def fmt(value, divisor=1.):
    return '不可用' if value is None else f'{value/divisor:.3f}'


def render(report):
    data, pairs, summaries, mm = report['data'], report['pairs'], report['comparisons'], report['metrics']
    s = summaries['A']
    lines = ['# P1第三轮：扫描站内移的固定八例结果', '',
        '**'+('R通过相对冻结A的开发筛选。' if s['screening_pass'] else 'R未通过相对冻结A的开发筛选。')+'**', '',
        'R=A加一个扫描站内移因素；主要比较R与上一轮冻结A，F3仅作历史参照。8例均为既有本地开发案例。', '',
        '| 方法 | 全清 | 平均整局/分钟 | 每局T/N等权平均/分钟每源 |', '| --- | ---: | ---: | ---: |']
    for mode in ('F3', 'A', 'R'):
        m = mm[mode]
        lines.append(f"| {mode} | {m['all_clear']}/{m['cases']} | {fmt(m.get('mean_min'))} | {fmt(m.get('per_source_min'))} |")
    lines += ['', '| 案例 | 源数 | A/分钟 | R/分钟 | 比A节省/秒 | 比F3节省/秒 | R全清 |',
              '| --- | ---: | ---: | ---: | ---: | ---: | --- |']
    for p in pairs:
        v = data[p['case']]
        lines.append(f"| {p['case']} | {p['n']} | {fmt(v['A']['result']['total_s'],60)} | {fmt(v['R']['result']['total_s'],60)} | {fmt(p.get('A_saving',{}).get('total_s'))} | {fmt(p.get('F3_saving',{}).get('total_s'))} | {'是' if v['R']['result']['success'] else '否'} |")
    lines += ['', '正数表示基准减R，即R更快。失败运行的总秒数仅为停止时已花费用，不作为完成时间进行排名。']
    if s['all_clear']:
        lines += ['', f"相对A平均省{s['mean_saving']['total_s']:.3f}秒；胜/负/平={s['wins']}/{s['losses']}/{s['ties']}，最大退步{s['worst_regression_s']:.3f}秒。",
            f"逐例删除后的最小平均节省：整局{s['leave_one_out_min']['total_s']:.3f}秒，每源{s['leave_one_out_min']['per_source_s']:.3f}秒；此检查不是显著性证明。",
            f"预先冻结门槛：`{s['thresholds']}`。", '', '| 费用分项 | 相对A平均节省/秒 |', '| --- | ---: |']
        for k, label in [('move_s','移动'),('measure_s','检测'),('switch_s','切频'),('success_clear_s','成功清除'),('fail_clear_s','失败清除')]:
            lines.append(f"| {label} | {s['mean_saving'][k]:+.3f} |")
    else:
        lines += ['', s['reason']]
    lines += ['', '## 查漏与真实分歧', '', '| 指标（每局均值） | F3 | A | R |', '| --- | ---: | ---: | ---: |']
    for key, label in [('mean_tail_s','最后清除后尾段/秒'),('mean_intermediate_search_s','中途无已发现待清源的排查/秒'),
        ('mean_search_without_found_s','全部无已发现待清源排查/秒'),('mean_unknown_measures','未知频道检测/次'),
        ('mean_pure_scan_stops','纯扫描停点/个'),('mean_between_service_scan_detour_m','服务点间纯扫描额外路程/米')]:
        lines.append('| '+label+' | '+' | '.join(fmt(mm[m].get(key)) for m in ('F3','A','R'))+' |')
    lines += ['', '尾段与中途查漏可相加得到全部排查时间；它们与移动、检测等费用交叉，不能再次加进整局总账。相邻服务点的直线路程差只是事后诊断，不是全部可取消的费用。', '',
        '| 案例 | A尾段/秒 | R尾段/秒 | 对A首次分歧步骤 | 分歧前found（A/R） | 首站移位计划 | 下一动作匹配移位首站 |',
        '| --- | ---: | ---: | ---: | --- | ---: | ---: |']
    for p in pairs:
        v = data[p['case']]; d = p['first_divergence']; r = v['R']['relocation']
        found = '/'.join(str(d[k]['before_counts']['found']) if d[k] else '结束' for k in ('old','new')) if d else '—'
        lines.append(f"| {p['case']} | {fmt(v['A']['extra']['tail_s'])} | {fmt(v['R']['extra']['tail_s'])} | {d['step'] if d else '无'} | {found} | {r['moved_first_station_plans']} | {r['moved_first_station_execution_count']} |")
    lines += ['', '三条原A长尾的机会检查与实际整局分开列示：', '',
        '| 原A长尾案例 | 旧状态首计划可省/秒 | A实际尾段/秒 | R实际尾段/秒 | 实际尾段节省/秒 | 实际整局节省/秒 |',
        '| --- | ---: | ---: | ---: | ---: | ---: |']
    for item in report['long_tail_comparison']:
        lines.append(f"| {item['case']} | {fmt(item['probe_first_plan_saving_s'])} | {fmt(item['A_tail_s'])} | {fmt(item['R_tail_s'])} | {fmt(item['tail_saving_s'])} | {fmt(item['total_saving_s'])} |")
    lines += ['', '机会检查的省时来自旧A公开状态的条件路线。新R可能更早改变发现、定位、清除及最后清除位置，因此这两列不是同状态反事实；计划省时不等于实际尾段或整局收益。整局变快但尾段增长的案例也保留，不用总均值掩盖。']
    counts = report['relocation_totals']
    lines += ['', '## 计划修改与实际行动的对应', '',
        f"在线规划统计：`{counts['counts']['online']}`；原F1预演内统计：`{counts['counts']['rollout']}`。",
        f"首站确有位移的在线计划{counts['moved_first_station_plans']}次，其中下一真实动作位置匹配新首站{counts['moved_first_station_execution_count']}次。仅是动作对应核查，不等同于相对A净省下这些距离。",
        '每次首站位移、两条路线、下一实际动作及计划名义省时均保存在analysis.json。滚动计划会重复，未累计计划省时来充当实际收益。',
        '同一内移组件也用于既有预演的未来查漏路线，因此可能在真实第一次查漏之前就改变选择；整局差额不能全部归因于实际末尾挪站。',
        f"R现实用时含历史开局选择费用：均值{mm['R']['mean_accounted_wall_s']:.1f}秒，最大{mm['R']['max_accounted_wall_s']:.1f}秒。A/F3为历史运行，不作同机同期墙钟排名。"]
    for p in pairs:
        if 'A_saving' in p and p['A_saving']['total_s'] > -60:
            continue
        v = data[p['case']]; d = p['first_divergence']
        lines += ['', '## 失败或分钟级退步复查：'+p['case'], '']
        if 'A_saving' in p:
            lines.append('R减A费用（正为多耗）：'+str({k: -x for k,x in p['A_saving'].items()})+'。')
        else:
            lines.append('R失败原因：'+str(v['R']['result'].get('failreason'))+'；已保留停止前完整轨迹。')
        if d:
            lines.append(f"首次分歧第{d['step']}步：A `{d['old']}`；R `{d['new']}`。")
        if p['same_clearance_order']:
            worst = sorted(zip(v['A']['segments'], v['R']['segments']), key=lambda x:x[1]['move_s']-x[0]['move_s'], reverse=True)[:3]
            lines.append('成功清除频道顺序相同，以下区间可用于定位额外移动：')
            for old,new in worst:
                lines.append(f"- 到频道{new['channel']}：A/R移动{old['move_s']:.3f}/{new['move_s']:.3f}秒。")
        else:
            lines.append('成功清除顺序不同，不能将同频道之前的路径直接解释为同一区间对照。')
        lines.append('逐段动作链见analysis.json的segments；首处分歧只定位入口，不能独自解释全部后续损失。')
    lines += ['', '## 核验与边界', '',
        f"{report['validation']['trajectories']}条轨迹、{report['validation']['actions']}个动作已重放环境反馈、独立重算计费并检查保守状态几何。新源码、原A源码/轨迹、共享输入、案例与机会检查指纹均核对。",
        '全部为AI核验，未声称团队人工确认；本分析只重放已完成轨迹，没有重新执行策略。参试算法未中途调参或加深预演，没有运行官方测试。固定8例开发筛选不能代替独立确认。',
        '各组原F3回退原因与次数保留在analysis.json；新增回退会单列供复查。', '',
        '[三条长尾的全路线配对](routes_long_tails.png)。黑色源位置仅供事后绘图，未用于策略决策。', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    args = parser.parse_args(); run = args.run.resolve()
    frozen, cases, prior, receipt = validate(run)
    items = {c['name']:c for c in frozen['baseline_manifest']['cases']}
    data, pairs, hashes = {}, [], {}
    action_count = 0
    for case in cases:
        name = case['name']; data[name] = {}; rows_by_mode = {}; metas = {}
        paths = dict(F3=(ROOT/items[name]['baseline_result']).parent, A=prior/'A'/name, R=run/name)
        for mode,path in paths.items():
            result, rows, extra = audit(case,path)
            assert result['case'] == name and result['source_count'] == len(case['sources'])
            action_count += len(rows); rows_by_mode[mode] = rows
            meta = read(path/'metadata.json'); metas[mode] = meta
            data[name][mode] = dict(result=result, extra=extra, diagnostics=stops_and_search(rows,extra),
                segments=clearance_segments(rows), fallback_counts=dict(collections.Counter(
                    d['fallback'] for d in meta['refinement_decisions'] if 'fallback' in d)))
            for fn in ('result.json','metadata.json','actions.jsonl'):
                hashes[(path/fn).relative_to(ROOT).as_posix()] = sha(path/fn)
        data[name]['R']['relocation'] = relocation_diagnostics(metas['R'],rows_by_mode['R'])
        data[name]['R']['lightweight_counts'] = metas['R']['lightweight']['counts']
        d = divergence(rows_by_mode['A'],rows_by_mode['R'])
        pair = dict(case=name,n=len(case['sources']),first_divergence=d,
            first_divergence_vs_F3=divergence(rows_by_mode['F3'],rows_by_mode['R']),
            same_clearance_order=[s['channel'] for s in data[name]['A']['segments']] ==
                                 [s['channel'] for s in data[name]['R']['segments']])
        if d:
            pair['first_divergence_decisions'] = {m:next((x for x in metas[m]['refinement_decisions']
                if x['at_action'] == d['step']-1),None) for m in ('A','R')}
            pair['first_divergence_relocation_plans'] = [p for p in data[name]['R']['relocation']['plans']
                                                       if p['at_action'] == d['step']-1]
        for baseline in ('A','F3'):
            old,new = data[name][baseline],data[name]['R']
            if old['result']['success'] and new['result']['success']:
                pair[baseline+'_saving'] = {k:old['result'][k]-new['result'][k] for k in KEYS}
                pair[baseline+'_tail_saving_s'] = old['extra']['tail_s']-new['extra']['tail_s']
                pair[baseline+'_intermediate_search_saving_s'] = old['diagnostics']['intermediate_search_s']-new['diagnostics']['intermediate_search_s']
        pair['new_fallback_reasons_vs_A'] = sorted(set(data[name]['R']['fallback_counts'])-set(data[name]['A']['fallback_counts']))
        pairs.append(pair)
    assert frozen['main_comparison'] == 'A_plus_relocation versus frozen A'
    assert receipt['completion']['all_clear'] == all(data[c['name']]['R']['result']['success'] for c in cases)
    rels = [data[c['name']]['R']['relocation'] for c in cases]
    totals = dict(counts={scope:dict(sum((collections.Counter(v['counts'].get(scope,{})) for v in rels),collections.Counter()))
                         for scope in ('online','rollout')},
        **{k:sum(v[k] for v in rels) for k in ('moved_first_station_plans','next_position_match_count','moved_first_station_execution_count')})
    probe_path = next(ROOT/p for p in frozen['code_hashes'] if p.endswith('/probe.json'))
    probe = {p['case']:p for p in read(probe_path)['cases']}
    by_case = {p['case']:p for p in pairs}
    long_tail_comparison = [dict(case=name,probe_first_plan_saving_s=probe[name]['first_plan_saving_s'],
        A_tail_s=data[name]['A']['extra']['tail_s'],R_tail_s=data[name]['R']['extra']['tail_s'],
        tail_saving_s=by_case[name].get('A_tail_saving_s'),
        total_saving_s=by_case[name].get('A_saving',{}).get('total_s')) for name in LONG_TAILS]
    report = dict(main_comparison='R versus frozen A', data=data,pairs=pairs,
        comparisons={m:comparison(pairs,data,m) for m in ('A','F3')},
        metrics={m:metrics([data[c['name']][m] for c in cases]) for m in ('F3','A','R')},
        relocation_totals=totals,long_tail_cases=list(LONG_TAILS),long_tail_comparison=long_tail_comparison,source_hashes=hashes,
        validation=dict(trajectories=3*len(cases),actions=action_count,feedback_cost_geometry_replay_passed=True,
                        input_validation=receipt),
        analysis_code_hashes={p.relative_to(ROOT).as_posix():sha(p) for p in
            (Path(__file__),Path(__file__).with_name('analyze_results.py'),Path(__file__).with_name('analyze_light.py'))})
    a.base.dump(run/'analysis.json',report)
    (run/'REPORT.md').write_text(render(report),encoding='utf-8')
    print(json.dumps(dict(comparisons=report['comparisons'],metrics=report['metrics'],relocation_totals=totals,
                         checked_actions=action_count),ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
