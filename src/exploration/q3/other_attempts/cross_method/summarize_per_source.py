"""只读既有逐局结果，按方法/批次重算每源耗时和源数分布；不导入或运行策略。"""
import hashlib
import json
from pathlib import Path
import statistics as st
from collections import Counter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
Q3 = HERE.parent
INPUTS = {}
CACHE = {}


def read(p):
    p = p.resolve()
    if p not in CACHE:
        data = p.read_bytes()
        INPUTS[p.relative_to(ROOT).as_posix()] = hashlib.sha256(data).hexdigest()
        CACHE[p] = json.loads(data.decode('utf-8-sig'))
    return CACHE[p]


def raw_record(index):
    path, sep, name = index['result_path'].partition('#')
    data = read(ROOT/path)
    r = next(x for x in data if x['case'] == name) if sep else data
    for k in ('case', 'real_n', 'cleared', 'success', 'total_s'):
        assert r[k] == index[k], (path, k)
    assert 10 <= r['real_n'] <= 16
    assert 0 <= r['cleared'] <= r['real_n']
    assert abs(sum(r[k] for k in ('move_s', 'measure_s', 'switch_s', 'success_clear_s', 'fail_clear_s'))-r['total_s']) < 1e-5
    if r['success']:
        assert r['cleared'] == r['real_n']
        assert abs(r['per_source_s']-r['total_s']/r['real_n']) < 1e-6
    # Locate the saved input case, independently of the summary's N field.
    folder = (ROOT/path).parent
    found = False
    while folder.is_relative_to(Q3):
        cp = folder/'cases.json'
        if cp.exists():
            cases = read(cp)
            if isinstance(cases, list):
                match = next((c for c in cases if c.get('name') == r['case']), None)
                if match:
                    assert len(match['sources']) == r['real_n']
                    found = True
                    break
        folder = folder.parent
    assert found, ('missing saved case', path)
    return dict(r, result_path=index['result_path'])


def stats(rows):
    assert rows and all(r['success'] for r in rows)
    hist = Counter(r['real_n'] for r in rows)
    groups = {n: {'rounds': hist[n],
                  'total_min': st.mean(r['total_s']/60 for r in rows if r['real_n'] == n),
                  'per_source_min': st.mean(r['total_s']/60/n for r in rows if r['real_n'] == n)} for n in sorted(hist)}
    score = st.mean(r['total_s']/60/r['cleared'] for r in rows)
    assert abs(score - sum(g['rounds']*g['per_source_min'] for g in groups.values())/len(rows)) < 1e-10
    return {'rounds': len(rows), 'count_10_to_16': [hist[n] for n in range(10,17)],
            'source_count_sum': sum(r['real_n'] for r in rows),
            'total_min': st.mean(r['total_s']/60 for r in rows),
            'per_source_min': score,
            'pooled_per_source_min': sum(r['total_s']/60 for r in rows)/sum(r['real_n'] for r in rows),
            'uniform_N_per_source_min': st.mean(g['per_source_min'] for g in groups.values()) if len(groups) == 7 else None,
            'groups': groups}


def table(headers, rows):
    return '\n'.join(['| '+' | '.join(headers)+' |', '| '+' | '.join(['---']*len(headers))+' |']+
                     ['| '+' | '.join(map(str,row))+' |' for row in rows])


