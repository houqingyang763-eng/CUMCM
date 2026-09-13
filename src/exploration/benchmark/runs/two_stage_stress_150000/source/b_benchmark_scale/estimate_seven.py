"""复用已有七点 reference 模式，本地测算；不接官方模拟器。"""
import argparse
import csv
import hashlib
import json
import math
import platform
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'experiments/b_adaptive_q3'
sys.path.insert(0, str(BASE))
from run_local import run_case
from simulation import Scenario
from policy import Config


def dump(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    if ROOT / 'experiments/b_benchmark_scale' not in out.parents:
        raise ValueError('输出必须在本实验目录内')
    out.mkdir(parents=True, exist_ok=False)
    (out / 'actions').mkdir()
    (out / 'source').mkdir()
    cases_file = ROOT / 'experiments/b_overnight/runs/q3_sweep_validation/cases.json'
    comparison_file = ROOT / 'experiments/b_oracle_q3/runs/sweep_validation_48100/summary.json'
    cases = json.loads(cases_file.read_text(encoding='utf-8'))
    (out / 'cases.json').write_bytes(cases_file.read_bytes())
    for path in [*BASE.glob('*.py'), Path(__file__)]:
        (out / 'source' / path.name).write_bytes(path.read_bytes())
    dump(out / 'manifest.json', {
        'python': platform.python_version(), 'policy': 'BasePolicy(reference_only=True)',
        'config': Config().to_dict(), 'case_source': str(cases_file.relative_to(ROOT)),
        'case_sha256': digest(cases_file),
        'source_sha256': {p.name: digest(p) for p in (out / 'source').glob('*.py')},
        'prior_oracle_summary_sha256': digest(comparison_file),
        'scope': '已有自建12案例诊断；未新抽案例，未调用官方模拟器',
    })
    rows = []
    for raw in cases:
        scenario = Scenario.from_dict(raw)
        trace = out / 'actions' / (scenario.name + '.jsonl')
        result = run_case(scenario, reference_only=True, trace_path=trace)
        actions = [json.loads(line) for line in trace.read_text(encoding='utf-8').splitlines()]
        last_measure = max(i for i, a in enumerate(actions) if a['kind'] == 'measure')
        discovery = actions[last_measure]['response']['virtual_time_s']
        result.update(discovery_phase_s=discovery,
                      after_discovery_s=result['virtual_time_s'] - discovery,
                      success_clear_s=5 * result['cleared'], fail_clear_s=3 * result['failed_clears'])
        assert result['success'], result['error']
        assert result['cleared'] == result['source_count']
        assert result['measure_count'] <= 140
        assert result['scan_position_count'] <= 7
        assert all(a['reason'].startswith('fallback') for a in actions)
        assert abs(result['clear_s'] - result['success_clear_s'] - result['fail_clear_s']) < 1e-7
        rows.append(result)
        dump(out / 'results.json', rows)
        print(json.dumps({k: result[k] for k in ['case', 'success', 'virtual_time_s', 'wall_time_s']}, ensure_ascii=False), flush=True)
    # 每局等权，题面每源指标与整局指标分别计算。
    metrics = ['virtual_time_s', 'average_localization_clear_s', 'discovery_phase_s',
               'after_discovery_s', 'move_s', 'switch_s', 'measure_s', 'success_clear_s',
               'fail_clear_s', 'failed_clears', 'measure_count', 'wall_time_s']
    summary = {k: {'mean': statistics.mean(r[k] for r in rows),
                   'min': min(r[k] for r in rows), 'max': max(r[k] for r in rows)} for k in metrics}
    summary['cases'] = len(rows)
    summary['sources'] = sum(r['source_count'] for r in rows)
    summary['full_clear_cases'] = sum(r['success'] for r in rows)
    summary['worst_quarter_per_source_s'] = statistics.mean(sorted(
        (r['average_localization_clear_s'] for r in rows), reverse=True)[:math.ceil(len(rows)/4)])
    summary['full_seven_scan'] = {'route_m': 7200, 'move_s': 1440, 'detections': 140,
                                'detect_s': 700, 'switch_s': 139, 'total_s': 2279}
    summary['coverage_radius_m'] = math.sqrt(1800**2 + 1200**2 - 2*1800*1200*math.cos(math.pi/6))
    assert summary['coverage_radius_m'] < 1000
    dump(out / 'summary.json', summary)
    with (out / 'results.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    mean = lambda key: summary[key]['mean']
    lines = [
        '# 七点覆盖基线耗时估计', '',
        '复用 BasePolicy(reference_only=True)，关闭自适应候选评分。不是新编固定巡查策略，也不是旧 committed_baseline。',
        '每次在仍缺检测的七点/未知频道中选即时移动加检测费用最小的一项；同一点先做完未知频道。发现后不继续测向，使用已有保守区域与蛇形小格逐个清除；区域足够小时直接认证清除。near 反馈可原地优先清除。', '',
        f'已有同一批 {len(rows)} 个自建案例全清，共 {summary["sources"]} 个源。平均整局 **{mean("virtual_time_s")/60:.2f} 分钟**；逐局每源用时均值 **{mean("average_localization_clear_s"):.2f} 秒/源**。',
        f'整局范围 {summary["virtual_time_s"]["min"]/60:.2f}—{summary["virtual_time_s"]["max"]/60:.2f} 分钟；最慢四分之一的每源均值 {summary["worst_quarter_per_source_s"]:.2f} 秒。范围是本批样本范围，不是所有场景的上下界。', '',
        '## 为什么七点覆盖不等于整局38分钟', '',
        '固定从圆心到半径1200米的六边形顶点，再沿五条相邻边走完：路程1200+5×1200=7200米，移动24分钟。',
        '每点按1至20号扫满：140次检测700秒、139次切频139秒，合计2279秒，即37分59秒。此处忽略中途near清除，且不返回原点。这是该满扫描计划的准确账本，不是任意路线的普遍上界。',
        '实际参考策略发现某频道后不再扫它，实际发现费用通常更低；但之后还有移动到源附近和多次光学试清的费用。', '',
        '| 阶段 | 同批平均分钟 |', '|---|---:|',
        f'| 起步至最后一次发现检测（含偶发原地near清除） | {mean("discovery_phase_s")/60:.2f} |',
        f'| 后续逐个定位清除 | {mean("after_discovery_s")/60:.2f} |',
        f'| 合计 | {mean("virtual_time_s")/60:.2f} |', '',
        '| 费用类别 | 同批平均分钟 |', '|---|---:|',
    ]
    for label, key in [('全部移动', 'move_s'), ('检测', 'measure_s'), ('切频', 'switch_s'),
                       ('成功清除', 'success_clear_s'), ('失败光学尝试', 'fail_clear_s')]:
        lines.append(f'| {label} | {mean(key)/60:.2f} |')
    lines += ['', '## 逐例', '', '| 案例 | 源数 | 整局分钟 | 每源秒 | 发现分钟 | 失败试清次数 |', '|---|---:|---:|---:|---:|---:|']
    for r in rows:
        lines.append(f'| {r["case"]} | {r["source_count"]} | {r["virtual_time_s"]/60:.2f} | {r["average_localization_clear_s"]:.2f} | {r["discovery_phase_s"]/60:.2f} | {r["failed_clears"]} |')
    lines += ['', '## 复现与边界', '',
              '逐动作保留真源的状态审计、全清检查、独立费用账本、检测点与动作来源检查均在本批实际执行。源数、布局、半径与固定误差场沿用此前12案例；策略看不到真值。',
              '误差场为自建smooth/biased/hashed并含两位小数舍入，不代表官方分布。已看过的案例用于配对诊断，不声称未见验证。未运行正式测试或官方演练。',
              '这里的朴素基线通过光学逐格尝试完成定位，可能比加入交会定位的基线慢得多；论文应准确命名，不把提升全归于七点布局，也不称本批最大值为理论最坏时间。',
              '原始逐动作记录见 actions/，结果见 results.json/csv，输入与源码散列见 manifest.json，源码快照见 source/。',
              '从项目根运行：py -3.13 experiments/b_benchmark_scale/estimate_seven.py --output experiments/b_benchmark_scale/runs/一个尚不存在的新批次目录',
              '本结果为AI实现与自检，待团队人工复核；未晋升src。', '']
    (out / 'RESULTS.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
