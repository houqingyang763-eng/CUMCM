"""实际成本、决策改变及测站越界面积；不把人工惩罚算进成绩。"""
import json
import math
from pathlib import Path
import statistics
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from boundary_policy import outside_fraction

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def actions(path):
    return [json.loads(x) for x in (path/'actions.jsonl').read_text(encoding='utf-8').splitlines()]


def metrics(path):
    result = read(path/'result.json')
    rows = actions(path)
    metadata = read(path/'metadata.json')
    decisions = metadata['refinement_decisions']
    points = []
    previous = None
    for row in rows:
        q = tuple(row['position'])
        if row['kind'] == 'measure' and q != previous:
            points.append(q)
        previous = q if row['kind'] == 'measure' else None
    fractions = [outside_fraction(q) for q in points]
    last_clear = max((r['response']['virtual_time_s'] for r in rows
                      if r['kind']=='clear' and r['response']['clear_result']=='success'), default=0.)
    return dict({k:result[k] for k in ('success','total_s','move_s','measure_s','switch_s','success_clear_s','fail_clear_s','measure_count','failreason','actions')},
                mean_station_outside_fraction=statistics.mean(fractions) if fractions else None,
                measurement_stations=len(points), outer_measurement_stations=sum(x>0 for x in fractions),
                sum_station_outside_fraction=sum(fractions),
                post_last_clear_s=result['total_s']-last_clear,
                evaluated_decisions=len(decisions),
                changed_ranking_decisions=sum(d.get('boundary_changed_choice',False) for d in decisions),
                fallback_decisions=sum('fallback' in d for d in decisions))


def first_divergence(base, path):
    original, altered = actions(base), actions(path)
    for left, right in zip(original, altered):
        if any(left[k] != right[k] for k in ('kind','channel','position')):
            return {'step':right['step'],
                    'original':{k:left[k] for k in ('kind','channel','position','reason')},
                    'penalized':{k:right[k] for k in ('kind','channel','position','reason')},
                    'original_radius_m':math.hypot(*left['position']),
                    'penalized_radius_m':math.hypot(*right['position']),
                    'original_outside_fraction':outside_fraction(left['position']),
                    'penalized_outside_fraction':outside_fraction(right['position'])}
    return None


def main():
    out = HERE/'runs'/ (sys.argv[1] if len(sys.argv)>1 else 'development')
    manifest = read(out/'manifest.json')
    modes = ['f3'] + [f'penalty{s:g}' for s in manifest['strengths_s']]
    rows = []
    for case in read(out/'cases.json'):
        base = REPO/manifest['baselines_relative_to_repository'][case['name']]
        row = {'case':case['name'], 'sources':len(case['sources']), 'f3':metrics(base)}
        for mode in modes[1:]:
            path = out/case['name']/mode
            row[mode] = metrics(path)
            row[mode]['first_divergence'] = first_divergence(base, path)
        rows.append(row)
    summary = {}
    for mode in modes:
        complete = all(row[mode]['success'] for row in rows)
        summary[mode] = {
            'all_clear':complete,
            'mean_min':statistics.mean(r[mode]['total_s']/60 for r in rows) if complete else None,
            'savings_min':statistics.mean((r['f3']['total_s']-r[mode]['total_s'])/60 for r in rows) if complete else None,
            'wins':sum(r[mode]['success'] and r[mode]['total_s']<r['f3']['total_s']-1e-6 for r in rows),
            'losses':sum(not r[mode]['success'] or r[mode]['total_s']>r['f3']['total_s']+1e-6 for r in rows),
            'changed_ranking_decisions':sum(r[mode]['changed_ranking_decisions'] for r in rows),
            'worst_min':max(r[mode]['total_s']/60 for r in rows),
            'component_increase_s':{k:statistics.mean(r[mode][k]-r['f3'][k] for r in rows)
                                    for k in ('move_s','measure_s','switch_s','success_clear_s','fail_clear_s')},
        }
    new_baselines = all((REPO/p).parent.parent.resolve() == out.resolve()
                        for p in manifest['baselines_relative_to_repository'].values())
    validation = {
        'new_episodes':len(rows)*(len(modes) if new_baselines else len(modes)-1),
        'independent_actions_replayed':sum(read(out/r['case']/m/'audit.json')['replayed']
                                          for r in rows for m in (modes if new_baselines else modes[1:]) if r[m]['success']),
        'all_clear':all(s['all_clear'] for s in summary.values()),
        'zero_equivalence':read(HERE/'runs/zero_equivalence.json'),
    }
    (out/'comparison.json').write_text(json.dumps({'rows':rows,'summary':summary,'validation':validation},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'summary':summary,'validation':validation},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
