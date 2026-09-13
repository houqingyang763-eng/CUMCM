"""仅汇总已落盘小改试验；不调用策略、环境或状态审计器。"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from statistics import mean

PROJECT = Path(__file__).resolve().parents[3]
ROOT = PROJECT / 'outputs/experiments/q4/micro_changes'
TOLERANCE_S = 1e-4
TARGETS = (943004, 944001)


def load(path):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def status(result, scene):
    if result is None:
        return 'missing'
    assert result['case'] == scene['name'] and result['seed'] == scene['seed']
    return ('all_clear' if result.get('success') is True
            and result.get('independent_audit_passed') is True
            and result.get('cleared') == len(scene['sources']) else 'failed')


def statistics(rows):
    pairs = [r for r in rows if r['delta_s'] is not None]
    regressions = sorted((r for r in pairs if r['outcome'] == 'regression'),
                         key=lambda r: r['delta_s'], reverse=True)
    return dict(expected=len(rows), reference_status=dict(Counter(r['reference_status'] for r in rows)),
                candidate_status=dict(Counter(r['candidate_status'] for r in rows)),
                all_clear_pairs=len(pairs), wins=sum(r['outcome'] == 'win' for r in pairs),
                ties=sum(r['outcome'] == 'tie' for r in pairs), regressions=len(regressions),
                complete=len(pairs) == len(rows),
                mean_delta_s=mean(r['delta_s'] for r in pairs) if pairs else None,
                mean_delta_per_source_s=mean(r['delta_per_source_s'] for r in pairs) if pairs else None,
                reference_mean_s=mean(r['reference_time_s'] for r in pairs) if pairs else None,
                candidate_mean_s=mean(r['candidate_time_s'] for r in pairs) if pairs else None,
                maximum_regression_s=regressions[0]['delta_s'] if regressions else None,
                regression_cases=regressions)


def build():
    catalog = load(ROOT / 'catalog.json')
    assert len(catalog) == 48 and len({i['scene']['seed'] for i in catalog}) == 48
    audit_path = ROOT / 'independent_audit_full01.json'
    audit = load(audit_path)
    used = {str(ROOT.joinpath('catalog.json').relative_to(PROJECT)): sha(ROOT / 'catalog.json')}
    if audit is not None:
        used[str(audit_path.relative_to(PROJECT))] = sha(audit_path)
    policies = {}
    for policy in ('A', 'B'):
        rows = []
        for item in catalog:
            scene = item['scene']
            reference_folder = (PROJECT / item['reference'] if item['reference'] else
                                ROOT / 'selected/cases' / scene['name'])
            reference_path = reference_folder / 'result.json'
            candidate_path = ROOT / policy / 'cases' / scene['name'] / 'result.json'
            reference, candidate = load(reference_path), load(candidate_path)
            for path in (reference_path, candidate_path):
                if path.exists():
                    used[str(path.relative_to(PROJECT))] = sha(path)
            rs, cs = status(reference, scene), status(candidate, scene)
            paired = rs == cs == 'all_clear'
            delta = candidate['virtual_time_s'] - reference['virtual_time_s'] if paired else None
            outcome = ('tie' if abs(delta) <= TOLERANCE_S else 'win' if delta < 0 else 'regression') if paired else 'unpaired'
            rows.append(dict(case=scene['name'], seed=scene['seed'], group=item['group'],
                             source_count=len(scene['sources']), reference_status=rs,
                             candidate_status=cs,
                             reference_time_s=reference.get('virtual_time_s') if reference else None,
                             candidate_time_s=candidate.get('virtual_time_s') if candidate else None,
                             delta_s=delta, delta_per_source_s=delta / len(scene['sources']) if paired else None,
                             outcome=outcome, candidate_error=candidate.get('error') if candidate else None,
                             reference_path=str(reference_path.relative_to(PROJECT)),
                             candidate_path=str(candidate_path.relative_to(PROJECT))))
        groups = {'all': rows, 'regression': [r for r in rows if r['group'].startswith('regression')],
                  'new': [r for r in rows if r['group'].startswith('new')]}
        groups.update({g: [r for r in rows if r['group'] == g] for g in sorted({r['group'] for r in rows})})
        policies[policy] = dict(groups={g: statistics(rr) for g, rr in groups.items()},
                                target_cases=[r for r in rows if r['seed'] in TARGETS], cases=rows)
    return dict(created_utc=datetime.now(timezone.utc).isoformat(),
                scope='仅汇总已有结果与已有审计报告；用户终止后未追加试验或审计。',
                decision='A、B均未采纳；当前正式策略保持shared25（selected）。',
                comparison='A/B减当前selected；不使用较旧joint25作比较基准。',
                tolerance_s=TOLERANCE_S, policies=policies, input_sha256=used,
                existing_audit={k: audit.get(k) for k in ('passed', 'partial', 'created_utc', 'checked_runs',
                                  'checked_actions', 'missing_runs', 'failures', 'scope')} if audit else None)


def number(value):
    return '无' if value is None else f'{value:.6f}'


def markdown(data):
    lines = ['# Q4 小改试验归档汇总', '', data['scope'], '', data['decision'], '', data['comparison'], '',
             'ΔT = 候选整局虚拟时间 − selected；负数为节省，正数为退步。绝对差不超过 0.0001 秒记为相等。', '',
             '均值仅使用两侧均全清且原运行独立审计通过的配对，并明确分母；失败和缺失单独列出，不视作零用时或成功。若有失败/缺失，条件均值不能充当完整集合成绩。', '',
             '原32例为已用于诊断的回归集，新16例为预先冻结的分层自建场景；均不代表官方隐藏测试分布。', '']
    audit = data['existing_audit']
    if audit:
        lines += [f"既有审计报告：通过={audit['passed']}；检查 {audit['checked_runs']} 条运行、{audit['checked_actions']} 个动作；失败 {audit['failures']}，缺失 {len(audit['missing_runs'] or [])}。这是已存在报告的归档引用，本次未重跑审计。", '']
    else:
        lines += ['未找到既有完整审计报告，不声称完成独立审计。', '']
    lines += ['## 完整性与分组结果', '', '|候选|集合|全清配对/应有|候选全清/失败/缺失|基准全清/失败/缺失|胜/平/退步|平均ΔT（秒）|平均Δ(T/N)（秒/源）|最大退步（秒）|',
              '|---|---|---:|---|---|---|---:|---:|---:|']
    labels = {'all':'整体48', 'regression':'回归32', 'new':'新16', 'regression_regular':'回归常规24',
              'regression_pressure':'回归压力8', 'new_regular':'新常规8', 'new_pressure':'新压力8'}
    for policy, result in data['policies'].items():
        for group, s in result['groups'].items():
            counts = lambda field: '/'.join(str(s[field].get(k, 0)) for k in ('all_clear', 'failed', 'missing'))
            lines.append(f"|{policy}|{labels[group]}|{s['all_clear_pairs']}/{s['expected']}|{counts('candidate_status')}|{counts('reference_status')}|{s['wins']}/{s['ties']}/{s['regressions']}|{number(s['mean_delta_s'])}|{number(s['mean_delta_per_source_s'])}|{number(s['maximum_regression_s'])}|")
    lines += ['', '胜平退步仅是本集合频数。出现任何退步即不能宣称满足“其它情况不恶化”；即使零退步也不等于未知情况下的保证。', '',
              '现实耗时和规划耗时处在并行运行环境，只保留在原始结果中；不据跨批 wall/planning 数据声称精确加速比。', '',
              '## 两个目标案例', '', '|候选|案例|selected（分）|候选（分）|ΔT（秒）|ΔT（分）|状态|', '|---|---|---:|---:|---:|---:|---|']
    for policy, result in data['policies'].items():
        for r in result['target_cases']:
            minute = lambda k: number(r[k] / 60) if r[k] is not None else '无'
            lines.append(f"|{policy}|{r['case']}|{minute('reference_time_s')}|{minute('candidate_time_s')}|{number(r['delta_s'])}|{minute('delta_s')}|{r['candidate_status']}|")
    lines += ['', '## 全部退步清单', '', '|候选|分组|案例|源数|selected（秒）|候选（秒）|ΔT（秒）|ΔT（分）|', '|---|---|---|---:|---:|---:|---:|---:|']
    for policy, result in data['policies'].items():
        for r in result['groups']['all']['regression_cases']:
            lines.append(f"|{policy}|{r['group']}|{r['case']}|{r['source_count']}|{number(r['reference_time_s'])}|{number(r['candidate_time_s'])}|{number(r['delta_s'])}|{number(r['delta_s']/60)}|")
    lines += ['', '## 失败与缺失', '']
    bad = [(p, r) for p, result in data['policies'].items() for r in result['cases'] if r['outcome'] == 'unpaired']
    lines += [f"- {p} / {r['case']}：基准 {r['reference_status']}；候选 {r['candidate_status']}；错误 {r['candidate_error']}" for p, r in bad] or ['无：A、B分别48例配对均全清。']
    lines += ['', '## 数据与复现', '', '`summary.json`保存96行逐例对照、分组统计与已读输入的SHA-256。基准32条复用原selected结果，新16条读取本批selected结果，共144条已有运行。', '',
              '复现归档汇总：`py -3.13 -X utf8 experiments/q4/micro_changes/summarize.py --output outputs/experiments/q4/micro_changes/archive_summary`。输出目录必须尚不存在；重现时另选新目录，避免覆盖。', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, help='必须不存在的新归档输出目录（项目相对路径）')
    args = parser.parse_args()
    output = PROJECT / args.output
    if output.exists():
        parser.error('输出目录已存在，拒绝覆盖')
    data = build()
    output.mkdir(parents=True, exist_ok=False)
    (output / 'summary.json').write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (output / 'REPORT.md').write_text(markdown(data), encoding='utf-8')
    print(json.dumps({p: {k: v for k, v in d['groups']['all'].items() if k != 'regression_cases'}
                      for p, d in data['policies'].items()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
