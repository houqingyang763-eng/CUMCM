"""只读既有实验，重建 AI1 汇总；不运行策略、不生成新场景。"""
import hashlib
import json
import math
import statistics as st
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
Q3 = ROOT / 'experiments/b_q3'
COSTS = ('move_s', 'measure_s', 'switch_s', 'success_clear_s', 'fail_clear_s')
INPUTS = {}
CHECKS = {'result_rows': 0, 'ledger_actions': 0, 'paired_batches': 0}


def read(path, lines=False):
    data = path.read_bytes()
    INPUTS[path.relative_to(ROOT).as_posix()] = hashlib.sha256(data).hexdigest()
    return [json.loads(x) for x in data.decode('utf-8-sig').splitlines()] if lines else json.loads(data)


def check(r):
    CHECKS['result_rows'] += 1
    assert r['success'] and r['cleared'] == r['real_n'], r['case']
    assert abs(sum(r[k] for k in COSTS) - r['total_s']) < 1e-5, r['case']
    assert abs(r['per_source_s'] - r['total_s'] / r['cleared']) < 1e-6


def load_patrol(run):
    rows = read(Q3 / 'probability_patrol/runs' / run / 'results.json')
    for row in rows:
        check(row)
    return {r['case']: r for r in rows}


def load_modes(folder, modes):
    summary = read(folder / 'summary.json')
    out = {m: {} for m in modes}
    for item in summary['rows']:
        for mode in modes:
            r = read(folder / item['case'] / mode / 'result.json')
            check(r)
            assert abs(item[mode]['total_s'] - r['total_s']) < 1e-6
            out[mode][r['case']] = r
    return out


def paired(data):
    sets = [set(v) for v in data.values()]
    assert all(s == sets[0] for s in sets)
    for case in sets[0]:
        rs = [v[case] for v in data.values()]
        assert len({(r['seed'], r['real_n'], r['layout'], r['noise']) for r in rs}) == 1
    CHECKS['paired_batches'] += 1


def pct(values, p):
    a = sorted(values)
    pos = (len(a) - 1) * p
    lo, hi = math.floor(pos), math.ceil(pos)
    return a[lo] + (a[hi] - a[lo]) * (pos - lo)


def metrics(rows):
    rows = list(rows)
    v = [r['total_s'] / 60 for r in rows]
    return dict(n=len(rows), mean=st.mean(v), median=st.median(v),
                sd=st.stdev(v) if len(v) > 1 else 0, p95=pct(v, .95), worst=max(v),
                per_source=st.mean(r['per_source_s'] / 60 for r in rows),
                **{k: st.mean(r[k] / 60 for r in rows) for k in COSTS})


def table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(headers) + ' |', '| ' + ' | '.join(['---'] * len(headers)) + ' |']
                     + ['| ' + ' | '.join(str(x) for x in row) + ' |' for row in rows])


def f(x):
    return f'{x:.3f}'


def batch_section(name, data, reference):
    lines = [f'## {name}', '', f'本表相对参照：`{reference}`；均为同案配对。', '']
    rows = []
    for mode, cases in data.items():
        m = metrics(cases.values())
        diff = [data[reference][c]['total_s'] / 60 - r['total_s'] / 60 for c, r in cases.items()]
        rows.append([mode, f'{m["n"]}/{m["n"]}', f(m['mean']), f(m['per_source']), f(m['median']), f(m['sd']), f(m['p95']), f(m['worst']), f(st.mean(diff)),
                     f'{sum(x > 1e-6 for x in diff)}/{sum(x < -1e-6 for x in diff)}/{sum(abs(x) <= 1e-6 for x in diff)}'])
    lines += [table(['版本', '全清/案例数', '整局均值/分', '逐局每源均值/分', '中位数/分', '样本标准差/分', '样本P95/分', '最慢局/分', '平均节省/分', '胜/负/平'], rows), '']
    for field, title in [('real_n', '源数'), ('layout', '分布'), ('noise', '误差机制')]:
        lines += [f'### 按{title}分组', '', '每个版本单元格均为“整局均值 / 每源均值”，单位：分钟。', '']
        groups = sorted({r[field] for r in next(iter(data.values())).values()})
        rows = []
        for group in groups:
            count = sum(r[field] == group for r in next(iter(data.values())).values())
            row = [group, count]
            for cases in data.values():
                m = metrics(r for r in cases.values() if r[field] == group)
                row.append(f'{m["mean"]:.3f} / {m["per_source"]:.3f}')
            rows.append(row)
        lines += [table([title, '案例数', *data.keys()], rows), '']
    return '\n'.join(lines)


