"""F3改固定24例：全轨迹审计、分层配对统计与中文报告。"""
import argparse
import collections
import json
import random
import statistics as st
from pathlib import Path

from analyze_results import audit
from analyze_light import stops_and_search
from analyze_relocation import divergence, sha
from light_run import ROOT, a, read
from prepare_team import canonical, digest

KEYS = ('total_s', 'per_source_s', 'move_s', 'measure_s', 'switch_s',
        'success_clear_s', 'fail_clear_s')
LABELS = {'all24': '全部24例', 'new16': '新增16例', 'reused8': '原开发8例'}


def percentile(sorted_values, q):
    index = (len(sorted_values)-1)*q
    lo = int(index); hi = min(lo+1, len(sorted_values)-1)
    return sorted_values[lo]*(hi-index)+sorted_values[hi]*(index-lo) if hi != lo else sorted_values[lo]


def paired_bootstrap(pairs, samples=20000, seed=20260913):
    strata = [[p for p in pairs if p['layout'] == layout] for layout in sorted({p['layout'] for p in pairs})]
    rng = random.Random(seed); values = {'total_s': [], 'per_source_s': []}
    for _ in range(samples):
        draw = [group[rng.randrange(len(group))] for group in strata for _ in group]
        for key in values:
            values[key].append(sum(p['saving'][key] for p in draw)/len(draw))
    return {key: [percentile(sorted(v), .025), percentile(sorted(v), .975)] for key, v in values.items()}


def summary(pairs, bootstrap=False):
    results = {label: [p[label]['result'] for p in pairs] for label in ('baseline', 'candidate')}
    clear = all(r['success'] for rr in results.values() for r in rr)
    out = dict(cases=len(pairs), source_count=sum(p['n'] for p in pairs), all_clear=clear,
        clear_counts={label: sum(r['success'] for r in rr) for label, rr in results.items()})
    if not clear:
        out['status'] = '存在未全清案例，不以仅成功子集估计性能收益'
        return out
    out['metrics'] = {}
    for label, rr in results.items():
        out['metrics'][label] = dict(sum_total_s=sum(r['total_s'] for r in rr),
            mean_total_s=st.mean(r['total_s'] for r in rr),
            mean_per_source_s=st.mean(r['per_source_s'] for r in rr),
            pooled_per_source_s=sum(r['total_s'] for r in rr)/out['source_count'],
            max_total_s=max(r['total_s'] for r in rr),
            mean_tail_s=st.mean(p[label]['extra']['tail_s'] for p in pairs),
            mean_search_without_found_s=st.mean(p[label]['diagnostics']['search_without_found_s'] for p in pairs))
    savings = [p['saving']['total_s'] for p in pairs]
    out.update(mean_saving={key: st.mean(p['saving'][key] for p in pairs) for key in KEYS},
        sum_saving_s=sum(savings), median_saving_s=st.median(savings),
        wins=sum(v>1e-6 for v in savings), losses=sum(v<-1e-6 for v in savings),
        ties=sum(abs(v)<=1e-6 for v in savings), worst_regression_s=max(0, -min(savings)),
        best_saving_s=max(savings), leave_one_out={key: [
            min(st.mean(p['saving'][key] for j, p in enumerate(pairs) if j != i) for i in range(len(pairs))),
            max(st.mean(p['saving'][key] for j, p in enumerate(pairs) if j != i) for i in range(len(pairs)))]
            for key in ('total_s', 'per_source_s')})
    out['relative_saving_pct'] = {
        key: out['mean_saving'][key]/out['metrics']['baseline'][metric]*100
        for key, metric in [('total_s', 'mean_total_s'), ('per_source_s', 'mean_per_source_s')]}
    # These identities use independent aggregation paths, including source weighting.
    assert abs(out['sum_saving_s']-(out['metrics']['baseline']['sum_total_s']-
                                  out['metrics']['candidate']['sum_total_s'])) < 1e-6
    assert abs(out['mean_saving']['total_s']-sum(out['mean_saving'][k] for k in KEYS[2:])) < 1e-6
    out['mean_total_saving_ge_30s'] = out['mean_saving']['total_s'] >= 30
    if bootstrap:
        out['bootstrap_ci95_s'] = paired_bootstrap(pairs)
        out['both_mean_savings_ci_positive'] = all(v[0] > 0 for v in out['bootstrap_ci95_s'].values())
    return out


