"""只读既有实验，生成AI3分组统计与时间账本；不导入策略、不启动仿真。"""
import hashlib
import json
import math
import statistics as st
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
Q3 = HERE.parent.parent
COSTS = ('move_s','measure_s','switch_s','success_clear_s','fail_clear_s')
INPUTS, RESULTS, LOGS = {}, {}, {}
BATCHES = []


def read(path, jsonl=False):
    blob = path.read_bytes()
    INPUTS[path.relative_to(ROOT).as_posix()] = hashlib.sha256(blob).hexdigest()
    text = blob.decode('utf-8-sig')
    return [json.loads(x) for x in text.splitlines() if x.strip()] if jsonl else json.loads(text)


def check(r):
    assert abs(sum(r[k] for k in COSTS)-r['total_s']) < 1e-5, r['case']
    assert 0 <= r['cleared'] <= r['real_n']
    if r['success']:
        assert r['cleared'] == r['real_n']
        assert abs(r['per_source_s']-r['total_s']/r['real_n']) < 1e-6


def result(path):
    key = path.relative_to(ROOT).as_posix()
    if key not in RESULTS:
        r = read(path)
        check(r)
        RESULTS[key] = dict(r, result_path=key)
    return RESULTS[key]


def patrol(run):
    path = Q3/'probability_patrol/runs'/run/'results.json'
    output = {}
    for r in read(path):
        check(r)
        key = path.relative_to(ROOT).as_posix()+'#'+r['case']
        RESULTS[key] = dict(r, result_path=key)
        output[r['case']] = RESULTS[key]
    return output


def modes(folder, names):
    index = read(folder/'summary.json')
    data = {m:{} for m in names}
    for row in index['rows']:
        for m in names:
            r = result(folder/row['case']/m/'result.json')
            assert abs(r['total_s']-row[m]['total_s']) < 1e-6
            data[m][r['case']] = r
    return data


def batch(name, data, ref, note, detailed=False, timed=False):
    sets = [set(x) for x in data.values()]
    assert sets and all(x == sets[0] for x in sets), name
    for c in sets[0]:
        assert len({(x[c]['seed'],x[c]['real_n'],x[c]['layout'],x[c]['noise']) for x in data.values()}) == 1
        assert all(x[c]['success'] for x in data.values()), 'failed runs must be separate'
    item = dict(name=name, data=data, ref=ref, note=note, detailed=detailed, timed=timed)
    BATCHES.append(item)
    return item


def percentile(values, p):
    x = sorted(values)
    z = (len(x)-1)*p
    lo, hi = math.floor(z), math.ceil(z)
    return x[lo]+(x[hi]-x[lo])*(z-lo)


def stats(rows):
    rs = list(rows)
    t = [r['total_s']/60 for r in rs]
    return dict(cases=len(rs), mean_min=st.mean(t), median_min=st.median(t),
                sd_min=st.stdev(t) if len(t)>1 else None, p95_min=percentile(t,.95), max_min=max(t),
                per_source_min=st.mean(r['total_s']/r['real_n']/60 for r in rs),
                **{k:st.mean(r[k] for r in rs) for k in COSTS})


def table(headers, rows):
    return '\n'.join(['| '+' | '.join(headers)+' |', '| '+' | '.join('---' for _ in headers)+' |']
                     + ['| '+' | '.join(str(x) for x in row)+' |' for row in rows])


def fmt(value):
    return '—' if value is None else f'{value:.3f}'


