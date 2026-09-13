"""仅本地Q3，冻结候选评分后再做真值反事实；批次失败不得删局。"""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import platform
import statistics
import time
import traceback

from model import (ROOT, CenterContinuation, TwoStagePolicy, CONFIGS, g,
                   InformationState, LocalEnvironment, audit_state, candidates,
                   worlds_from_history, evaluate, continue_to_end, sweep_class)
from simulation import generate

HERE = Path(__file__).resolve().parent


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def real_step(state, env, a):
    assert math.hypot(*a['position']) <= 5000+1e-6
    before = state.virtual_time_s
    move = g.distance(state.position, a['position'])/5
    switch = int(a['kind'] == 'measure' and a['channel'] != state.measuring_channel)
    r = env.act(a)
    operation = 5 if a['kind'] == 'measure' or r['clear_result'] == 'success' else 3
    assert abs(env.virtual_time_s-before-move-switch-operation) < 1e-6
    state.update(a, r)
    audit_state(state, env)
    return r


def scan_snapshot(case):
    state, env = InformationState(), LocalEnvironment(case)
    p = TwoStagePolicy(CONFIGS['scan7_r60'])
    rows = []
    while True:
        a = p.choose(state)
        if a['phase'] != 'scan':
            break
        rows.append(dict(step=len(rows)+1, action=a, response=real_step(state, env, a)))
    assert not any(c.status == 'unknown' for c in state.channels.values())
    return state, env, rows


def baseline(case, policy):
    state, env = InformationState(), LocalEnvironment(case)
    rows = []
    start = time.perf_counter()
    while not state.complete:
        if len(rows) >= 3000 or time.perf_counter()-start > 600:
            raise RuntimeError('基线保护上限，不能记成功')
        a = policy.choose(state)
        rows.append(dict(step=len(rows)+1, action=a, response=real_step(state, env, a)))
    return dict(total_s=env.virtual_time_s, actions=rows, wall_s=time.perf_counter()-start)


def brief(case, name, result, scan_s=None):
    rows = result['actions']
    return dict(case=case.name, policy=name, sources=len(case.sources), success=True,
                total_s=result['total_s'], per_source_s=result['total_s']/len(case.sources),
                scan_s=scan_s, service_s=result.get('remaining_s'),
                measures=sum(r['action']['kind']=='measure' for r in rows),
                failed_clears=sum(r['response'].get('clear_result')=='no_target_in_range' for r in rows),
                wall_s=result.get('wall_s'), costs=result.get('costs'))


def run_case(case, out):
    folder = out / case.name
    folder.mkdir()
    state, env, scan = scan_snapshot(case)
    dump(folder/'scan.json', scan)
    dump(folder/'public_state.json', dict(position=state.position, channel=state.measuring_channel,
         time_s=state.virtual_time_s, channels={j:dict(status=c.status, observations=c.observations,
         exclusions=c.exclusions, circle=c.circle() if c.status=='found' else None)
         for j,c in state.channels.items()}))
    start = time.perf_counter()
    options = candidates(state)
    worlds = worlds_from_history(state)
    selected, prediction = evaluate(state, options, worlds)
    planning_s = time.perf_counter()-start
    # 先落盘冻结选择；之后才将候选放到真实自建案例执行。
    frozen = dict(selected_index=selected, selected_name=options[selected]['name'],
                  planning_wall_s=planning_s, candidates=options, prediction=prediction,
                  worlds=[w.to_dict() for w in worlds])
    dump(folder/'selection_before_counterfactual.json', frozen)
    selection_hash = sha(folder/'selection_before_counterfactual.json')
    actual = []
    for item in options:
        began = time.perf_counter()
        result = continue_to_end(state, copy.deepcopy(env), item['actions'])
        result['wall_s'] = time.perf_counter()-began
        dump(folder/(item['name']+'_actual.json'), result)
        actual.append(result)
    assert sha(folder/'selection_before_counterfactual.json') == selection_hash
    rows = []
    for name, policy in [('scan7_r60', TwoStagePolicy(CONFIGS['scan7_r60'])),
                         ('sweep', sweep_class()())]:
        result = baseline(case, policy)
        dump(folder/(name+'_actual.json'), result)
        if name == 'scan7_r60':
            assert result['actions'][:len(scan)] == scan
        rows.append(brief(case, name, result))
    rows.append(brief(case, 'center_default', actual[0], state.virtual_time_s))
    rows.append(brief(case, 'rollout_selected', actual[selected], state.virtual_time_s))
    rows[-1]['wall_s'] += planning_s
    true = [r['remaining_s'] for r in actual]
    best = min(true)
    ranking = [dict(name=o['name'], predicted_s=p['mean_s'], actual_s=t,
                    predicted_gain_s=prediction[0]['mean_s']-p['mean_s']
                    if prediction[0]['mean_s'] is not None and p['mean_s'] is not None else None,
                    actual_gain_s=true[0]-t) for o,p,t in zip(options,prediction,true)]
    diagnosis = dict(case=case.name, candidates=len(options), selected=options[selected]['name'],
        selected_index=selected, selection_sha256=selection_hash, planning_wall_s=planning_s,
        all_imagined_success=all(p['mean_s'] is not None for p in prediction),
        actual_gain_s=true[0]-true[selected], regret_s=true[selected]-best,
        opportunity_s=true[0]-best, actual_best=options[true.index(best)]['name'], ranking=ranking)
    dump(folder/'diagnosis.json', diagnosis)
    return rows, diagnosis


