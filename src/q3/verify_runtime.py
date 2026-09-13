"""整理后重用原测试，不重跑整局实验。"""
import json
import subprocess
import sys
from pathlib import Path
from runtime import runtime, source_file, project_root, check


def main():
    root = project_root(); output = root/'outputs/source_migration/q3'
    output.mkdir(parents=True, exist_ok=True)
    base = 'experiments/b_q3/'
    manifest_old = base+'cross_method/team_screening_manifest.json'
    manifest = json.loads(source_file(manifest_old)[0].read_text(encoding='utf-8'))
    extra = list(manifest['files_sha256_lf']) + [manifest_old,
        base+'cross_method/prepare_team.py',
        base+'cross_method/p1/light_route.py', base+'cross_method/p1/relocate.py',
        base+'cross_method/p1/light_run.py', base+'cross_method/p1/relocation_probe.py',
        base+'cross_method/p1/test_light.py', base+'cross_method/p1/test_relocation.py',
        base+'refinement/test_refined.py', base+'refinement/verified.py',
        base+'adaptive_second/demonstration/replay.json',
        'outputs/experiments/b_q3_p1/relocation_probe_20260913/probe.json',
        'outputs/experiments/b_q3_p1/light_screening_20260913/A/line_smooth_320118/actions.jsonl',
        'outputs/experiments/b_q3_p1/light_screening_20260913/A/'+manifest['cases'][0]['name']+'/actions.jsonl']
    results = []
    with runtime('F3', extra_files=extra) as session:
        for relative in (base+'refinement/test_refined.py', base+'cross_method/p1/test_light.py',
                         base+'cross_method/p1/test_relocation.py'):
            completed = subprocess.run([sys.executable, '-X', 'utf8', str(session.workspace/relative)],
                cwd=session.workspace, capture_output=True, text=True, encoding='utf-8', timeout=180)
            text = completed.stdout+completed.stderr
            (output/(Path(relative).stem+'.txt')).write_text(text, encoding='utf-8')
            row = dict(test=relative, returncode=completed.returncode, output=text)
            results.append(row)
            print(Path(relative).name, completed.returncode, text[-250:], flush=True)
            if completed.returncode:
                break
    receipt = dict(passed=all(r['returncode'] == 0 for r in results) and len(results) == 3,
        tests=results, construction=check(), scope='original existing unit checks; no full-case rerun')
    (output/'runtime_validation.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    if not receipt['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