def batch_text(b):
    data, ref = b['data'], b['ref']
    text = [f"## {b['name']}",'',b['note'],'',f'节省参照为`{ref}`；以下均为完整全清结果。','']
    rows, aggregate = [], {}
    for mode, cases in data.items():
        m = stats(cases.values())
        ds = [(data[ref][c]['total_s']-r['total_s'])/60 for c,r in cases.items()]
        m.update(savings_min=st.mean(ds), wins=sum(x>1e-6 for x in ds), losses=sum(x < -1e-6 for x in ds), ties=sum(abs(x)<=1e-6 for x in ds))
        aggregate[mode] = m
        rows.append([mode, f"{m['cases']}/{m['cases']}", *[fmt(m[k]) for k in ('mean_min','per_source_min','median_min','sd_min','p95_min','max_min','savings_min')], f"{m['wins']}/{m['losses']}/{m['ties']}"])
    text += [table(['版本','全清','整局均值/分','每源均值/分','中位/分','标准差/分','P95/分','最慢/分','平均节省/分','胜/负/平'],rows),'']
    grouped = {}
    for field,label in [('real_n','源数'),('layout','分布'),('noise','误差机制')]:
        groups = sorted({r[field] for r in data[ref].values()})
        rows, grouped[field] = [], {}
        for key in groups:
            ms = {m:stats(r for r in rs.values() if r[field]==key) for m,rs in data.items()}
            grouped[field][str(key)] = ms
            rows.append([key,ms[ref]['cases'],*[f"{v['mean_min']:.3f} / {v['per_source_min']:.3f}" for v in ms.values()]])
        text += [f'### 按{label}分组','', '每格为“整局平均分钟 / 逐局每源平均分钟”；一例组不作总体推断。','', table([label,'案例数',*data],rows),'']
    if b['detailed']:
        rows = [[c,data[ref][c]['real_n'],*[fmt(rs[c]['total_s']/60) for rs in data.values()]] for c in data[ref]]
        text += ['### 逐例整局分钟','',table(['案例','N',*data],rows),'']
    return '\n'.join(text), dict(summary=aggregate, groups=grouped)


def audit(r):
    key = r['result_path']
    if key in LOGS:
        return LOGS[key]
    rows = read((ROOT/key).with_name('actions.jsonl'), True)
    assert len(rows) == r['actions']
    p, channel, total = (0.,0.), 1, 0.
    sums = dict.fromkeys(COSTS,0.)
    moves, costs, clear_times = [], [], []
    last_clear_index = None
    for i,row in enumerate(rows):
        c = dict.fromkeys(COSTS,0.)
        c['move_s'] = math.dist(p,row['position'])/5
        if c['move_s'] > 1e-8:
            moves.append(c['move_s'])
        if row['kind'] == 'measure':
            c['measure_s'] = 5.
            c['switch_s'] = float(channel != row['channel'])
            channel = row['channel']
        else:
            ok = row['response']['clear_result']=='success'
            c['success_clear_s' if ok else 'fail_clear_s'] = 5. if ok else 3.
        total += sum(c.values())
        assert abs(total-row['response']['virtual_time_s']) < 1e-5
        for k in COSTS:
            sums[k] += c[k]
            if 'independent_costs' in row:
                assert abs(c[k]-row['independent_costs'][k]) < 1e-5
        costs.append(c)
        if c['success_clear_s']:
            last_clear_index = i
            clear_times.append(total)
        p = row['position']
    assert len(clear_times) == r['cleared']
    assert all(abs(sums[k]-r[k])<1e-5 for k in COSTS)
    assert abs(total-r['total_s']) < 1e-5
    tail = {k:sum(c[k] for c in costs[last_clear_index+1:]) for k in COSTS} if last_clear_index is not None else None
    LOGS[key] = dict(case=r['case'], N=r['real_n'], actions=len(rows), moves_s=moves, sums=sums,
                     last_clear_step=last_clear_index+1 if last_clear_index is not None else None,
                     last_clear_s=clear_times[-1] if clear_times else None,
                     tail=tail if r['success'] else None,
                     remaining_actions=len(rows)-last_clear_index-1 if last_clear_index is not None else None)
    return LOGS[key]