def summarize(rows, diagnostics, failures):
    summary = {}
    for policy in ('scan7_r60', 'sweep', 'center_default', 'rollout_selected'):
        rs = [r for r in rows if r['policy'] == policy]
        if failures:
            summary[policy] = dict(successes=len(rs), batch_failed=True)
            continue
        xs = [r['per_source_s'] for r in rs]
        summary[policy] = dict(successes=len(rs), mean_total_min=statistics.mean(r['total_s'] for r in rs)/60,
            mean_per_source_s=statistics.mean(xs),
            worst_quarter_per_source_s=statistics.mean(sorted(xs, reverse=True)[:math.ceil(len(xs)/4)]),
            max_per_source_s=max(xs), mean_wall_s=statistics.mean(r['wall_s'] for r in rs))
    if diagnostics:
        gains = [d['actual_gain_s'] for d in diagnostics]
        summary['diagnosis'] = dict(cases=len(gains), wins=sum(x>1e-5 for x in gains),
            ties=sum(abs(x)<=1e-5 for x in gains), losses=sum(x<-1e-5 for x in gains),
            mean_gain_s=statistics.mean(gains), worst_change_s=min(gains),
            mean_regret_s=statistics.mean(d['regret_s'] for d in diagnostics),
            mean_opportunity_s=statistics.mean(d['opportunity_s'] for d in diagnostics),
            mean_planning_wall_s=statistics.mean(d['planning_wall_s'] for d in diagnostics),
            imagined_all_success=all(d['all_imagined_success'] for d in diagnostics))
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', choices=['smoke', 'confirm'], required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    out = (HERE/'runs'/args.output).resolve()
    assert (HERE/'runs').resolve() in out.parents
    out.mkdir(parents=True, exist_ok=False)
    cases = [generate(160000, 'uniform', 'hashed')] if args.stage == 'smoke' else [
        generate(161100+3*i+j, layout, noise) for i,layout in enumerate(('uniform','edge','cluster','line'))
        for j,noise in enumerate(('smooth','biased','hashed'))]
    dump(out/'cases.json', [c.to_dict() for c in cases])
    files = list(HERE.glob('*.py'))+[HERE/'DESIGN.md']
    files += [ROOT/'experiments'/p for p in ('b_benchmark_scale/two_stage.py',
        'b_adaptive_q3/state.py','b_adaptive_q3/geometry.py','b_adaptive_q3/simulation.py',
        'b_adaptive_q3/policy.py','b_oracle_q3/oracle.py',
        'b_overnight/task_cost.py','b_overnight/sweep_policy.py')]
    hashes = {str(p.relative_to(ROOT)):sha(p) for p in files}
    for path in files:
        dest = out/'source'/path.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(path.read_bytes())
    dump(out/'manifest.json', dict(stage=args.stage, python=platform.python_version(),
        created=time.strftime('%Y-%m-%d %H:%M:%S %z'), sources_sha256=hashes,
        cases_sha256=sha(out/'cases.json'), mode='local_q3_only',
        decision='一次阶段交界选择；本批结束不调参', expected_cases=len(cases)))
    rows, diagnoses, failures = [], [], []
    for case in cases:
        try:
            r, d = run_case(case, out)
            rows.extend(r)
            diagnoses.append(d)
            print(json.dumps({k:d[k] for k in ('case','selected','actual_gain_s','regret_s','opportunity_s','planning_wall_s')},ensure_ascii=False),flush=True)
        except Exception:
            failure = dict(case=case.name, error=traceback.format_exc())
            failures.append(failure)
            print(json.dumps(failure,ensure_ascii=False),flush=True)
        dump(out/'results.json', rows)
        dump(out/'diagnostics.json', diagnoses)
        dump(out/'failures.json', failures)
    summary = summarize(rows, diagnoses, failures)
    dump(out/'summary.json', summary)
    print(json.dumps(summary,ensure_ascii=False),flush=True)
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
