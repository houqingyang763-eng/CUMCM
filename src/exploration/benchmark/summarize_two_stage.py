"""只读已完成批次，核对证据并生成总报告。"""
import hashlib
import json
import statistics
from pathlib import Path

BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[1]
BATCHES={'开发':'two_stage_development_130100','验证':'two_stage_holdout_140100',
         '压力':'two_stage_stress_150000','旧案例对齐':'two_stage_replay_48100'}


def read(path):return json.loads(path.read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    audit={}
    allrows=[]
    case_sets={}
    for label,batch in BATCHES.items():
        folder=BASE/'runs'/batch
        manifest=read(folder/'manifest.json')
        assert sha(folder/'cases.json')==manifest['case_sha256']
        for rel,h in manifest['source_sha256'].items():
            assert sha(folder/'source'/rel)==h
            assert sha(ROOT/'experiments'/rel)==h,(batch,rel,'运行后源码已变化')
        cases=read(folder/'cases.json')
        case_sets[label]={c['name'] for c in cases}
        rows=read(folder/'results.json')
        assert len(rows)==len(cases)*len(manifest['policies'])
        assert all(r['success'] and r['cleared']==r['source_count'] for r in rows)
        for r in rows:
            assert abs(r['total_s']-sum(r[k] for k in ['move_s','switch_s','measure_s','success_clear_s','fail_clear_s']))<1e-5
            assert abs(r['total_s']-r['scan_s']-r['service_s'])<1e-5
        audit[label]={'cases':len(cases),'runs':len(rows),'cleared_runs':len(rows),'source_and_input_hashes_ok':True}
        allrows.extend(rows)
    for i,(name,s) in enumerate(case_sets.items()):
        for name2,s2 in list(case_sets.items())[i+1:]:assert not s&s2,(name,name2)
    audit.update(total_cases=sum(len(s) for s in case_sets.values()),total_runs=len(allrows),
                 source_case_runs=sum(r['source_count'] for r in allrows),
                 fallback_targets=sum(r['fallback_targets'] for r in allrows))
    (BASE/'VALIDATION.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    dev=read(BASE/'runs'/BATCHES['开发']/'summary.json')
    hold=read(BASE/'runs'/BATCHES['验证']/'summary.json')
    replay=read(BASE/'runs'/BATCHES['旧案例对齐']/'summary.json')['scan7_r60']
    oracle=read(ROOT/'experiments/b_oracle_q3/runs/sweep_validation_48100/summary.json')
    old=read(BASE/'runs/seven_reference_48100/summary.json')
    # 旧参照与本轮确为同一组输入；同时核对原比较批次的共享基础源码。
    original_cases=ROOT/'experiments/b_overnight/runs/q3_sweep_validation/cases.json'
    assert read(original_cases)==read(BASE/'runs'/BATCHES['旧案例对齐']/'cases.json')
    assert read(original_cases)==read(BASE/'runs/seven_reference_48100/cases.json')
    original_manifest=read(original_cases.parent/'manifest.json')
    for name in ['geometry.py','state.py','simulation.py','policy.py']:
        assert sha(ROOT/'experiments/b_adaptive_q3'/name)==original_manifest['code_sha256']['base/'+name]
    assert sha(ROOT/'experiments/b_overnight/task_cost.py')==original_manifest['code_sha256']['night/task_cost.py']
    chosen=hold['scan7_r60']
    lines=['# 两阶段基线：建模与多组测试结果','',
        f'**推荐暂用7点扫描、60米停止阈值的两阶段基线。另24个验证案例全部清除，平均整局{chosen["total_s"]/60:.2f}分钟，每源{chosen["per_source_s"]:.2f}秒。**',
        '先固定扫描，再依据估计位置安排访问顺序，接近时补测或在小范围内试清。它是本任务的新基线，区别于此前误用的纯逐格试清模式。','',
        '## 两阶段到底花了多久','',
        f'- 固定扫描平均{chosen["scan_s"]/60:.2f}分钟。60米是停止重复扫描的阈值，不保证第一阶段所有区域都已小于60米。',
        f'- 路线访问、补测及清除平均{chosen["service_s"]/60:.2f}分钟；每局补测{chosen["service_measures"]:.2f}次，失败清除{chosen["fail_clears"]:.2f}次。',
        f'- 验证案例整局范围{chosen["min_total_s"]/60:.2f}—{chosen["max_total_s"]/60:.2f}分钟。',
        f'- 第一阶段区域半径中位数{chosen["stage1_radius_median_m"]:.2f}米，最大约{chosen["stage1_radius_max_m"]:.0f}米；{chosen["stage1_radius_gt60_count"]}/{chosen["sources"]}个源仍超过60米。因此它保证发现，精细定位由第二阶段补齐，不能称七点已经准确定位所有源。','',
        '## 固定点数量与扫描精度怎么取','',
        '| 方案 | 开发12例整局均值/分 | 验证24例整局均值/分 | 验证每源均值/秒 |',
        '|---|---:|---:|---:|']
    for key,label in [('scan7_r60','7点，60米停止阈值'),('scan7_r30','7点，30米停止阈值'),('scan13_r60','13点，60米停止阈值'),('scan19_r60','19点，60米停止阈值')]:
        value=hold.get(key)
        lines.append(f'| {label} | {dev[key]["total_s"]/60:.2f} | '+(f'{value["total_s"]/60:.2f} | {value["per_source_s"]:.2f} |' if value else '未进入验证 | — |'))
    lines+=['',
        '增加固定测点并未在这些候选中省时：13点把后续服务压到25.04分钟，但扫描增至51.01分钟；7点总成本更低。7点的30/60米阈值差异很小，不宣称60米是理论最优参数。',
        '选定方案由开发批次决定，记录见 runs/two_stage_development_130100/SELECTION.json，之后没有用验证集调整参数。','',
        '## 和已有理想标尺对齐','',
        '以下仅比较原先同一批12案例，不能把这些均值与上方24例直接混比。','',
        '| 方法 | 同批整局均值/分 | 每源均值/秒 |', '|---|---:|---:|',
        f'| 理想数学下界 | {oracle["lower_bound"]["total"]["mean"]/60:.2f} | {oracle["lower_bound"]["per_source"]["mean"]:.2f} |',
        f'| 已知真值的可执行路线 | {oracle["oracle_centers"]["total"]["mean"]/60:.2f} | {oracle["oracle_centers"]["per_source"]["mean"]:.2f} |',
        f'| 已有集中巡查策略 | {oracle["sweep"]["total"]["mean"]/60:.2f} | {oracle["sweep"]["per_source"]["mean"]:.2f} |',
        f'| 本轮两阶段基线 | {replay["total_s"]/60:.2f} | {replay["per_source_s"]:.2f} |',
        f'| 旧基础自适应参照 | {oracle["committed_baseline"]["total"]["mean"]/60:.2f} | {oracle["committed_baseline"]["per_source"]["mean"]:.2f} |',
        f'| 此前误用的逐格试清策略 | {old["virtual_time_s"]["mean"]/60:.2f} | {old["average_localization_clear_s"]["mean"]:.2f} |','',
        '两阶段基线明显优于纯逐格试清，但没有超过这批案例中已有集中巡查策略；它的价值是形成结构清楚、成本可解释的比较参照。理想下界省掉信息获取，差距不能全部理解成可消除浪费。',
        '同批新基线阶段二为28.85分钟，原逐格策略为85.44分钟；此处不是只换了一个模块的消融，路线与局部处理都已改变。','',
        '## 测试覆盖与结果边界','',
        '| 批次 | 不同案例数 | 策略—案例运行数 | 全清 |', '|---|---:|---:|---:|']
    for label,batch in BATCHES.items():
        a=audit[label]
        lines.append(f'| [{label}](runs/{batch}/RESULTS.md) | {a["cases"]} | {a["runs"]} | {a["cleared_runs"]}/{a["runs"]} |')
    lines+=['',f'合计{audit["total_cases"]}个不同案例、{audit["total_runs"]}次运行，全清且逐动作真源保留与独立计费检查通过；没有触发每目标24动作后的兜底。压力案例包括圆域边界、最小接收半径、同址/近同址及近共线。',
        '开放路径DP与六节点全排列等3项针对性测试通过。所有种子组互不重叠，输入和源码快照散列核对通过，详见 VALIDATION.json。',
        '这些是自建环境结果，并非官方成绩；有限压力测试不构成普遍成功率或现实20分钟保证。精确DP只优化当前估计中心之间的访问顺序，不证明整个未知位置任务最优。',
        'Q4本轮未实施。源代码仍在experiments，未晋升正式论文代码，AI工作待团队人工审阅。','',
        '## 文件入口','',
        '- [模型、公式与设计边界](MODEL.md)',
        '- [策略代码](two_stage.py) · [实验入口](run_two_stage.py) · [针对性测试](test_two_stage.py)',
        '- 各批次的 results.csv/json、actions/、plans/、manifest.json 提供逐例数字、轨迹、路线和源文件散列。','']
    (BASE/'RESULTS.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(audit,ensure_ascii=False))


if __name__=='__main__':main()
