"""只读既有结果和动作账本，重建 AI2 的 02、03 与机器记录；不运行策略。"""
import hashlib
import json
import math
import statistics as st
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
Q3 = ROOT / 'experiments/b_q3'
COSTS = ('move_s', 'measure_s', 'switch_s', 'success_clear_s', 'fail_clear_s')
INPUTS, PATHS = {}, {}
CHECKS = dict(result_records=0, paired_batches=0, actions_recomputed=0)


def read(path, jsonl=False):
    data = path.read_bytes()
    INPUTS[path.relative_to(ROOT).as_posix()] = hashlib.sha256(data).hexdigest()
    text = data.decode('utf-8-sig')
    return [json.loads(x) for x in text.splitlines() if x.strip()] if jsonl else json.loads(text)


def check(r, complete=True):
    assert abs(sum(r[k] for k in COSTS) - r['total_s']) < 1e-5, r['case']
    assert r['cleared'] <= r['real_n']
    if complete:
        assert r['success'] and r['cleared'] == r['real_n'], r['case']
        assert abs(r['per_source_s'] - r['total_s'] / r['real_n']) < 1e-6
    else:
        assert not r['success']
    CHECKS['result_records'] += 1


def result(path, complete=True):
    r = read(path)
    check(r, complete)
    PATHS[id(r)] = path
    return r


def patrol(run):
    path = Q3 / 'probability_patrol/runs' / run / 'results.json'
    rows = read(path)
    for r in rows:
        check(r)
        PATHS[id(r)] = path
    return {r['case']: r for r in rows}


def modes(folder, names):
    index = read(folder / 'summary.json')
    out = {m: {} for m in names}
    for item in index['rows']:
        for m in names:
            r = result(folder / item['case'] / m / 'result.json')
            assert abs(item[m]['total_s'] - r['total_s']) < 1e-6
            out[m][r['case']] = r
    return out


def paired(data):
    keys = [set(v) for v in data.values()]
    assert all(k == keys[0] for k in keys)
    for case in keys[0]:
        assert len({(v[case]['seed'], v[case]['real_n'], v[case]['layout'], v[case]['noise']) for v in data.values()}) == 1
    CHECKS['paired_batches'] += 1


def pct(values, p):
    a = sorted(values)
    x = (len(a) - 1) * p
    lo, hi = math.floor(x), math.ceil(x)
    return a[lo] + (a[hi] - a[lo]) * (x - lo)


def metrics(rows):
    rs = list(rows)
    t = [r['total_s'] / 60 for r in rs]
    return dict(n=len(rs), mean=st.mean(t), median=st.median(t),
                sd=st.stdev(t) if len(t) > 1 else None, p95=pct(t, .95), worst=max(t),
                per_source=st.mean(r['total_s'] / r['real_n'] / 60 for r in rs),
                **{k: st.mean(r[k] / 60 for r in rs) for k in COSTS})


def f(x):
    return '—' if x is None else f'{x:.3f}'


def table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(headers) + ' |', '| ' + ' | '.join(['---'] * len(headers)) + ' |']
                     + ['| ' + ' | '.join(map(str, row)) + ' |' for row in rows])