def time_text(b):
    text = [f"## {b['name']}",'',b['note'],'']
    rows, info = [], {}
    for mode, rs in b['data'].items():
        logs = [audit(r) for r in rs.values()]
        moves = [v for log in logs for v in log['moves_s']]
        tails = [sum(log['tail'].values())/60 for log in logs]
        info[mode] = dict(nonzero_moves=len(moves),mean_move_s=st.mean(moves),median_move_s=st.median(moves),
                          p95_move_s=percentile(moves,.95), mean_tail_min=st.mean(tails), max_tail_min=max(tails),
                          mean_tail_move_min=st.mean(x['tail']['move_s']/60 for x in logs),
                          mean_tail_scan_switch_min=st.mean((x['tail']['measure_s']+x['tail']['switch_s'])/60 for x in logs),
                          cases_with_tail=sum(t>1e-6 for t in tails))
        v = info[mode]
        rows.append([mode,len(logs),v['nonzero_moves'],*[fmt(v[k]) for k in ('mean_move_s','median_move_s','p95_move_s','mean_tail_min','max_tail_min','mean_tail_move_min','mean_tail_scan_switch_min')]])
    text += [table(['版本','案例','非零移动数','单移均值/秒','单移中位/秒','单移P95/秒','尾段均值/分','尾段最慢/分','尾段移动/分','尾段测量切频/分'],rows),'',
             table(['版本','全程移动/分','全程扫描/分','全程切频/分','成功清除/分','失败清除/分'],
                   [[mode,*[fmt(st.mean(r[k]/60 for r in rs.values())) for k in COSTS]] for mode,rs in b['data'].items()]),'']
    if b['detailed']:
        text += ['### 逐例：总时间 / 最后成功清除后尾段（分钟）','',table(['案例','N',*b['data']],
            [[name,b['data'][b['ref']][name]['real_n'],*[f"{rs[name]['total_s']/60:.3f} / {sum(audit(rs[name])['tail'].values())/60:.3f}" for rs in b['data'].values()]] for name in b['data'][b['ref']]]),'']
    return '\n'.join(text), info


