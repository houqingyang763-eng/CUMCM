"""固定八例本地筛选；使用唯一模块名隔离历史运行器导入。"""
import argparse
import concurrent.futures
import hashlib
import json
import platform
import time
from pathlib import Path

from p1_policy import P1Policy
from p1_tasks import a, Q3

HERE = Path(__file__).resolve().parent
ROOT = Q3.parents[1]
DESIGN = HERE.parent/'p1_screening_manifest.json'


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_inputs():
    manifest = load(DESIGN)
    artifacts = [manifest['scenario_source'], manifest['baseline']['config_artifact'],
                 *manifest['baseline']['runtime_dependencies']]
    for case in manifest['screening_cases']:
        artifacts.extend(case['artifacts'].values())
    for item in artifacts:
        if sha(ROOT/item['path']) != item['sha256']:
            raise ValueError('Frozen input changed: '+item['path'])
    cases = load(ROOT/manifest['scenario_source']['path'])
    selected = []
    for item in manifest['screening_cases']:
        case = cases[item['source_index_zero_based']]
        digest = hashlib.sha256(json.dumps(case, sort_keys=True, ensure_ascii=False,
                                           separators=(',', ':')).encode()).hexdigest()
        assert digest == item['case_content_sha256']
        selected.append((case, item))
    return manifest, selected


def execute(payload):
    case, item, output = payload
    path = Path(output)/case['name']
    selection = load(ROOT/item['artifacts']['selection.json']['path'])
    selection_s = selection['wall_s']
    deadline = time.perf_counter()+1200-selection_s
    original_factory = a.base.create_policy
    try:
        a.base.create_policy = lambda name, config: (P1Policy(selection['selected'], deadline=deadline),
                                                    a.CoverageInformationState())
        a.base.execute_case(case, 'P1_joint_tasks', a.CONFIG, path,
                            dict(action_limit=3000, virtual_limit_s=10800, wall_limit_s=1200-selection_s))
    finally:
        a.base.create_policy = original_factory
    result = load(path/'result.json')
    result.update(cached_opening_selection_wall_s=selection_s,
                  accounted_wall_s=result['wall_s']+selection_s,
                  opening_selection='reused identical public-history selection; historical compute charged separately')
    a.base.dump(path/'result.json', result)
    print(json.dumps(dict(case=case['name'], success=result['success'],
                          virtual_min=result['total_s']/60, wall_s=result['accounted_wall_s'],
                          failreason=result['failreason']), ensure_ascii=False), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=2)
    args = parser.parse_args()
    manifest, items = validate_inputs()
    if args.out.exists():
        raise ValueError('Output exists; preserve prior attempt and choose a new run directory')
    args.out.mkdir(parents=True)
    hashes = {str(p.relative_to(ROOT)).replace('\\', '/'): sha(p) for p in HERE.glob('*.py')}
    a.base.dump(args.out/'manifest.json', dict(code_hashes=hashes, design_manifest_sha256=sha(DESIGN),
        python=platform.python_version(), started_unix=time.time(), workers=args.workers,
        scope='eight fixed local cases; F3 reused; no official simulator',
        baseline_manifest=manifest, runtime_limits=dict(actions=3000, virtual_s=10800, accounted_wall_s=1200)))
    a.base.dump(args.out/'cases.json', [case for case, _ in items])
    results = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(execute, (case, item, str(args.out))) for case, item in items]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
            a.base.dump(args.out/'progress.json', dict(finished=len(results), planned=8, results=results))
    a.base.dump(args.out/'completion.json', dict(finished=len(results),
        all_clear=all(r['success'] for r in results), finished_unix=time.time()))


if __name__ == '__main__':
    main()