def audit_log(path, result):
    logs = read(path, lines=True)
    assert len(logs) == result['actions']
    sums = {k: 0.0 for k in COSTS}
    position, channel, total = (0.0, 0.0), 1, 0.0
    histories = {j: set() for j in range(1, 21)}
    statuses = {j: 'unknown' for j in range(1, 21)}
    heterogeneous, joint_departures = 0, 0
    positive_moves, clear_times = [], []
    for a in logs:
        CHECKS['ledger_actions'] += 1
        costs = a['independent_costs']
        move = math.dist(position, a['position']) / 5
        switch = float(a['kind'] == 'measure' and channel != a['channel'])
        assert abs(move - costs['move_s']) < 1e-5
        assert switch == costs['switch_s']
        if a['kind'] == 'measure':
            assert costs['measure_s'] == 5 and costs['success_clear_s'] == costs['fail_clear_s'] == 0
            channel = a['channel']
        else:
            success = a['response']['clear_result'] == 'success'
            assert costs['success_clear_s'] == (5 if success else 0)
            assert costs['fail_clear_s'] == (0 if success else 3)
        if move > 1e-8:
            positive_moves.append(move)
        for key in COSTS:
            sums[key] += costs[key]
        total += sum(costs.values())
        assert abs(total - a['response']['virtual_time_s']) < 1e-5
        if costs['success_clear_s']:
            clear_times.append(total)
        if a['reason'] == 'joint_cover_scan' and move > 1e-8:
            groups = {frozenset(histories[j]) for j, s in statuses.items() if s == 'unknown'}
            joint_departures += 1
            heterogeneous += len(groups) > 1
        j = a['channel']
        if a['kind'] == 'measure' and a['response'].get('measure_result') == 'no_signal':
            histories[j].add(tuple(a['position']))
        statuses[j] = a['after']['selected_channel']['status']
        if a['after']['ever_seen_count'] == 16:
            statuses = {j: ('absent' if s == 'unknown' else s) for j, s in statuses.items()}
        position = tuple(a['position'])
    for key in COSTS:
        assert abs(sums[key] - result[key]) < 1e-5
    assert len(clear_times) == result['cleared']
    last_index = max(i for i, a in enumerate(logs) if a['independent_costs']['success_clear_s'])
    tail = logs[last_index + 1:]
    tail_cost = {k: sum(a['independent_costs'][k] for a in tail) for k in COSTS}
    assert abs(sum(tail_cost.values()) - (total - clear_times[-1])) < 1e-5
    intervals = [t - prev for t, prev in zip(clear_times, [0.0] + clear_times[:-1])]
    blocks = []
    for quartile in range(4):
        values = [v for i, v in enumerate(intervals) if (4 * i) // len(intervals) == quartile]
        blocks.append(st.mean(values))
    return dict(case=result['case'], n=result['real_n'], layout=result['layout'], noise=result['noise'],
                positive_moves_s=positive_moves, tail_s=sum(tail_cost.values()), tail_costs=tail_cost,
                tail_actions=len(tail), last_clear_step=logs[last_index]['step'],
                average_clear_timestamp_s=st.mean(clear_times), clear_interval_quartiles_s=blocks,
                joint_departures=joint_departures, heterogeneous_joint_departures=heterogeneous)


def geometric_spot_checks():
    """重现上轮临时几何核对；不请求新反馈，也不模拟策略。"""
    sys.path.insert(0, str(Q3 / 'probability_patrol'))
    from coverage_state import coverage_certificate
    out = []
    for name in ('cluster_biased_320115', 'uniform_hashed_320104', 'line_biased_320120', 'uniform_smooth_320101'):
        logs = read(Q3 / 'refinement/runs/micro_confirm' / name / 'f3/actions.jsonl', lines=True)
        index = max(i for i,a in enumerate(logs) if a['independent_costs']['move_s'] > 1e-8)
        a = logs[index]
        p, oldq, j = tuple(a['before']['position']), tuple(a['position']), a['channel']
        history = [(tuple(r['position']), 1000.0) for r in logs[:index]
                   if r['channel'] == j and r['kind'] == 'measure' and r['response'].get('measure_result') == 'no_signal']
        def certify(t):
            q = tuple(p[k] + t * (oldq[k] - p[k]) for k in range(2))
            return q, coverage_certificate(history + [(q, 1000.0)])
        assert certify(1)[1].complete
        feasible = [t/20 for t in range(21) if certify(t/20)[1].complete]
        hi = min(feasible)
        lo = max(0, hi - .05)
        for _ in range(12):
            mid = (lo + hi) / 2
            if certify(mid)[1].complete:
                hi = mid
            else:
                lo = mid
        q, cert = certify(hi)
        out.append(dict(case=name, step=a['step'], channel=j, old_q=oldq, candidate_q=q,
                        old_move_s=math.dist(p,oldq)/5, candidate_move_s=math.dist(p,q)/5,
                        move_saved_s=(math.dist(p,oldq)-math.dist(p,q))/5,
                        rational_verified=cert.rational_verified,
                        scope='single-channel conditional negative coverage; no policy run or 2D optimum'))
    return out


def main():
    batches = {}
    batches['R3独立24例（180100—180123）'] = {
        'baseline': load_patrol('baseline_holdout_final'), 'R3': load_patrol('r3_holdout_final')}
    batches['自适应第二站独立24例（280100—280123）'] = load_modes(Q3 / 'adaptive_second/runs/confirm', ['baseline', 'fixed', 'position', 'joint'])
    ref = Q3 / 'refinement/runs'
    batches['F系列第一批24例（310100—310123）'] = load_modes(ref / 'confirm', ['baseline', 'current', 'f1', 'f2', 'f3'])
    batches['F系列第二批24例（320100—320123）'] = load_modes(ref / 'micro_confirm', ['baseline', 'current', 'f1', 'f2', 'f3', 'f4'])
    batches['F系列固定压力8例（190100—190107）'] = load_modes(ref / 'stress', ['baseline', 'current', 'f1', 'f2', 'f3', 'f4'])
    for data in batches.values():
        paired(data)
    first, second = list(batches.values())[2:4]
    combined = {m: {**first[m], **second[m]} for m in first}
    assert all(len(v) == 48 for v in combined.values())
    paired(combined)
    refs = ['baseline', 'fixed', 'current', 'current', 'current']
    intro = ['# AI1：按源数、布局和误差分组的性能', '',
             '生成依据：既有逐局 result/results JSON；本次只做重新统计，没有新跑策略。生成脚本为 [rebuild_metrics_AI1.py](rebuild_metrics_AI1.py)。', '',
             '所有下列案例均全清。每源均值 = 先在每局算 T/N，再对案例等权平均；不能替换成总时间之和除以源数之和。节省为参照减候选，负数表示恶化。样本P95采用排序后线性插值，不是最坏情况保证。', '',
             '源数由生成种子决定；源数分组同时混有不同位置、接收半径及误差，未做只改变源数的控制实验。边缘与近共线组接收半径固定1000米，均匀与聚集组为1000—1500米，因此布局差异同时含半径差异。详见 [01_AI1_优化历程.md](01_AI1_优化历程.md)。', '']
    intro += ['压力8例中N=10与zero误差绑定、N=16与biased误差绑定；压力集的源数表和误差表不是两个独立影响的证据。', '']
    for (name, data), reference in zip(batches.items(), refs):
        intro.append(batch_section(name, data, reference))
    intro += ['## 两批F系列合并48例：描述性汇总', '',
              '合并的是已完成的两批不同种子，不是新增48例；F3未随F4增加复查逻辑。两批分别统计应优先阅读。F4没有第一批数据，因此不并入此表。', '',
              batch_section('合并48例', combined, 'current')]
    intro += ['### 合并48例：布局×误差', '', '每格4例；仅列current、F3与baseline，时间为分钟。样本很小，不作子组显著性断言。', '']
    cross = []
    for layout in ('uniform', 'edge', 'cluster', 'line'):
        for noise in ('smooth', 'biased', 'hashed'):
            vals = {m: metrics(r for r in combined[m].values() if r['layout'] == layout and r['noise'] == noise) for m in ('baseline', 'current', 'f3')}
            cross.append([layout, noise, vals['f3']['n'], f(vals['baseline']['mean']), f(vals['current']['mean']), f(vals['f3']['mean']), f(vals['current']['mean'] - vals['f3']['mean'])])
    intro += [table(['布局', '误差', '案例数', 'baseline', 'current', 'F3', 'F3相对current节省'], cross), '',
              '## 第二批费用账本', '', table(['版本', '移动/分', '检测/分', '切频/分', '成功清除/分', '失败清除/分'],
                [[m, *[f(metrics(rs.values())[k]) for k in COSTS]] for m, rs in second.items()]), '',
              '## 第二批逐例表', '', table(['案例', 'N', 'baseline/分', 'current/分', 'F3/分', 'F4/分', 'F3节省current/分', 'F3每源/分'],
                [[c, second['f3'][c]['real_n'], *[f(second[m][c]['total_s'] / 60) for m in ('baseline', 'current', 'f3', 'f4')],
                  f((second['current'][c]['total_s']-second['f3'][c]['total_s'])/60), f(second['f3'][c]['per_source_s']/60)] for c in sorted(second['f3'])]), '',
              '## 数据入口', '', '- [R3原始逐局结果](../../probability_patrol/runs/r3_holdout_final/results.json)',
              '- [第二站原始汇总](../../adaptive_second/runs/confirm/summary.json)',
              '- [F系列第一批](../../refinement/runs/confirm/summary.json)',
              '- [F系列第二批](../../refinement/runs/micro_confirm/summary.json)',
              '- [F系列压力集](../../refinement/runs/stress/summary.json)', '',
              '各输入文件SHA256、统计口径与校验计数见 [metrics_AI1.json](metrics_AI1.json)。']
    (HERE / '02_AI1_分组性能.md').write_text('\n'.join(intro) + '\n', encoding='utf-8')

    logs = {mode: [audit_log(ref / 'micro_confirm' / c / mode / 'actions.jsonl', r) for c, r in cases.items()] for mode, cases in second.items()}
    f3 = logs['f3']
    text = ['# AI1：移动、清除进度和最终查漏的时间尺度', '',
            '本页由原始动作重新计费；仅使用F系列第二批24例。查漏尾段定义为“最后一次成功清除之后至算法结束”，这是评估者事后划分，策略当时不知道还有没有源。不能只用代码phase=completion：服务站队列在最后清除后也可能继续检测。', '',
            '## 各版本尾段及移动尺度', '',
            '单次移动只统计距离大于0的动作；同站切频检测的0秒移动不进入分母。移动均值/中位数为该版本24例所有实际移动的合并统计。尾段均值含尾段为0的案例。', '']
    rows = []
    for mode, rs in logs.items():
        moves = [v for r in rs for v in r['positive_moves_s']]
        rows.append([mode, len(moves), f(st.mean(moves)), f(st.median(moves)), f(pct(moves, .95)),
                     f(st.mean(r['tail_s'] for r in rs)/60), f(st.mean(r['tail_costs']['move_s'] for r in rs)/60),
                     f(st.mean(r['tail_costs']['measure_s']+r['tail_costs']['switch_s'] for r in rs)/60), sum(r['tail_s']>1e-8 for r in rs)])
    text += [table(['版本', '非零移动次数', '单移均值/秒', '单移中位/秒', '单移P95/秒', '尾段均值/分', '尾段移动/分', '尾段检测切频/分', '有尾段局数/24'], rows), '',
             'baseline尾段为零是因为排查提前完成，不表示它没有查漏成本。F3尾段也不含清除过程中穿插的未知频道检查，不能当作全部查漏费用。', '',
             '题面时间尺度：一次检测5秒；发生换频再加1秒；100米移动20秒、1000米移动200秒；成功清除5秒、失败清除3秒。仅减少操作次数，可能被一次绕路抵消。', '',
             '## F3：不同源数的尾段', '', table(['N', '案例数', '尾段平均/分', '尾段最慢/分'],
               [[n, sum(r['n']==n for r in f3), f(st.mean(r['tail_s'] for r in f3 if r['n']==n)/60), f(max(r['tail_s'] for r in f3 if r['n']==n)/60)] for n in sorted({r['n'] for r in f3})]), '',
             '## F3：逐局尾段', '', table(['案例', 'N', '最后成功清除步', '后续动作数', '尾段/分', '尾段移动/分', '检测切频/分'],
               [[r['case'], r['n'], r['last_clear_step'], r['tail_actions'], f(r['tail_s']/60), f(r['tail_costs']['move_s']/60), f((r['tail_costs']['measure_s']+r['tail_costs']['switch_s'])/60)] for r in f3]), '',
             '## F3：是否越清越快', '',
             '定义相邻成功清除之间的间隔，第一个间隔从开局算起；按该局的清除次序等分四段（按floor(4i/N)分组），各段先在局内取均值再对24局取均值。这里包含共享观测与移动，不是某个源独占的物理处理时间。尾段另列，不塞入最后一个源。', '',
             table(['清除次序分段', '平均相邻清除间隔/秒'], [[f'第{k+1}段', f(st.mean(r['clear_interval_quartiles_s'][k] for r in f3))] for k in range(4)]), '',
             '该描述不能建立“每后一个源都更快”或“增加源数必然降低单源成本”的因果关系。共享前期费用摊薄、路程变化、最后困难目标和16源上限结束规则同时影响T/N。', '',
             '## 频道记录是否不同：本次核对结果', '',
             f'第二批F3共有{sum(r["joint_departures"] for r in f3)}次发生移动的joint_cover_scan出发；其中未知频道阴性历史存在差异的次数为{sum(r["heterogeneous_joint_departures"] for r in f3)}。当前多数共享站对未知频道整批测量，记录因此同步。', '',
             '代码确实只取未知频道共同的阴性测点、用全部未知频道数量计费；这是按频道选择时应解除的限制，但不能将这批案例的耗时归因于已发生的历史信息丢失。本页未评估任何新查漏策略的提速。', '',
             '本次校验重算路程/5、检测5秒、切频1秒、清除3/5秒及累计时钟，与既有结果逐项一致；未重新验证隐含真值几何或重新执行策略。']
    (HERE / '03_AI1_时间尺度与查漏.md').write_text('\n'.join(text) + '\n', encoding='utf-8')
    spots = geometric_spot_checks()
    for relative in ('experiments/b_adaptive_q3/simulation.py', 'experiments/b_overnight/coverage.py',
                     'experiments/b_q3/probability_patrol/coverage_state.py',
                     'experiments/b_q3/probability_patrol/covering_route.py',
                     'experiments/b_q3/probability_patrol/REPORT.md',
                     'experiments/b_q3/probability_patrol/INITIAL_DESIGN.md',
                     'experiments/b_q3/adaptive_second/REPORT.md',
                     'experiments/b_q3/refinement/REPORT.md',
                     'experiments/b_q3/refinement/FAILURE_ANALYSIS.md',
                     'experiments/b_q3/refinement/runs/random_audit/REVIEW.md',
                     'experiments/b_q3/decision_pilot/REPORT.md',
                     'experiments/b_benchmark_scale/RESULTS.md',
                     'experiments/b_adaptive_q3/RESULTS.md',
                     'experiments/b_method_families/Q3_RESEARCH_REASSESSMENT.md'):
        INPUTS[relative] = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
    out = {'owner': 'AI1', 'date': '2026-09-12', 'scope': 'read-only aggregation, no new strategy runs',
           'checks': CHECKS, 'batch_metrics': {name: {m: metrics(v.values()) for m,v in data.items()} for name,data in batches.items()},
           'combined48': {m: metrics(v.values()) for m,v in combined.items()}, 'tail_audits_micro24': logs,
           'geometric_spot_checks': spots, 'input_sha256': INPUTS}
    (HERE / 'metrics_AI1.json').write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'checks': CHECKS, 'inputs': len(INPUTS), 'combined48': out['combined48']['f3'],
                      'f3_tail_min': st.mean(r['tail_s'] for r in f3)/60,
                      'f3_move_mean_s': st.mean(v for r in f3 for v in r['positive_moves_s']),
                      'clear_intervals_s': [st.mean(r['clear_interval_quartiles_s'][k] for r in f3) for k in range(4)]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
