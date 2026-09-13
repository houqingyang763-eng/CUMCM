"""核对Q3交接并准备固定输入；不执行策略或访问官方模拟器。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MANIFEST = HERE / 'team_screening_manifest.json'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()


def check():
    manifest = read(MANIFEST)
    for rel, expected in manifest['files_sha256_lf'].items():
        path = ROOT / rel
        if not path.is_file() or digest(path) != expected:
            raise ValueError('missing or changed frozen input: ' + rel)
    all_cases = read(ROOT / manifest['scenario_source'])
    selected = []
    action_count = 0
    sys.path.insert(0, str(HERE.parent / 'refinement'))
    from refined import RefinedPolicy  # 仅导入；不构造/调用策略
    from posterior import a
    for entry in manifest['cases']:
        case = all_cases[entry['source_index_zero_based']]
        if case['name'] != entry['name'] or canonical(case) != entry['case_content_sha256']:
            raise ValueError('case mismatch: ' + entry['name'])
        result = read(ROOT / entry['baseline_result'])
        if not result['success'] or result['cleared'] != len(case['sources']):
            raise ValueError('baseline is not all-clear: ' + entry['name'])
        if abs(result['total_s'] / result['cleared'] - result['per_source_s']) > 1e-6:
            raise ValueError('per-source metric mismatch')
        state = a.CoverageInformationState()
        previous, channel, total = (0., 0.), 1, 0.
        opening = True
        with (ROOT / entry['baseline_actions']).open(encoding='utf-8') as stream:
            for line in stream:
                row = json.loads(line)
                costs, channel = a.base.independent_cost(previous, channel, row, row['response'])
                total += sum(costs.values())
                previous = row['position']
                if abs(total - row['response']['virtual_time_s']) > 1e-5:
                    raise ValueError('action accounting mismatch')
                if opening and row.get('reason') == 'initial_1':
                    state.update(row, row['response'])
                else:
                    opening = False
                action_count += 1
        if abs(total - result['total_s']) > 1e-5:
            raise ValueError('final accounting mismatch')
        selection = read(ROOT / entry['baseline_selection'])
        # 若日志的首站标记不适用，不能默默跳过缓存核验。
        if state.actions == 0 or a.history_seed(state) != selection['history_seed']:
            raise ValueError('baseline first-station history mismatch: ' + entry['name'])
        selected.append(case)
    return manifest, selected, {'ok': True, 'cases': len(selected),
                               'files': len(manifest['files_sha256_lf']),
                               'historical_actions_checked': action_count,
                               'scope': 'imports, frozen inputs and old action accounting only; no strategy run'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    if not args.check and args.out is None:
        parser.error('use --check or --out')
    manifest, cases, receipt = check()
    if args.out is not None:
        out = args.out.resolve()
        output_root = (ROOT / 'outputs/experiments').resolve()
        if not out.is_relative_to(output_root) or out == output_root:
            raise ValueError('--out must be a new run directory under outputs/experiments')
        out.mkdir(parents=True, exist_ok=False)
        def dump(path, value):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        dump(out / 'cases.json', cases)
        dump(out / 'baseline_references.json', {'status': 'inputs_prepared_no_candidate_run',
             'manifest_sha256_lf': digest(MANIFEST), 'cases': manifest['cases'], 'validation': receipt})
        for entry in manifest['cases']:
            dump(out / 'baseline_selection' / entry['name'] / 'selection.json',
                 read(ROOT / entry['baseline_selection']))
        receipt['prepared'] = str(out.relative_to(ROOT))
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
