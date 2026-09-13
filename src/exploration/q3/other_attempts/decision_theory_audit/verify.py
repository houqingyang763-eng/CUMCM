"""独立核对诊断产物的完整性、逐世界均值、选择及冻结输入；不新增试算。"""
import argparse
import hashlib
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def close(x, y):
    assert math.isclose(x, y, abs_tol=1e-8, rel_tol=1e-12), (x, y)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--read-only', action='store_true', help='核验而不重写VALIDATION.json')
    args = parser.parse_args()
    plan = read(HERE / 'PLAN.json')
    summary = read(HERE / 'SUMMARY.json')
    assert len(plan['cases']) == 8
    assert summary['cases_processed'] == 8
    unchanged = {}
    for name, expected in plan['frozen_lf_hashes'].items():
        actual = hashlib.sha256((ROOT / name).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
        unchanged[name] = actual == expected
    assert all(unchanged.values())
    assert hashlib.sha256((HERE / 'probe.py').read_bytes()).hexdigest() == plan['script_sha256']
    counts = {'cases': 0, 'prefix_actions': 0, 'old_costs': 0, 'new_costs': 0,
              'actual_costs': 0, 'failures': 0, 'maximum_old_reproduction_abs_error_s': 0.0}
    for target, row in zip(plan['cases'], summary['rows']):
        result = read(HERE / 'cases' / target['case'] / 'result.json')
        assert result['case'] == target['case'] == row['case']
        assert result['at_action'] == target['at_action']
        assert result['status'] == 'complete'
        assert result['old4_reproduction_passed']
        assert result['old4']['chosen'] == result['old4_reproduced']['chosen']
        counts['cases'] += 1
        counts['prefix_actions'] += result['verified_prefix_actions']
        for old, reproduced in zip(result['old4']['options'], result['old4_reproduced']['options']):
            assert old['id'] == reproduced['id']
            assert len(old['costs_s']) == len(reproduced['costs_s']) == 4
            for x, y in zip(old['costs_s'], reproduced['costs_s']):
                close(x, y)
                counts['maximum_old_reproduction_abs_error_s'] = max(
                    counts['maximum_old_reproduction_abs_error_s'], abs(x-y))
                counts['old_costs'] += 1
        for label, salt in plan['salts'].items():
            group = result['groups'][label]
            assert group['salt'] == salt
            assert len(group['worlds']) == 8
            assert group['posterior']['pool_size'] == 256
            records = group['records']
            assert [r['id'] for r in records] == target['option_ids']
            for record in records:
                assert len(record['costs_s']) == len(record['errors']) == 8
                assert all(x is None for x in record['errors'])
                assert all(math.isfinite(x) and 0 <= x <= 10800 for x in record['costs_s'])
                close(record['mean_s'], sum(record['costs_s']) / 8)
                counts['new_costs'] += 8
            assert group['chosen'] == min(records, key=lambda r: sum(r['costs_s']))['id']
            assert group['first4_chosen'] == min(records, key=lambda r: sum(r['costs_s'][:4]))['id']
            assert group['last4_chosen'] == min(records, key=lambda r: sum(r['costs_s'][4:]))['id']
        records = result['hindsight_actual']['records']
        assert [r['id'] for r in records] == target['option_ids']
        for record in records:
            assert len(record['costs_s']) == 1 and record['errors'] == [None]
            close(record['mean_s'], record['costs_s'][0])
            counts['actual_costs'] += 1
        expected = min(records, key=lambda r: r['costs_s'][0])['id']
        assert expected == result['hindsight_actual']['chosen']
        b = {r['id']: sum(r['costs_s'])/8 for r in result['groups']['B8']['records']}
        actual = {r['id']: r['costs_s'][0] for r in records}
        ids = result['choices']
        close(row['B8_old4_minus_A8_s'], b[ids['old4']] - b[ids['A8']])
        close(row['B8_Afirst4_minus_A8_s'], b[ids['A8_first4']] - b[ids['A8']])
        close(row['actual_old4_minus_A8_s'], actual[ids['old4']] - actual[ids['A8']])
        close(row['actual_candidate_range_s'], max(actual.values()) - min(actual.values()))
        close(row['actual_old4_hindsight_gap_s'], actual[ids['old4']] - min(actual.values()))
    report = {'validation': 'passed', 'performed_by': 'AI', 'counts': counts,
              'frozen_input_source_files_unchanged': len(unchanged),
              'limitations': '仅核验复现、算术、选择与证据完整性，不证明工作先验或F1续行代表真实官方分布。'}
    if not args.read_only:
        (HERE / 'VALIDATION.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