def section(title, data, reference, note):
    out = [f'## {title}', '', note, '', f'节省列以 `{reference}` 为参照，正数更快；以下均为完整全清结果。', '']
    rows = []
    for mode, cases in data.items():
        m = metrics(cases.values())
        ds = [(data[reference][c]['total_s'] - r['total_s']) / 60 for c, r in cases.items()]
        rows.append([mode, f'{m["n"]}/{m["n"]}', *[f(m[k]) for k in ('mean', 'per_source', 'median', 'sd', 'p95', 'worst')],
                     f(st.mean(ds)), f'{sum(x>1e-6 for x in ds)}/{sum(x< -1e-6 for x in ds)}/{sum(abs(x)<=1e-6 for x in ds)}'])
    out += [table(['版本', '全清/案例数', '整局均值/分', '每源均值/分', '中位/分', '标准差/分', 'P95/分', '最慢/分', '平均节省/分', '胜/负/平'], rows), '']
    if len(next(iter(data.values()))) > 1:
        for field, label in [('real_n', '源数'), ('layout', '分布'), ('noise', '误差机制')]:
            out += [f'### 按{label}分组', '', '各版本单元格为“整局均值 / 每源均值”，单位分钟。每行样本数是场景数。', '']
            groups = sorted({r[field] for r in next(iter(data.values())).values()})
            rows = []
            for group in groups:
                ms = [metrics(r for r in cases.values() if r[field] == group) for cases in data.values()]
                rows.append([group, ms[0]['n'], *[f'{m["mean"]:.3f} / {m["per_source"]:.3f}' for m in ms]])
            # 每个分组按案例数加权后，必须回到原总体均值。
            for cases in data.values():
                ms = [metrics(r for r in cases.values() if r[field] == g) for g in groups]
                assert abs(sum(m['mean'] * m['n'] for m in ms) / sum(m['n'] for m in ms) - metrics(cases.values())['mean']) < 1e-9
            out += [table([label, '案例数', *data], rows), '']
    return '\n'.join(out)


def audit(r):
    path = PATHS[id(r)].with_name('actions.jsonl')
    logs = read(path, True)
    assert len(logs) == r['actions']
    pos, channel, total = (0., 0.), 1, 0.
    sums = {k: 0. for k in COSTS}
    moves, clears = [], []
    for idx, a in enumerate(logs):
        costs = a['independent_costs']
        calculated = {k: 0. for k in COSTS}
        calculated['move_s'] = math.dist(pos, a['position']) / 5
        if a['kind'] == 'measure':
            calculated['measure_s'] = 5.
            calculated['switch_s'] = float(channel != a['channel'])
            channel = a['channel']
        else:
            assert a['kind'] == 'clear'
            key = 'success_clear_s' if a['response']['clear_result'] == 'success' else 'fail_clear_s'
            calculated[key] = 5. if key == 'success_clear_s' else 3.
        for k in COSTS:
            assert abs(calculated[k] - costs[k]) < 1e-5, (path, idx, k)
            sums[k] += calculated[k]
        total += sum(calculated.values())
        assert abs(total - a['response']['virtual_time_s']) < 1e-5
        if calculated['move_s'] > 1e-8:
            moves.append(calculated['move_s'])
        if calculated['success_clear_s']:
            clears.append((idx, total))
        pos = tuple(a['position'])
    assert len(clears) == r['cleared']
    assert abs(total - r['total_s']) < 1e-5
    for k in COSTS:
        assert abs(sums[k] - r[k]) < 1e-5
    CHECKS['actions_recomputed'] += len(logs)
    last, clear_time = clears[-1]
    tail = {k: sum(a['independent_costs'][k] for a in logs[last+1:]) for k in COSTS}
    assert abs(sum(tail.values()) - (total - clear_time)) < 1e-5
    return dict(case=r['case'], real_n=r['real_n'], layout=r['layout'], noise=r['noise'], moves_s=moves,
                last_clear_step=logs[last]['step'], last_clear_s=clear_time, tail_s=sum(tail.values()),
                tail_actions=len(logs)-last-1, tail_costs=tail)


