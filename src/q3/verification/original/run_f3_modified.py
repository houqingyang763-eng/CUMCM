"""冻结F3改并补齐原micro_confirm 24例；复用已校验的8例。"""
import argparse
import concurrent.futures
import json
import platform
import time
from pathlib import Path

from run_relocation import execute
from analyze_relocation import validate as validate_reused, sha
from light_run import ROOT, a, read
from prepare_team import canonical

HERE = Path(__file__).resolve().parent
SOURCE = ROOT/'experiments/b_q3/refinement/runs/micro_confirm'
REUSED = ROOT/'outputs/experiments/b_q3_p1/relocation_screening_20260913'


def prepare(out):
    frozen, old_cases, prior, receipt = validate_reused(REUSED)
    old_analysis = read(REUSED/'analysis.json')
    cases = read(SOURCE/'cases.json')
    assert len(cases) == 24 and [c['seed'] for c in cases] == list(range(320100, 320124))
    old_by_name = {c['name']: c for c in old_cases}
    assert set(old_by_name) == {cases[i]['name'] for i in range(0, 24, 3)}
    inputs = [SOURCE/'cases.json', SOURCE/'manifest_current_f1_f2_f3_f4_baseline.json',
              REUSED/'manifest.json', REUSED/'analysis.json', REUSED/'completion.json']
    entries = []
    # Original execution dependencies retain byte-exact historical hashes.
    historical = read(SOURCE/'manifest_current_f1_f2_f3_f4_baseline.json')['hashes']
    changed = [rel for rel, h in historical.items() if sha(ROOT/rel) != h]
    allowed = {'experiments/b_q3/refinement/report_results.py',
               'experiments/b_q3/adaptive_second/build_demo.py'}
    assert {p.replace('\\', '/') for p in changed}.issubset(allowed), changed
    for case in cases:
        name = case['name']; base = SOURCE/name/'f3'; selection_path = SOURCE/name/'selection.json'
        selection = read(selection_path); result = read(base/'result.json')
        assert result['success'] and result['cleared'] == len(case['sources'])
        assert abs(result['per_source_s']-result['total_s']/result['cleared']) < 1e-6
        state = a.CoverageInformationState()
        for line in (base/'actions.jsonl').read_text(encoding='utf-8').splitlines():
            row = json.loads(line)
            if row.get('reason') != 'initial_1':
                break
            state.update(row, row['response'])
        assert state.actions and a.history_seed(state) == selection['history_seed'], name
        reused = name in old_by_name
        candidate = REUSED/name if reused else out/name
        inputs += [selection_path] + [base/fn for fn in ('result.json', 'actions.jsonl', 'metadata.json')]
        if reused:
            assert case == old_by_name[name]
            for fn in ('result.json', 'actions.jsonl', 'metadata.json'):
                path = candidate/fn
                assert sha(path) == old_analysis['source_hashes'][path.relative_to(ROOT).as_posix()]
                inputs.append(path)
            assert read(candidate/'result.json')['success']
        entries.append(dict(name=name, source_count=len(case['sources']), layout=case['layout'],
            noise=case['noise'], case_sha256=canonical(case), reused=reused,
            baseline_selection=selection_path.relative_to(ROOT).as_posix(),
            baseline_dir=base.relative_to(ROOT).as_posix(),
            candidate_dir=candidate.relative_to(ROOT).as_posix()))
    code = {rel: h for freeze in (frozen, frozen['prior_freeze']) for rel, h in freeze['code_hashes'].items()}
    for fn in ('run_f3_modified.py', 'F3_MODIFIED_DESIGN.md'):
        p = HERE/fn; code[p.relative_to(ROOT).as_posix()] = sha(p)
    return cases, dict(candidate_name='F3改', candidate_id='f3_modified',
        implementation='frozen R = F3 + A + scan station relocation; no B or service side exchange',
        source=SOURCE.relative_to(ROOT).as_posix(), cases=entries,
        code_hashes=code, dependency_hashes_lf=frozen['baseline_manifest']['files_sha256_lf'],
        input_hashes={p.relative_to(ROOT).as_posix(): sha(p) for p in inputs},
        validation=dict(reused_validation=receipt, all_24_opening_history_seeds_verified=True,
            historical_execution_hashes_unchanged=True, historical_nonexecution_differences=changed),
        statistics=dict(seed=20260913, bootstrap=20000, strata='layout', interval='percentile 95%',
            delta='F3 - F3改', groups=['all24', 'new16', 'reused8']),
        limits=dict(actions=3000, virtual_s=10800, accounted_wall_s=1200))


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=2); args = parser.parse_args()
    out = args.out.resolve()
    assert out.is_relative_to(ROOT/'outputs/experiments') and not out.exists()
    cases, manifest = prepare(out)
    manifest.update(started_unix=time.time(), python=platform.python_version(), workers=args.workers)
    out.mkdir(parents=True, exist_ok=False)
    a.base.dump(out/'manifest.json', manifest); a.base.dump(out/'cases.json', cases)
    entries = {e['name']: e for e in manifest['cases']}
    results = [read(ROOT/e['candidate_dir']/'result.json') for e in entries.values() if e['reused']]
    a.base.dump(out/'progress.json', dict(finished=len(results), planned=24, reused=8, new_finished=0))
    print('Frozen F3 modified: 24 paired cases, 8 verified reused, 16 new.', flush=True)
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(execute, (case, entries[case['name']], str(out)))
                   for case in cases if not entries[case['name']]['reused']]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
            a.base.dump(out/'progress.json', dict(finished=len(results), planned=24, reused=8,
                new_finished=len(results)-8, results=results))
    a.base.dump(out/'completion.json', dict(finished=len(results), reused=8, new_finished=len(results)-8,
        all_clear=all(r['success'] for r in results), finished_unix=time.time()))


if __name__ == '__main__':
    main()
