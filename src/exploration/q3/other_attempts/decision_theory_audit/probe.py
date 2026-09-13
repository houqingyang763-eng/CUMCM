"""冻结八例首个多候选状态的条件估价诊断；不生成或部署新策略。"""
import argparse
import copy
import hashlib
import json
import math
import pickle
import statistics
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / 'refinement'))
from refined import RefinedPolicy
from posterior import a, sample_worlds

MANIFEST = ROOT / 'experiments/b_q3/cross_method/team_screening_manifest.json'
SALTS = {'A8': 2026091301, 'B8': 2026091302}
ORIGINAL_SIMULATE = RefinedPolicy.simulate


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def dump(path, data):
    a.base.dump(path, data)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def sha(path, lf=False):
    data = Path(path).read_bytes()
    return hashlib.sha256(data.replace(b'\r\n', b'\n') if lf else data).hexdigest()


def equal(expected, actual, path='root'):
    """JSON结构严格比较；浮点允许1e-8秒/米的数值误差。"""
    if isinstance(expected, dict):
        assert set(expected) == set(actual), (path, set(expected), set(actual))
        for key in expected:
            equal(expected[key], actual[key], path + '.' + str(key))
    elif isinstance(expected, (list, tuple)):
        assert len(expected) == len(actual), (path, len(expected), len(actual))
        for i, (x, y) in enumerate(zip(expected, actual)):
            equal(x, y, path + '.' + str(i))
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        assert math.isclose(expected, actual, abs_tol=1e-8, rel_tol=1e-12), (path, expected, actual)
    else:
        assert expected == actual, (path, expected, actual)


def prepare():
    manifest = read(MANIFEST)
    inputs = {name: sha(ROOT / name, lf=True) for name in manifest['files_sha256_lf']}
    mismatches = [name for name, value in inputs.items() if value != manifest['files_sha256_lf'][name]]
    assert not mismatches, ('frozen_source_or_input_drift', mismatches)
    cases = read(ROOT / manifest['scenario_source'])
    plan = []
    for item in manifest['cases']:
        case = cases[item['source_index_zero_based']]
        assert case['name'] == item['name']
        assert hashlib.sha256(canonical(case).encode()).hexdigest() == item['case_content_sha256']
        metadata_path = (ROOT / item['baseline_result']).with_name('metadata.json')
        metadata = read(metadata_path)
        chosen = next(d for d in metadata['refinement_decisions']
                      if len(d.get('options', [])) >= 2 and 'fallback' not in d)
        plan.append({'case': item['name'], 'at_action': chosen['at_action'],
                     'option_ids': [x['id'] for x in chosen['options']],
                     'old4_chosen': chosen['chosen'], 'old_wall_s': chosen['wall_s']})
    imported = {}
    for module in list(sys.modules.values()):
        filename = getattr(module, '__file__', None)
        if filename:
            path = Path(filename).resolve()
            if path.is_file() and path.is_relative_to(ROOT):
                imported[str(path.relative_to(ROOT)).replace('\\', '/')] = sha(path)
    dump(HERE / 'PLAN.json', {
        'created_unix_s': time.time(), 'design': 'frozen_first_successful_multicandidate_decision_per_case',
        'cases': plan, 'salts': SALTS, 'old_salt': 310912, 'pool_size': 256,
        'worlds_per_candidate': {'old_reproduction': 4, 'A8': 8, 'B8': 8, 'hindsight_actual': 1},
        'workers': 1, 'limits': {'actions': 3000, 'remaining_virtual_s': 10800},
        'selection': 'same ordered candidates; min sample mean, first in order breaks ties',
        'failure_rule': 'retain every failure; any failed rollout makes that group incomplete; no partial winner',
        'capture': 'normal policy.choose and environment feedback replay; intercept original simulate at target',
        'evaluation': 'unchanged RefinedPolicy.simulate; common F1 for every option and every world',
        'boundaries': [
            'A8 and B8 salts each regenerate the 256 proposal pool, not merely the sampled worlds',
            'A first4 versus all8 is nested within the same A proposal pool',
            'B8 checks the working model, not the actual official distribution',
            'actual is hindsight-only one-step evaluation with common F1; not deployable or additive whole-run savings',
            '8 cases and 8 worlds do not demonstrate convergence or generalization',
            'no new strategy, no parameter search, no official simulator, no P1 access'],
        'frozen_manifest': str(MANIFEST.relative_to(ROOT)).replace('\\', '/'),
        'frozen_manifest_sha256': sha(MANIFEST), 'frozen_lf_hashes': inputs,
        'imported_source_sha256_bytes': imported, 'script_sha256': sha(__file__),
    })
    return manifest, cases, plan


