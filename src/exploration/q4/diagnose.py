"""合并不同开发批次的同案例结果，保留来源与失败，不覆盖原始运行。"""
import argparse
import csv
import json
from pathlib import Path
import statistics


def compare(paths, output):
    records = []
    for folder in paths:
        for row in json.loads((folder / 'results.json').read_text(encoding='utf-8')):
            kept = {k: row[k] for k in ('case', 'policy', 'success', 'cleared', 'source_count',
                'virtual_time_s', 'average_localization_clear_s', 'move_s', 'measure_s',
                'switch_s', 'measure_count', 'failed_clears', 'wall_time_s')}
            kept['batch'] = folder.name
            records.append(kept)
    output.mkdir(parents=True, exist_ok=False)
    with (output / 'cases.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    names = sorted(set(r['policy'] for r in records))
    by_policy = {name: {r['case']: r for r in records if r['policy'] == name} for name in names}
    if any(len(by_policy[n]) != sum(r['policy'] == n for r in records) for n in names):
        raise ValueError('同策略同案例存在多条记录；请显式选择一个批次，不得静默覆盖')
    summary = {}
    for name, cases in by_policy.items():
        rows = list(cases.values())
        good = [r for r in rows if r['success']]
        summary[name] = dict(cases=len(rows), all_clear=len(good),
            mean_seconds_per_source=statistics.mean(r['average_localization_clear_s'] for r in good),
            mean_virtual_minutes=statistics.mean(r['virtual_time_s'] for r in good)/60,
            failed_clears=sum(r['failed_clears'] for r in rows),
            max_wall_s=max(r['wall_time_s'] for r in rows))
    paired = []
    for reference in ('baseline', 'joint25', 'shared'):
        if reference not in by_policy:
            continue
        for name in names:
            if name == reference:
                continue
            common = sorted(set(by_policy[reference]) & set(by_policy[name]))
            good = [c for c in common if by_policy[reference][c]['success'] and by_policy[name][c]['success']]
            if not good:
                continue
            differences = [by_policy[reference][c]['virtual_time_s']-by_policy[name][c]['virtual_time_s'] for c in good]
            per_source = [by_policy[reference][c]['average_localization_clear_s']-by_policy[name][c]['average_localization_clear_s'] for c in good]
            paired.append(dict(reference=reference, candidate=name, matched_cases=len(common),
                both_all_clear=len(good), wins=sum(x>1e-6 for x in differences),
                mean_saved_s=statistics.mean(differences), mean_saved_seconds_per_source=statistics.mean(per_source),
                worst_saved_s=min(differences), case_differences_s=dict(zip(good, differences))))
    result = dict(sources=[str(p) for p in paths], policies=summary, comparisons=paired,
        scope='本地自建案例；开发与确认必须分别汇总；所有失败保留')
    (output / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('batches', type=Path, nargs='+')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.batches, args.output)
    print(json.dumps(dict(policies=result['policies'], comparisons=[
        {k:v for k,v in p.items() if k != 'case_differences_s'}
        for p in result['comparisons']]), ensure_ascii=False, indent=2))