def main():
    runs = Q3/'probability_patrol/runs'
    names = {'baseline':'baseline_development_02','R1':'r1_development_01','R2_coverage':'r2_coverage_development',
             'R2_short':'r2_short_development','R2_edge':'r2_edge_development','R3':'r3_covering_development',
             'R4_1000':'r4_arc1000_development','R4_1200':'r4_arc1200_development','R4_1450':'r4_arc1450_development'}
    batch('共同前序：R1—R4开发12例',{m:patrol(run) for m,run in names.items()},'baseline','种子170100—170111；开发选择集，非独立确认。')
    batch('共同前序：R3独立24例',{'baseline':patrol('baseline_holdout_final'),'R3':patrol('r3_holdout_final')},'baseline','种子180100—180123；冻结后确认。')
    batch('共同前序：R3固定压力8例',{'baseline':patrol('baseline_stress_final'),'R3':patrol('r3_stress_final')},'baseline','种子190100—190107；N与误差机制绑定，不能拆作独立因果影响。')
    batch('共同前序：自适应第二站24例',modes(Q3/'adaptive_second/runs/confirm',['baseline','fixed','position','joint']),'fixed','种子280100—280123；同案比较位置及频道增量。')
    ref = Q3/'refinement/runs'
    first = modes(ref/'confirm',['baseline','current','f1','f2','f3'])
    second = modes(ref/'micro_confirm',['baseline','current','f1','f2','f3','f4'])
    batch('共同前序：F系列第一批24例',first,'current','种子310100—310123；current为自适应第二站策略。')
    batch('共同前序：F系列第二批24例',second,'current','种子320100—320123；F4调试后新确认。',timed=True)
    batch('共同前序：F系列压力8例',modes(ref/'stress',['baseline','current','f1','f2','f3','f4']),'current','固定压力190100—190107；不是新增随机分布。')
    batch('共同前序：F系列48例描述性合并',{m:dict(first[m],**second[m]) for m in first},'current','上述两批合并；不算新增运行，不包含没有首批成绩的F4。')
    tree = read(Q3/'belief_tree/runs/development_comparison.json')
    data = {m:{} for m in ('baseline','f3','m3')}
    for row in tree['rows']:
        for m in data:
            p = Path(row['versions'][m]['path'])
            r = result(p if p.is_absolute() else ROOT/p)
            assert abs(r['total_s']-row['versions'][m]['result']['total_s'])<1e-6
            data[m][r['case']] = r
    batch('共同前序：M3信念树开发8例',data,'f3','均匀、边缘、聚集、近共线各2例；只评价完成的M3，U1/T3未完成单列。',True,True)
    smoke = Q3/'belief_tree/runs/smoke_macro_loaded/uniform_hashed_330000'
    smoke_data = {m:{'uniform_hashed_330000':result(smoke/m/'result.json')} for m in ('baseline','m3')}
    smoke_data['f3'] = {'uniform_hashed_330000':result(Q3/'belief_tree/runs/smoke_importfix/uniform_hashed_330000/f3/result.json')}
    batch('共同前序：M3哈希误差冒烟单例',smoke_data,'f3','单例不能推断平均性能。',True,True)
    clear = Q3/'clearability'
    demo_name = 'uniform_hashed_186539142'
    demo = ref/'demo_f3_20260912'/demo_name/'f3'
    data = {'f3':{demo_name:result(demo/'result.json')}}
    for mode in ('s1','s2','s3','s4'):
        folder = 'fixed_demo' if mode=='s4' else 'diagnostic'
        data[mode] = {demo_name:result(clear/'runs'/folder/demo_name/mode/'result.json')}
    batch('AI3：新F3演示与S1—S4诊断单例',data,'f3','一次抽取种子186539142，16源；此后用于设计诊断，不是独立确认。',True,True)
    cases = read(clear/'fresh_cases.json')
    data = {m:{} for m in ('f3','s1','s3','s4')}
    for c in cases:
        for m in data:
            folder = 'fixed' if m=='s4' else 'fresh_loaded'
            data[m][c['name']] = result(clear/'runs'/folder/c['name']/m/'result.json')
    batch('AI3：S系列四例修复后复验',data,'f3','两组16源世界分别删去4源形成12源版本；S4据此修复后复跑，此批已不是未触碰确认集。S2没有四例成绩。',True,True)
    activation = clear/'runs/activation_only'
    data = {m:{} for m in ('f3','linear','sigmoid')}
    for i,c in enumerate(read(activation/'cases.json')):
        base = demo.parent if i==0 else clear/'runs/fresh_loaded'/c['name']
        data['f3'][c['name']] = result(base/'f3/result.json')
        for m in ('linear','sigmoid'):
            data[m][c['name']] = result(activation/c['name']/m/'result.json')
    batch('AI3：激活函数单因素五例',data,'f3','均为已看过的案例；F3无原生激活函数，linear和sigmoid使用同一新增筛选器，仅函数形状不同。',True,True)
    for stage, detail in [('development','5例既有案例比较λ=60/180/600，不是独立泛化确认。'),('confirmation','冻结λ=60后6个全新种子；没有继续调参。')]:
        out = Q3/'boundary_penalty/runs'/stage
        manifest = read(out/'manifest.json')
        data = {m:{} for m in ['f3']+[f'penalty{x:g}' for x in manifest['strengths_s']]}
        for c in read(out/'cases.json'):
            name = c['name']
            data['f3'][name] = result(ROOT/manifest['baselines_relative_to_repository'][name]/'result.json')
            for m in data:
                if m!='f3':data[m][name] = result(out/name/m/'result.json')
        batch('AI3：边界惩罚'+('开发5例' if stage=='development' else '独立6例'),data,'f3',detail,True,True)

    failures = []
    for p in sorted((Q3/'belief_tree/runs').rglob('result.json')):
        r = read(p)
        if not r['success']:
            r = result(p)
            failures.append(dict(r,record_kind='计算上限未完成'))
    r = result(clear/'runs/fresh_loaded/uniform_hashed_20260925_n12/s4/result.json')
    failures.append(dict(r,record_kind='修复前实现失败'))
    partials = []
    for folder in ('dev_merged','dev_biased','smoke_merged'):
        for p in sorted((Q3/'belief_tree/runs'/folder).rglob('progress.json')):
            if not (p.parent/'result.json').exists():
                r = read(p);check(r)
                partials.append(dict(r,result_path=p.relative_to(ROOT).as_posix(),record_kind='主动停止的部分记录'))

    intro = ['# AI3：不同源数、分布与误差下的性能','',
             '本页由只读脚本重算既有结果，没有启动新仿真。共同前序与AI3后续分批列出；不得跨批直接以均值排名。',
             '', '每源均值=mean(T_i/N_i)，非sum(T)/sum(N)。节省=同案参照−候选；正数更快。标准差为样本标准差，单例记—；P95线性插值，仅描述本样本。未完成记录不计入完成均值。',
             '', '常规源数由10+seed%7决定；源数分组同时改变了位置、半径、误差和路线。边缘与近共线通常R=1000米，均匀/聚集R为1000—1500米均匀假设，不能声称组间差异只来自分布。AI3四例16/12源组保留相同其余真源，但两个版本的观测、选点和路线会随反馈变化。','']
    metric_batches, time_batches = [], []
    for b in BATCHES:
        text, ms = batch_text(b)
        intro += [text,'']
        metric_batches.append(dict(name=b['name'],note=b['note'],reference=b['ref'],**ms,rows=b['data']))
    intro += ['## 未完成、失败与主动停止','',
              '下表是停止时已经花掉的虚拟时间，绝不是完成成绩；墙钟指本机计算等待。所有失败保留，不将成功子集均值冒充整批表现。','',
              table(['类型','案例/版本','清除/总源','已花虚拟分钟','墙钟分钟','原因'],
                    [[r['record_kind'],r['case']+'/'+Path(r['result_path']).parent.name,f"{r['cleared']}/{r['real_n']}",fmt(r['total_s']/60),fmt(r['wall_s']/60),r.get('failreason') or '用户要求停止，未生成完整结果'] for r in failures+partials]),'',
              '另有早期同名模块导入错误（belief_tree与clearability的启动目录），没有可计分的虚拟执行，不编造平均时间。旧S4失败已修复并全批复跑，但原失败记录仍保留。','',
              '前置scan7_r60布局筛选和中心逼近试验见[优化历程](01_AI3_优化历程.md)及其原始报告；没有把这些不同结构的旧汇总强行套进当前费用账本。']
    (HERE/'02_AI3_分组性能.md').write_text('\n'.join(intro)+'\n',encoding='utf-8')

    text = ['# AI3：移动、操作及最后查漏的时间尺度','',
            '只读取既有动作日志，按距离/5、测量5秒、必要切频1秒、成功清除5秒/失败3秒独立复算。未重新运行控制器，也未重新执行几何真值审计。',
            '', '单次移动排除0米动作，再合并同版本所有案例的非零移动；尾段定义为“最后一次成功清除之后到公开状态结束”。策略当时不知道真实源数，不能事后提前停。尾段为0也可能是查漏提前发生；尾段与移动分项重叠，不能相加。','']
    for b in BATCHES:
        if b['timed']:
            fragment, data = time_text(b)
            text += [fragment,'']
            time_batches.append(dict(name=b['name'],metrics=data))
    text += ['## 尺度与源数解释','',
             '100米移动20秒，1000米移动200秒。一次检测加一次切频共6秒，因此100米绕行就相当于约3.3次检测切频。必须连同未来路线的改变比较，不能仅按当前扫描次数评价。',
             '', '16源一旦全被发现，可用题面数量上限排除其他未知频道；少于16源时没有这条结束捷径。但AI3两组16/12源受控删除试验中，12源仍更快，说明不存在“16一定比12快”的规律。',
             '', 'S4原演示少32次扫描却多走10.312分钟；M3开发集末尾查漏均值约7.998分钟、F3约1.515分钟；边界惩罚确认集平均移动省37.029秒、扫描切频多25.333秒，净省12.695秒。这些是各自批次的账本，不跨批相加。']
    (HERE/'03_AI3_时间尺度与查漏.md').write_text('\n'.join(text)+'\n',encoding='utf-8')
    checks = dict(unique_result_records=len(RESULTS), paired_batch_tables=len(BATCHES),
                  unique_logs_recomputed=len(LOGS), actions_recomputed=sum(x['actions'] for x in LOGS.values()),
                  failure_records=len(failures),partial_records=len(partials),new_simulations=0)
    output = dict(scope='共同前序与AI3独立后续；只读重算，不改其他AI目录',checks=checks,
                  inputs_sha256=INPUTS,batches=metric_batches,time_batches=time_batches,logs=LOGS,
                  failures=failures,partials=partials)
    (HERE/'metrics_AI3.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(checks,ensure_ascii=False))


if __name__ == '__main__':
    main()