def capture(item, case_data, target):
    directory = (ROOT / item['baseline_result']).parent
    metadata = read(directory / 'metadata.json')
    actions = [json.loads(line) for line in (directory / 'actions.jsonl').read_text(encoding='utf-8').splitlines()]
    old = next(d for d in metadata['refinement_decisions'] if d['at_action'] == target['at_action'])
    p = RefinedPolicy(metadata['selected_second'], level=3, samples=4)
    state = a.CoverageInformationState()
    env = a.LocalEnvironment(a.Scenario.from_dict(case_data))
    saved = {}
    calls = []

    def intercept(self, state, world, option, original):
        if self is p and state.actions == target['at_action']:
            if not saved:
                saved.update(policy=copy.deepcopy(self), state=copy.deepcopy(state), original=copy.deepcopy(original))
            calls.append({'option': copy.deepcopy(option), 'world': world.to_dict()})
        return ORIGINAL_SIMULATE(self, state, world, option, original)

    RefinedPolicy.simulate = intercept
    try:
        for logged in actions:
            assert state.actions + 1 == logged['step']
            action = p.choose(state)
            equal({key: logged[key] for key in action}, action, 'action')
            if state.actions == target['at_action']:
                assert saved, 'target simulate checkpoint was not captured'
                reproduced = p.decisions[-1]
                keys = ['at_action', 'position', 'channel', 'original_reason', 'original_action',
                        'scan_unknown', 'posterior', 'options', 'chosen', 'predicted_saving_s']
                equal({k: old[k] for k in keys}, {k: reproduced[k] for k in keys}, 'old4_decision')
                assert len(calls) == len(old['options']) * 4
                saved.update(old=old, reproduced=reproduced, calls=calls,
                             verified_prefix_actions=state.actions, verified_next_action=action)
                return saved
            reply = env.act(action)
            equal(logged['response'], reply, 'feedback')
            state.update(action, reply)
            a.audit_state(state, env)
    finally:
        RefinedPolicy.simulate = ORIGINAL_SIMULATE
    raise AssertionError('target not reached')


def evaluate(saved, worlds):
    records = []
    for option in saved['old']['options']:
        values, errors, walls = [], [], []
        for world in worlds:
            began = time.perf_counter()
            try:
                value = ORIGINAL_SIMULATE(saved['policy'], saved['state'], world, option, saved['original'])
                error = None
            except Exception as exc:
                value, error = None, f'{type(exc).__name__}: {exc}'
            values.append(value)
            errors.append(error)
            walls.append(time.perf_counter() - began)
        complete = all(value is not None for value in values)
        records.append({'id': option['id'], 'costs_s': values, 'errors': errors, 'wall_s': walls,
                        'mean_s': statistics.mean(values) if complete else None})
    return records


def choice(records, section=None):
    values = []
    for r in records:
        v = r['costs_s'] if section is None else r['costs_s'][section]
        if not v or any(x is None for x in v):
            return None
        values.append((statistics.mean(v), r['id']))
    return min(values, key=lambda pair: pair[0])[1]


def cost(records, option_id):
    return next(r['mean_s'] for r in records if r['id'] == option_id) if option_id else None


def process(item, case_data, target):
    began = time.perf_counter()
    out = HERE / 'cases' / item['name']
    out.mkdir(parents=True, exist_ok=True)
    saved = capture(item, case_data, target)
    print(json.dumps({'case': item['name'], 'stage': 'old4_exact_reproduction_passed',
                      'at_action': target['at_action'], 'options': target['option_ids']}, ensure_ascii=False), flush=True)
    checkpoint = out / 'checkpoint.pkl'
    checkpoint.write_bytes(pickle.dumps({k: saved[k] for k in ('policy', 'state', 'original')}, protocol=5))
    result = {'case': item['name'], 'at_action': target['at_action'], 'status': 'running',
              'verified_prefix_actions': saved['verified_prefix_actions'],
              'verified_next_action': saved['verified_next_action'], 'old4_reproduction_passed': True,
              'checkpoint_sha256': sha(checkpoint), 'old4': saved['old'],
              'old4_reproduced': saved['reproduced'], 'old4_worlds_and_options': saved['calls'],
              'state_public_summary': a.base.visible_snapshot(saved['state']),
              'groups': {}, 'errors': []}
    dump(out / 'result.json', result)
    for label, salt in SALTS.items():
        try:
            worlds, info = sample_worlds(saved['state'], count=8, pool_size=256, salt=salt)
            records = evaluate(saved, worlds)
            result['groups'][label] = {'salt': salt, 'posterior': info,
                'worlds': [w.to_dict() for w in worlds], 'records': records,
                'chosen': choice(records), 'first4_chosen': choice(records, slice(0, 4)),
                'last4_chosen': choice(records, slice(4, 8))}
        except Exception as exc:
            result['groups'][label] = {'salt': salt, 'error': f'{type(exc).__name__}: {exc}'}
            result['errors'].append(f'{label}: {type(exc).__name__}: {exc}')
        dump(out / 'result.json', result)
    case = a.Scenario.from_dict(case_data)
    remaining = tuple(src for src in case.sources if saved['state'].channels[src.channel].status != 'cleared')
    actual = a.Scenario(case.name, case.seed, case.layout, case.noise, remaining)
    true_records = evaluate(saved, [actual])
    result['hindsight_actual'] = {'world': actual.to_dict(), 'records': true_records,
                                  'chosen': choice(true_records), 'deployable': False}
    old_id = saved['old']['chosen']
    choices = {'old4': old_id}
    for label in SALTS:
        group = result['groups'][label]
        choices.update({label: group.get('chosen'), label + '_first4': group.get('first4_chosen'),
                        label + '_last4': group.get('last4_chosen')})
    result['choices'] = choices
    b_records = result['groups']['B8'].get('records', [])
    result['B8_evaluation'] = {label: cost(b_records, option_id) for label, option_id in choices.items()} if b_records else {}
    result['actual_evaluation'] = {label: cost(true_records, option_id) for label, option_id in choices.items()}
    if choice(true_records):
        low = min(r['mean_s'] for r in true_records)
        high = max(r['mean_s'] for r in true_records)
        result['actual_candidate_range_s'] = high - low
        result['actual_old4_hindsight_gap_s'] = cost(true_records, old_id) - low
    result['status'] = 'complete' if not result['errors'] and all(
        group.get('chosen') is not None for group in result['groups'].values()) and choice(true_records) else 'incomplete'
    result['wall_s'] = time.perf_counter() - began
    dump(out / 'result.json', result)
    return result