def main():
    index = read(HERE/'AI3_optimization_summary_20260912/metrics_AI3.json')
    batches = []
    for b in index['batches']:
        data = {m:[raw_record(r) for r in rows.values()] for m,rows in b['rows'].items()}
        for rows in data.values():
            assert {r['case'] for r in rows} == {r['case'] for r in next(iter(data.values()))}
        batches.append({'name':b['name'], 'note':b['note'], 'reference':b['reference'],
                        'versions':{m:stats(rows) for m,rows in data.items()},'rows':data})

    folder = Q3/'decision_pilot/runs/confirm_161100'
    cases = {c['name']:c for c in read(folder/'cases.json')}
    decision = {}
    for r in read(folder/'results.json'):
        n = len(cases[r['case']]['sources'])
        assert n == r['sources'] and r['success'] and abs(r['per_source_s']-r['total_s']/n)<1e-7
        if r['scan_s'] is not None:
            assert abs(r['scan_s']+r['service_s']-r['total_s'])<1e-7
        decision.setdefault(r['policy'],[]).append(dict(r,real_n=n,cleared=n))
    batches.insert(0,{'name':'中心逼近与阶段交界预演：12例','note':'种子161100—161111；四种完整方法同案配对，包含共享扫描前缀。',
                      'reference':'scan7_r60','versions':{m:stats(rows) for m,rows in decision.items()},'rows':decision})
    failures = [raw_record(r) for r in index['failures']]
    partials = []
    for r in index['partials']:
        raw = read(ROOT/r['result_path'])
        assert raw['total_s'] == r['total_s'] and raw['cleared'] == r['cleared']
        partials.append(r)
    # Verify raw input hashes recorded by the previous index, where available.
    compared = 0
    for path,digest in INPUTS.items():
        if path in index['inputs_sha256']:
            assert digest == index['inputs_sha256'][path], ('changed indexed input',path)
            compared += 1
    combined = next(b for b in batches if '48例描述性' in b['name'])
    paired = next(b for b in batches if '四例修复' in b['name'])
    source_pairs=[]
    for r in paired['rows']['f3']:
        if r['real_n']==16:
            small=next(x for x in paired['rows']['f3'] if x['case']==r['case']+'_n12')
            source_pairs.append({'case':r['case'],'N16_total_min':r['total_s']/60,'N12_total_min':small['total_s']/60})
    lines=['# 第三问各方法：平均每源耗时与测试分布','',
           '2026-09-12；只读取既有结果重新汇总。本表按方法对应批次统计，不代表所有方法都在同一套场景上测过。','',
           '## 统计定义','',
           '一轮是一个完整场景对一种策略的执行。先确认全部源清除，再计算当轮整局虚拟耗时T（含移动、扫描、切频、成功/失败清除和末尾查漏）除以当轮实际清除源数N；对K轮等权平均：A=(1/K)Σ(T_i/N_i)。单位分钟/源。它不是源被清除时刻的平均，也不是单次清除指令的5秒。',
           '总耗时之和除以总源数之和会让多源轮权重更高，本报告主列不用此口径。附加“源数等权”先在每种N内取均值，再对N=10,…,16七组等权平均；缺组时不估填，也不报告完整七组均值。该处理仅平衡N权重，不消除位置/误差/半径混杂。','',
           '常规输入生成器为N=10+seed%7，是随种子循环，不是每轮独立均匀抽N。24轮不可能把七种N分得完全相等；F系列48轮分布接近相等。人为压力组和近期小对照另列。所有完整成绩均属于本地自建模拟。','',
           '## 按批次列出全部已纳入版本','',
           '开发集、确认集、压力集及诊断单例分开，48例合并是已有两批的描述性合并，不是新增48轮。各行的“轮数”均指每个版本纳入该均值的场景数；对照版本共享场景不能重复算作独立场景。','']
    distribution=[]
    for j,b in enumerate(batches,1):
        v=next(iter(b['versions'].values()))
        distribution.append([j,b['name'],v['rounds'],*v['count_10_to_16']])
        lines += [f'### {j}. {b["name"]}','',b['note'],'',
                  'N=10—16的轮数依次为：'+str(v['count_10_to_16'])+'。','',
                  table(['版本','全清/纳入轮数','每源均值/分钟','同案参照每源/分钟','整局均值/分钟','N七组等权每源/分钟'],
                        [[m,f'{s["rounds"]}/{s["rounds"]}',f'{s["per_source_min"]:.6f}',f'{b["versions"][b["reference"]]["per_source_min"]:.6f}',f'{s["total_min"]:.6f}',
                          '缺组，不计算' if s['uniform_N_per_source_min'] is None else f'{s["uniform_N_per_source_min"]:.6f}'] for m,s in b['versions'].items()]),'']
    lines += ['## 源数分布总表','',table(['批次','名称','每版本轮数','10','11','12','13','14','15','16'],distribution),'',
              '## F3的48轮：源数与耗时','',table(['源数','轮数','整局平均分钟','每源平均分钟'],
                [[n,g['rounds'],f'{g["total_min"]:.6f}',f'{g["per_source_min"]:.6f}'] for n,g in combined['versions']['f3']['groups'].items()]),'',
              '这批样本中16源组总耗时较短，但各档不单调递减，不能将跨案例分组解释为源数的纯因果作用。','',
              '## 保留其余源的12/16源对照','',table(['原场景','12源总分钟','16源总分钟'],[[r['case'],f'{r["N12_total_min"]:.6f}',f'{r["N16_total_min"]:.6f}'] for r in source_pairs]),'',
              '两组都是12源总耗时更短；现有结果不支持“源越少总时间必然越多”。16源清完可直接利用公开上限停止；少于16源还需排除其他频道，这是可解释部分差异的机制，具体移动与测量决策也会改变。','',
              '## 未完成与统计范围','',
              f'索引中保留{len(failures)}项失败/计算到限记录和{len(partials)}项主动停止：信念树U1/T3七项未完成，另有S4修复前一次失败；不能用这些停止时耗时计算完成成绩。S4修复后的四例完整批次单列，不把失败记录丢弃。',
              '信念树M3完整开发8轮与冒烟1轮分开，U1/T3没有完整成绩。S系列中S2仅有诊断单例。R1/R2/R4为开发比较，R3另有24轮确认及8轮压力。F4仅有第二批24轮及8轮压力，不混入F1—F3的48轮合并。',
              '上述为用于方法比较的明确批次，不宣称已把目录中的所有调试、失败重启、反事实候选、源码快照或重复演示算成新增独立轮次。','',
              '## 本次核验','',f'按旧总结仅定位原始文件，主数字从逐轮JSON重新计算；核对每源比值、费用加总、全清字段与保存输入中的源数；{compared}份原输入SHA256与已有记录一致。中心逼近批次额外核对扫描前缀计入整局；其全清几何沿用原VALIDATION，本次未重新运行控制器或几何重放。',
              '复算脚本：[summarize_per_source.py](summarize_per_source.py)；机器结果：[PER_SOURCE_SUMMARY.json](PER_SOURCE_SUMMARY.json)。','']
    (HERE/'PER_SOURCE_SUMMARY.md').write_text('\n'.join(lines),encoding='utf-8')
    out={'definition':'mean over cases of total_s / cleared / 60, all-clear only','batches':batches,'source_pairs':source_pairs,
         'failures':failures,'partials':partials,'inputs_sha256':INPUTS,'verified_prior_input_hashes':compared}
    (HERE/'PER_SOURCE_SUMMARY.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'batches':len(batches),'raw_inputs':len(INPUTS),'prior_hashes_verified':compared,
                      'decision':batches[0]['versions'],'f3_48':combined['versions']['f3'],'pairs':source_pairs},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
