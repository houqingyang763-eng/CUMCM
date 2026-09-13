"""只读核对交付数据、运行源码快照、固定配置和文档链接，不执行策略。"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import statistics

ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit():
    selected = read(ROOT/'src/q4/selected_config.json')['parameters']
    batches, all_rows, cases_seen = [], [], set()
    for name, count in (('holdout01', 24), ('pressure01', 8)):
        folder = ROOT/'outputs/q4'/name
        manifest, rows = read(folder/'manifest.json'), read(folder/'results.json')
        assert len(rows) == 3*count
        assert len({(r['case'], r['policy']) for r in rows}) == len(rows)
        cases = {r['case'] for r in rows}
        assert len(cases) == count and not cases_seen.intersection(cases)
        cases_seen.update(cases)
        assert {r['policy'] for r in rows} == {'baseline', 'joint25', 'selected'}
        for policy in ('baseline', 'joint25', 'selected'):
            assert {r['case'] for r in rows if r['policy'] == policy} == cases
        for r in rows:
            assert r['success'] and r['independent_audit_passed'] and r['error'] is None
            assert r['cleared'] == r['source_count']
            assert math.isclose(r['average_localization_clear_s'], r['virtual_time_s']/r['cleared'], abs_tol=1e-9)
            assert math.isclose(sum(r['ledger'].values()), r['virtual_time_s'], rel_tol=0, abs_tol=1e-6)
            if r['policy'] == 'selected':
                assert r['policy_metadata']['config'] == selected
                assert r['policy_metadata']['rollout_attempts'] == 0
        hashes = manifest['code_sha256']
        for path, digest in hashes.items():
            assert sha(ROOT/path) == digest, f'当前运行依赖改变: {path}'
            assert sha(folder/'source'/path) == digest, f'批次快照改变: {path}'
        all_rows.extend(rows)
        picked = [r for r in rows if r['policy'] == 'selected']
        batches.append(dict(batch=name, cases=count, rows=len(rows), sources=sum(r['source_count'] for r in picked),
            selected_actions=sum(r['actions'] for r in picked), dependency_count=len(hashes),
            results_sha256=sha(folder/'results.json'), manifest_sha256=sha(folder/'manifest.json'),
            mean_seconds_per_source=statistics.mean(r['average_localization_clear_s'] for r in picked)))
    chosen = [r for r in all_rows if r['policy'] == 'selected']
    delivery = read(ROOT/'outputs/q4/delivery01/summary.json')
    assert delivery['fully_clear']
    assert delivery['selected_total']['cases'] == len(chosen)
    assert delivery['selected_total']['sources'] == sum(r['source_count'] for r in chosen)
    assert math.isclose(delivery['selected_total']['mean_per_source_s'], statistics.mean(r['average_localization_clear_s'] for r in chosen), abs_tol=1e-9)
    for path, digest in delivery['source_sha256'].items():
        assert sha(ROOT/path) == digest, f'报告输入或生成器改变: {path}'
    figures = ROOT/'outputs/q4/figures01'
    figure_data = read(figures/'figure_data.json')
    assert figure_data['generator_sha256'] == sha(ROOT/'src/q4/figures.py')
    for group in figure_data['groups'].values():
        assert sha(ROOT/group['batch']/'results.json') == group['results_sha256']
    for stem in ('efficiency', 'cost_breakdown', 'paired_cases', 'example_routes'):
        for extension in ('png', 'pdf'):
            assert (figures/f'{stem}.{extension}').stat().st_size > 1000
    practice = read(ROOT/'outputs/experiments/q4/practice_shared01/verified_summary.json')
    assert practice['official_all_cleared'] and practice['exited'] and practice['automatic_retries'] == 0
    assert practice['cleared_count'] == practice['official_true_count'] == len(practice['unique_successful_channels'])
    assert math.isclose(practice['virtual_time_s'], sum(practice['ledger'].values()), rel_tol=0, abs_tol=1e-4)
    documents = [ROOT/'src/exploration/q4'/n for n in ('README.md', 'MODEL.md', 'PLAN.md', 'CAP_DIAGNOSTIC.md')]
    documents += [ROOT/'src/q4'/n for n in ('README.md', 'MIGRATION.md')]
    documents += [ROOT/'outputs/q4/delivery01/REPORT.md']
    for file in documents:
        for target in re.findall(r'(?<!!)\[[^\]]+\]\(([^)]+)\)', file.read_text(encoding='utf-8')):
            if '://' in target or target.startswith('#'):
                continue
            assert (file.parent/target.split('#')[0].strip('<>')).exists(), (file, target)
    return dict(passed=True, audited_at_utc=datetime.now(timezone.utc).isoformat(), batches=batches,
        different_cases=len(cases_seen), policy_runs=len(all_rows), selected_sources=sum(r['source_count'] for r in chosen),
        checked_documents=len(documents), official_practice_verified=True,
        scope='数据、源码指纹、参数、生成物与导航一致性；不替代逐动作审计、几何测试和人工审阅',
        document_sha256={str(p.relative_to(ROOT)):sha(p) for p in documents},
        auditor_sha256=sha(Path(__file__)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('核验记录已存在，请使用新路径')
    result = audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('batches','document_sha256')},ensure_ascii=False))