def main():
    batches = {}
    def add(key, title, data, ref, note):
        paired(data)
        batches[key] = dict(title=title, data=data, reference=ref, note=note)

    development = {'baseline': patrol('baseline_development_02')}
    for name, run in [('R1', 'r1_development_01'), ('R2_coverage', 'r2_coverage_development'),
                      ('R2_short', 'r2_short_development'), ('R2_edge', 'r2_edge_development'),
                      ('R3', 'r3_covering_development'), ('R4_1000', 'r4_arc1000_development'),
                      ('R4_1200', 'r4_arc1200_development'), ('R4_1450', 'r4_arc1450_development')]:
        development[name] = patrol(run)
    add('patrol_dev', 'R1—R4：同一12例开发比较', development, 'baseline', '开发集用于选择布局和后续结构，不能作为独立确认。种子170100—170111。')
    add('patrol_confirm', 'R3：独立24例确认', {'baseline': patrol('baseline_holdout_final'), 'R3': patrol('r3_holdout_final')}, 'baseline', '种子180100—180123；冻结后确认。')
    add('patrol_stress', 'R3：固定8例压力检查', {'baseline': patrol('baseline_stress_final'), 'R3': patrol('r3_stress_final')}, 'baseline', '种子190100—190107；极端边界、小半径、同址和窄共线，源数与误差机制绑定。')
    add('adaptive_pilot', '自适应第二站：4例先导', modes(Q3/'adaptive_second/runs/pilot', ['baseline','fixed','position','joint']), 'fixed', '种子270100—270103，均为hashed；只用于跑通和诊断。')
    add('adaptive_confirm', '自适应第二站：独立24例', modes(Q3/'adaptive_second/runs/confirm', ['baseline','fixed','position','joint']), 'fixed', '种子280100—280123；频道联合版应与position看增量，不能只与fixed比较。')
    ref = Q3/'refinement/runs'
    add('refine_dev', 'F1—F3：修正后的5例开发', modes(ref/'development_corrected', ['current','f1','f2','f3']), 'current', '既有演示及反例用于开发；旧development含队列触发缺陷，保留但不作为修正版本成绩。')
    add('refine_first', 'F1—F3：第一批24例', modes(ref/'confirm', ['baseline','current','f1','f2','f3']), 'current', '种子310100—310123。对冻结F1—F3为确认集；之后用于F4诊断，不能再作为F4确认。')
    add('refine_second', 'F1—F4：第二批新24例', modes(ref/'micro_confirm', ['baseline','current','f1','f2','f3','f4']), 'current', '种子320100—320123；F4修正后的新确认集。')
    add('refine_stress', 'F1—F4：固定8例压力检查', modes(ref/'stress', ['baseline','current','f1','f2','f3','f4']), 'current', '重复使用190100—190107压力场景，不能与R3压力集合计成16个独立场景。')
    add('refine_random', '一次随机审查：1392164241', modes(ref/'random_audit', ['current','f1','f3','f4']), 'current', '16源，均匀布局、hashed误差；单场景用于逐步诊断，不是总体性能验证。')

    b = Q3/'belief_tree/runs'
    index = read(b/'development_comparison.json')
    tree = {m: {} for m in ('baseline','f3','m3')}
    caps = []
    for item in index['rows']:
        case = item['case']['name']
        for m in tree:
            entry = item['versions'][m]
            p = Path(entry['path'])
            r = result(p if p.is_absolute() else ROOT/p)
            assert abs(r['total_s'] - entry['result']['total_s']) < 1e-6
            tree[m][case] = r
        if 't3' in item['versions']:
            entry = item['versions']['t3']
            p = Path(entry['path'])
            r = result(p if p.is_absolute() else ROOT/p, False)
            caps.append(dict(mode='T3', result=r, status='计算上限，未完成'))
    add('tree_dev', 'M3：8例完整开发比较', tree, 'f3', '330010/13/16/19为smooth，330011/14/17/20为biased；每布局2例。不是独立确认集。')
    smoke_case = 'uniform_hashed_330000'
    smoke = {}
    for m, folder in [('baseline','smoke_macro_loaded'),('f3','smoke_importfix'),('m3','smoke_macro_loaded')]:
        smoke[m] = {smoke_case: result(b/folder/smoke_case/m/'result.json')}
    add('tree_smoke', 'M3：另一个均匀/哈希冒烟', smoke, 'f3', '16源，种子330000。与8开发例分列，不能用9例冒充预设独立确认。')
    caps.insert(0, dict(mode='U1', result=result(b/'smoke_merged'/smoke_case/'u1/result.json', False), status='计算上限，未完成'))
    canceled = []
    for folder in ('dev_merged','smoke_merged'):
        stop = read(b/folder/'STOPPED.json')
        for item in stop['pending']:
            r = item['progress']
            check(r, False)
            canceled.append(dict(mode='T3', result=r, status='主动停止，未完成'))
    assert len(caps) == 7 and len(canceled) == 3

    out = ['# AI2：按源数、分布和误差分组的性能', '',
           '本页由 [rebuild_metrics_AI2.py](rebuild_metrics_AI2.py) 只读原始结果生成。共同前序与AI2信念树后续分批列出；没有运行新算法或生成新场景。', '',
           '每源均值=mean(T_i/N_i)，单位分钟/源；不是sum(T)/sum(N)。节省=参照减候选。单例标准差记为—；P95采用线性插值，仅为样本描述。失败及主动停止在末尾单列，不把未完成耗时当成绩。', '',
           '源数由种子决定，组间同时改变了位置、半径和误差；边缘/近共线通常固定R=1000，均匀/聚集为R∈[1000,1500]均匀。因此不能将组间差异解释成源数或布局的独立因果效应。压力组N=10与zero、N=16与biased绑定。定义见 [01_AI2_优化历程.md](01_AI2_优化历程.md)。', '']
    for v in batches.values():
        out += [section(v['title'], v['data'], v['reference'], v['note'])]
    out += ['## M3开发：逐例比较与恶化量', '',
            table(['案例','N','baseline/分','F3/分','M3/分','M3比F3多耗/分'],
                  [[c,tree['f3'][c]['real_n'],*[f(tree[m][c]['total_s']/60) for m in tree],f((tree['m3'][c]['total_s']-tree['f3'][c]['total_s'])/60)] for c in tree['f3']]), '',
            '## U1/T3：计算到限与主动停止，均无完整成绩', '',
            '以下虚拟时间仅表示停止前已经支付的费用；不可与全清均值排名，也不可由此断言其完整虚拟表现必然较差。墙钟计时独立于题面虚拟时间。', '',
            table(['版本','案例','状态','已清/真实N','已花虚拟分钟','动作数','本地墙钟分钟'],
                  [[x['mode'],x['result']['case'],x['status'],f'{x["result"]["cleared"]}/{x["result"]["real_n"]}',f(x['result']['total_s']/60),x['result']['actions'],f(x['result']['wall_s']/60)] for x in caps+canceled]), '',
            'STOPPED.json中的中文reason字段已有编码损坏，本表使用可正常读取的结构化case/progress与本轮原REPORT交叉核对，未修改原文件。未合并反馈节点的旧原型、导入失败、重复参照执行也均不并入完整成绩；详见04。', '',
            '## 数据入口与复算范围', '',
            '- [R1—R4原始运行目录](../../probability_patrol/runs)',
            '- [自适应第二站原始运行目录](../../adaptive_second/runs)',
            '- [F系列原始运行目录](../../refinement/runs)',
            '- [信念树逐案例索引](../../belief_tree/runs/development_comparison.json)',
            '- [本次输入散列、全部逐局数据和校验计数](metrics_AI2.json)', '',
            '该汇总不读取AI1的metrics，也不引用AI1独立后续结果为AI2成果。原始报告中的bootstrap区间在01/04保留其原批次及口径；本次未重新抽样计算新的置信区间。']
    (HERE/'02_AI2_分组性能.md').write_text('\n'.join(out)+'\n', encoding='utf-8')

    audits = {}
    for name in ('refine_second','tree_dev','tree_smoke'):
        audits[name] = {m: [audit(r) for r in cases.values()] for m,cases in batches[name]['data'].items()}
    out = ['# AI2：时间尺度、费用分解与最终查漏', '',
           '由既有动作坐标和反馈独立重算距离/5、扫描5秒、切频1秒、成功清除5秒、失败清除3秒；未调用模拟器或控制器。', '',
           '“最终查漏尾段”定义为最后一次真实成功清除后至算法合法结束，含排队中的服务测量。它是事后评估口径，算法当时不知道真源总数。不能只统计phase=completion，也不能用提前清完的真实时刻代替合法结束。', '',
           '只对非零移动计算单次移动尺度，同站0秒动作不进分母。合并移动均值=总移动秒数/非零移动次数，不是先算每局移动均值再平均。尾段与移动/扫描费用是重叠分解，不能相加。', '']
    for key, per_mode in audits.items():
        v = batches[key]
        out += [f'## {v["title"]}', '', '### 全程费用（平均分钟/局）', '',
                table(['版本','移动','扫描','切频','成功清除','失败清除','整局'],
                      [[m,*[f(metrics(rs.values())[k]) for k in COSTS],f(metrics(rs.values())['mean'])] for m,rs in v['data'].items()]), '',
                '### 移动与查漏尺度', '']
        rows = []
        for m, rs in per_mode.items():
            moves = [x for r in rs for x in r['moves_s']]
            rows.append([m,len(rs),len(moves),f(len(moves)/len(rs)),f(st.mean(moves)),f(st.median(moves)),f(pct(moves,.95)),
                         f(st.mean(r['tail_s'] for r in rs)/60),f(max(r['tail_s'] for r in rs)/60),sum(r['tail_s']>1e-8 for r in rs)])
        out += [table(['版本','案例数','总移动次数','每局移动次数','单移均值/秒','单移中位/秒','单移P95/秒','尾段均值/分','尾段最慢/分','有尾段局数'],rows),'']
        mode = 'm3' if 'm3' in per_mode else 'f3'
        for field,label in [('real_n','源数'),('layout','分布')]:
            rs = per_mode[mode]
            rows=[]
            for g in sorted({r[field] for r in rs}):
                group=[r for r in rs if r[field]==g]
                rows.append([g,len(group),f(st.mean(r['tail_s'] for r in group)/60),f(st.mean(r['tail_costs']['move_s'] for r in group)/60),
                             f(st.mean(r['tail_costs']['measure_s']+r['tail_costs']['switch_s'] for r in group)/60)])
            out += [f'### {mode}按{label}的尾段', '',table([label,'案例数','尾段/分','其中移动/分','其中扫描切频/分'],rows),'']
    out += ['## M3开发逐局：提前清完和合法结束的差别', '',
            table(['案例','N','最后成功步','最后清除时刻/分','尾段/分','尾段移动/分','F3尾段/分'],
                  [[r['case'],r['real_n'],r['last_clear_step'],f(r['last_clear_s']/60),f(r['tail_s']/60),f(r['tail_costs']['move_s']/60),
                    f(next(x['tail_s'] for x in audits['tree_dev']['f3'] if x['case']==r['case'])/60)] for r in audits['tree_dev']['m3']]), '',
            '## 解释这些尺度', '',
            '- 移动100米=20秒，1000米=200秒；一个新增停留若多走500米，就需靠约17次“检测+换频”的6秒操作才能抵消。还必须保留全清证据。',
            '- 两次失败再成功的操作费是3+3+5=11秒，但不同清除圆心间的移动另算；不能只与一次检测5秒比较。',
            '- M3开发均值：移动次数28→39.25，单次移动85.65→67.56秒，总移动却增加4.226分钟。更小的步子没有构成更短的路线。',
            '- 同批最终尾段1.515→7.998分钟，和总移动多4.226分钟重叠；不能把两项相加当作总退步。总退步是4.543分钟。',
            '- F3第二批24例与M3开发8例是不同场景。两批F3尾段均值不同属批次差异，不能解释为同版本代码再次改动。', '',
            '## 证据边界', '',
            '逐步反馈和全清几何的历史核验分别保存在 [refinement/VALIDATION.json](../../refinement/VALIDATION.json) 与 [belief_tree/VALIDATION.json](../../belief_tree/VALIDATION.json)。本次重新核对的是坐标计费、操作费、累计账本、最后成功时刻及分组统计；未重新证明所有几何定理或运行任何新策略。']
    (HERE/'03_AI2_时间尺度与查漏.md').write_text('\n'.join(out)+'\n', encoding='utf-8')
    payload = dict(owner='AI2', generated_date='2026-09-12', scope='existing local results only', checks=CHECKS,
                   inputs_sha256=INPUTS, batches=batches, incomplete=caps, canceled=canceled, action_audits=audits)
    (HERE/'metrics_AI2.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(checks=CHECKS, inputs=len(INPUTS), batches={k:{m:metrics(rs.values())['mean'] for m,rs in v['data'].items()} for k,v in batches.items()}),ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