def report_text(data):
    g = data['groups']; all_s = g['all24']; lines = ['# F3改与F3：原普通24例配对结果', '',
        '2026-09-13。F3改固定为上一轮R（F3＋A＋扫描站挪近），未加入B及换侧删站。', '',
        '沿用原F3的micro_confirm批次：320100—320123，四种布局×三种误差×两例。原8例实际是这批24例的固定子集，不是独立压力组。本轮引用已核验的8条F3改轨迹，补跑其余16条；原F3的24条轨迹全部复用。', '',
        '运行前已冻结输入、源码、统计口径和上限；未调参或排除结果。全部是本地自建案例，24例含开发数据，新增16例在本轮未参与调参。', '']
    if not all_s['all_clear']:
        lines += ['**存在未全清案例，本轮不能确认F3改更快。**', '',
                  '详见analysis.json中的逐例状态；未删除失败样本。']
        return '\n'.join(lines)+'\n'
    old = all_s['metrics']['baseline']; new = all_s['metrics']['candidate']
    ci = all_s['bootstrap_ci95_s']; benefit = all_s['relative_saving_pct']['total_s']
    if all_s['both_mean_savings_ci_positive']:
        judgment = '这批24例的平均整局和每源耗时均有清晰改善，但实际幅度仍需按百分比判断。'
    else:
        judgment = '完整24例的平均差异证据不够清晰，本轮不支持用F3改替代F3。'
    lines += [f"**{judgment} 两种方法均24/24全清，整局平均变化为节省{all_s['mean_saving']['total_s']/60:.3f}分钟（{benefit:.2f}%）。**", '',
        '| 指标 | F3 | F3改 | F3改节省 |', '| --- | ---: | ---: | ---: |',
        f"| 24局合计/分钟 | {old['sum_total_s']/60:.3f} | {new['sum_total_s']/60:.3f} | {all_s['sum_saving_s']/60:.3f} |",
        f"| 单局平均/分钟 | {old['mean_total_s']/60:.3f} | {new['mean_total_s']/60:.3f} | {all_s['mean_saving']['total_s']/60:.3f}（{benefit:.2f}%） |",
        f"| 每局T/N再等权平均/分钟每源 | {old['mean_per_source_s']/60:.3f} | {new['mean_per_source_s']/60:.3f} | {all_s['mean_saving']['per_source_s']/60:.3f}（{all_s['relative_saving_pct']['per_source_s']:.2f}%） |",
        f"| 总T/总N/分钟每源 | {old['pooled_per_source_s']/60:.3f} | {new['pooled_per_source_s']/60:.3f} | {(old['pooled_per_source_s']-new['pooled_per_source_s'])/60:.3f} |", '',
        f"24例共{all_s['source_count']}个源。T包含定位、移动、扫描、清除以及最终查漏的全部虚拟时间；每源指标不是清除动作本身的5秒。现实计算时间单列，不与题目虚拟耗时混用。", '',
        '## 收益是否稳定', '',
        f"逐例为{all_s['wins']}胜、{all_s['ties']}平、{all_s['losses']}负；中位节省{all_s['median_saving_s']/60:.3f}分钟，最大退步{all_s['worst_regression_s']/60:.3f}分钟。",
        f"按布局分层、同案配对bootstrap的95%区间：单局平均节省[{ci['total_s'][0]/60:.3f}, {ci['total_s'][1]/60:.3f}]分钟；每源平均节省[{ci['per_source_s'][0]:.3f}, {ci['per_source_s'][1]:.3f}]秒。固定种子20260913，20000次重采样，百分位区间。",
        f"删除任意一例后，平均单局节省范围[{all_s['leave_one_out']['total_s'][0]/60:.3f}, {all_s['leave_one_out']['total_s'][1]/60:.3f}]分钟。统计区间描述本批案例的波动，不等于官方隐藏测试保证。", '',
        '| 样本 | F3单局/分钟 | F3改单局/分钟 | 平均节省/秒 | 整局节省95%区间/秒 | 每源节省/秒 | 胜/平/负 |',
        '| --- | ---: | ---: | ---: | --- | ---: | --- |']
    for group in ('all24', 'new16', 'reused8'):
        s = g[group]; interval = s['bootstrap_ci95_s']['total_s']
        lines.append(f"| {LABELS[group]} | {s['metrics']['baseline']['mean_total_s']/60:.3f} | {s['metrics']['candidate']['mean_total_s']/60:.3f} | {s['mean_saving']['total_s']:.3f} | [{interval[0]:.3f}, {interval[1]:.3f}] | {s['mean_saving']['per_source_s']:.3f} | {s['wins']}/{s['ties']}/{s['losses']} |")
    s = g['new16']; nci = s['bootstrap_ci95_s']['per_source_s']
    new_judgment = ('新增案例的两个平均收益区间均为正，收益并非只来自原开发8例。'
        if s['both_mean_savings_ci_positive'] else
        '新增案例平均耗时更长，且区间跨零，既不支持提速，也不足以断言普遍变慢。'
        if s['mean_saving']['total_s'] < 0 else
        '新增案例均值有所改善，但两个指标尚未同时支持区间为正，改善证据有限。')
    lines += ['', f"新增16例每源平均节省的95%区间为[{nci[0]:.3f}, {nci[1]:.3f}]秒。" + new_judgment, '',
        '## 成本分解与查漏', '', '| 平均每局成本/秒 | F3减F3改，正为节省 |', '| --- | ---: |']
    for key, label in [('move_s', '移动'), ('measure_s', '检测'), ('switch_s', '切频'),
                       ('success_clear_s', '成功清除'), ('fail_clear_s', '失败清除')]:
        lines.append(f"| {label} | {all_s['mean_saving'][key]:+.3f} |")
    lines += ['', f"最后清除后的尾段均值：F3 {old['mean_tail_s']:.3f}秒，F3改 {new['mean_tail_s']:.3f}秒。中途加尾段的无已发现待清源排查均值：F3 {old['mean_search_without_found_s']:.3f}秒，F3改 {new['mean_search_without_found_s']:.3f}秒。整局收益不能自动归因为最后查漏改善。", '',
        '## 最大退步的实际轨迹', '']
    worst = min(data['pairs'], key=lambda p: p['saving']['total_s'])
    if worst['saving']['total_s'] < -1e-6:
        div = worst['first_divergence']; move_loss = -worst['saving']['move_s']
        lines += [f"`{worst['case']}`整局多用{-worst['saving']['total_s']/60:.3f}分钟，其中移动多用{move_loss/60:.3f}分钟。首次实际动作分歧是第{div['step']}步。", '',
                  f"F3动作：{div['old']['reason']}，位置{div['old']['position']}；F3改动作：{div['new']['reason']}，位置{div['new']['position']}。当时状态{div['old']['before_counts']}。", '',
                  f"实际成功清除频道顺序：F3 {worst['baseline']['clearance_order']}；F3改 {worst['candidate']['clearance_order']}。", '',
                  '这是固定组合的整局回归证据。连续覆盖与当前计划缩短不保证反馈后的整局耗时缩短；本轮没有另跑A单因素，不能将全部差值分摊给A或挪站。', '']
    else:
        lines += ['本批没有整局退步案例。', '']
    lines += [
        '## 分组与逐例', '', '下列布局和误差分组只作描述，单组例数很少，不据此继续定向调参。', '',
        '| 分组 | 例数 | 平均整局节省/秒 | 平均每源节省/秒 | 胜/平/负 |', '| --- | ---: | ---: | ---: | --- |']
    for kind in ('by_layout', 'by_noise'):
        for name, s in data[kind].items():
            lines.append(f"| {name} | {s['cases']} | {s['mean_saving']['total_s']:.3f} | {s['mean_saving']['per_source_s']:.3f} | {s['wins']}/{s['ties']}/{s['losses']} |")
    lines += ['', '| 案例 | 来源 | 源数 | F3/分钟 | F3改/分钟 | 节省/分钟 | 每源节省/秒 |',
              '| --- | --- | ---: | ---: | ---: | ---: | ---: |']
    for p in data['pairs']:
        lines.append(f"| {p['case']} | {'复用8例' if p['reused'] else '新增16例'} | {p['n']} | {p['baseline']['result']['total_s']/60:.3f} | {p['candidate']['result']['total_s']/60:.3f} | {p['saving']['total_s']/60:+.3f} | {p['saving']['per_source_s']:+.3f} |")
    v = data['validation']; wall = data['candidate_computation']
    lines += ['', '## 核验与复现', '',
        f"已独立重放{v['trajectories']}条轨迹、{v['actions']}个动作，核对反馈、计费、几何状态及全清条件；案例、策略依赖、开局缓存与历史结果指纹未变。旧批次有两处仅报告/演示文件与当时指纹不同，执行依赖全部匹配，详见manifest.json。",
        f"F3改含历史开局选点时间的单局计算耗时均值{wall['mean_accounted_wall_s']:.2f}秒、最大{wall['max_accounted_wall_s']:.2f}秒。8例与16例运行时段不同，不以墙钟证明相对原F3计算更快。",
        '结果、逐例输入引用和指纹见本目录的analysis.json、manifest.json、cases.json、completion.json；新轨迹在各案例子目录，复用轨迹在manifest逐例candidate_dir字段。', '',
        '```powershell',
        'py -3.13 experiments/b_q3/cross_method/p1/analyze_f3_modified.py outputs/experiments/b_q3_p1/f3_modified_micro24_20260913',
        '```', '', '以上核验由AI执行，尚未经团队人工复核；本轮不改src正式模型，不构成正式测试表现。']
    return '\n'.join(lines)+'\n'


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('run', type=Path); args = parser.parse_args()
    run = args.run.resolve(); manifest = read(run/'manifest.json'); cases = read(run/'cases.json')
    assert read(run/'completion.json')['finished'] == len(cases) == 24
    for mapping in ('code_hashes', 'input_hashes'):
        for rel, expected in manifest[mapping].items():
            assert sha(ROOT/rel) == expected, rel
    for rel, expected in manifest['dependency_hashes_lf'].items():
        assert digest(ROOT/rel) == expected, rel
    entries = {e['name']: e for e in manifest['cases']}; pairs = []; hashes = {}; actions = 0
    assert len(entries) == len(cases) and sum(e['reused'] for e in entries.values()) == 8
    for case in cases:
        e = entries[case['name']]; assert canonical(case) == e['case_sha256']
        pair = dict(case=case['name'], n=len(case['sources']), layout=case['layout'], noise=case['noise'], reused=e['reused'])
        rows_by_label = {}
        for label in ('baseline', 'candidate'):
            directory = ROOT/e[label+'_dir']; result, rows, extra = audit(case, directory)
            actions += len(rows); rows_by_label[label] = rows; meta = read(directory/'metadata.json')
            assert meta['refinement_level'] == 3 and meta['samples'] == 4
            assert meta['selected_second'] == read(ROOT/e['baseline_selection'])['selected']
            pair[label] = dict(result=result, extra=extra, diagnostics=stops_and_search(rows, extra),
                fallback_counts=dict(collections.Counter(d['fallback'] for d in meta['refinement_decisions'] if 'fallback' in d)),
                clearance_order=[r['channel'] for r in rows if r['kind'] == 'clear' and r['response']['clear_result'] == 'success'])
            pair[label]['diagnostics'].pop('stops'); pair[label]['diagnostics'].pop('detours')
            if label == 'candidate':
                assert meta['lightweight']['mode'] == 'A' and meta['relocation']['bisections'] == 10
                pair[label]['relocation_counts'] = meta['relocation']['counts']
            for fn in ('result.json', 'metadata.json', 'actions.jsonl'):
                path = directory/fn; hashes[path.relative_to(ROOT).as_posix()] = sha(path)
        pair['first_divergence'] = divergence(rows_by_label['baseline'], rows_by_label['candidate'])
        if pair['baseline']['result']['success'] and pair['candidate']['result']['success']:
            pair['saving'] = {key: pair['baseline']['result'][key]-pair['candidate']['result'][key] for key in KEYS}
        pairs.append(pair)
        print('audited', case['name'], flush=True)
    groups = {name: summary(pp, bootstrap=True) for name, pp in [
        ('all24', pairs), ('new16', [p for p in pairs if not p['reused']]), ('reused8', [p for p in pairs if p['reused']])]}
    data = dict(groups=groups, pairs=pairs, source_hashes=hashes, analysis_code_sha256=sha(Path(__file__)),
        validation=dict(trajectories=48, actions=actions, feedback_cost_geometry_replay_passed=True,
                        frozen_inputs_and_code_unchanged=True, method_configuration_verified=True),
        candidate_computation=dict(mean_accounted_wall_s=st.mean(p['candidate']['result']['accounted_wall_s'] for p in pairs),
            max_accounted_wall_s=max(p['candidate']['result']['accounted_wall_s'] for p in pairs)),
        by_layout={name: summary([p for p in pairs if p['layout'] == name]) for name in sorted({p['layout'] for p in pairs})},
        by_noise={name: summary([p for p in pairs if p['noise'] == name]) for name in sorted({p['noise'] for p in pairs})})
    a.base.dump(run/'analysis.json', data)
    (run/'REPORT.md').write_text(report_text(data), encoding='utf-8')
    print(json.dumps(groups, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