def summarize(results):
    rows = []
    for result in results:
        if result['status'] in ('capture_failed', 'failed'):
            rows.append({'case': result['case'], 'status': result['status'], 'error': result['error']})
            continue
        choices = result['choices']
        b = result['B8_evaluation']
        actual = result['actual_evaluation']
        def delta(data, old, new):
            return data[old] - data[new] if data.get(old) is not None and data.get(new) is not None else None
        rows.append({'case': result['case'], 'status': result['status'], 'at_action': result['at_action'],
                     'choices': choices, 'B8_old4_minus_A8_s': delta(b, 'old4', 'A8'),
                     'B8_Afirst4_minus_A8_s': delta(b, 'A8_first4', 'A8'),
                     'actual_old4_minus_A8_s': delta(actual, 'old4', 'A8'),
                     'actual_candidate_range_s': result.get('actual_candidate_range_s'),
                     'actual_old4_hindsight_gap_s': result.get('actual_old4_hindsight_gap_s'),
                     'A_halves_agree': choices['A8_first4'] == choices['A8_last4'],
                     'B_halves_agree': choices['B8_first4'] == choices['B8_last4'],
                     'A8_B8_agree': choices['A8'] == choices['B8'],
                     'old4_A8_agree': choices['old4'] == choices['A8'],
                     'wall_s': result['wall_s']})
    output = {'scope': 'descriptive_fixed8_first_decision_common_F1_no_whole_run_claim',
              'cases_requested': 8, 'cases_processed': len(rows), 'rows': rows}
    for key in ('B8_old4_minus_A8_s', 'B8_Afirst4_minus_A8_s', 'actual_old4_minus_A8_s',
                'actual_candidate_range_s', 'actual_old4_hindsight_gap_s'):
        values = [r[key] for r in rows if r.get(key) is not None]
        output[key] = {'count': len(values), 'mean': statistics.mean(values) if values else None,
                       'median': statistics.median(values) if values else None,
                       'positive_count': sum(v > 1e-8 for v in values),
                       'negative_count': sum(v < -1e-8 for v in values)}
    for key in ('A_halves_agree', 'B_halves_agree', 'A8_B8_agree', 'old4_A8_agree'):
        output[key] = {'count': sum(key in r for r in rows), 'agree': sum(r.get(key, False) for r in rows)}
    dump(HERE / 'SUMMARY.json', output)
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    manifest, cases, plan = prepare()
    if args.prepare_only:
        print(json.dumps(plan, ensure_ascii=False))
        return
    results = []
    for item, target in zip(manifest['cases'], plan):
        try:
            result = process(item, cases[item['source_index_zero_based']], target)
        except Exception as exc:
            result = {'case': item['name'], 'status': 'failed',
                      'error': f'{type(exc).__name__}: {exc}', 'traceback': traceback.format_exc()}
            dump(HERE / 'cases' / item['name'] / 'failure.json', result)
        results.append(result)
        summarize(results)
        print(json.dumps({'case': item['name'], 'status': result['status'],
                          'wall_s': result.get('wall_s'), 'error': result.get('error'),
                          'choices': result.get('choices')}, ensure_ascii=False), flush=True)
        if result['status'] == 'failed':
            raise RuntimeError('diagnosis stopped on capture/reproduction failure; see failure.json')


if __name__ == '__main__':
    main()
