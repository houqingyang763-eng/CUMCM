"""三类整理的清单和只读核验；目录移动由显式 PowerShell 操作完成。"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'src/migration_manifest.json'
MOVES = [
    ('experiments/b_q3/final_methods', 'src/q3'),
    ('experiments/b_q3', 'src/exploration/q3'),
    ('experiments/初步探索归档', 'src/exploration/early'),
    ('experiments/q4', 'src/exploration/q4'),
    ('experiments/b_benchmark_scale', 'src/exploration/benchmark'),
    ('experiments/b_method_families', 'src/exploration/method_families'),
    ('experiments/research', 'src/exploration/research'),
]

def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def mapped(name):
    name = name.replace('\\', '/')
    for old, new in MOVES:
        if name == old or name.startswith(old + '/'):
            return new + name[len(old):]
    for folder in ('b_adaptive_q3', 'b_env_probe', 'b_oracle_q3', 'b_overnight'):
        old = 'experiments/' + folder
        if name == old or name.startswith(old + '/'):
            return 'src/exploration/early/' + folder + name[len(old):]
    return name

def save(p, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def prepare():
    if MANIFEST.exists():
        raise RuntimeError('清单已存在，不覆盖')
    files = {}
    for old, new in MOVES:
        source, target = ROOT / old, ROOT / new
        assert source.is_dir() and not target.exists(), (old, new)
        for p in source.rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts:
                relative = p.relative_to(ROOT).as_posix()
                files[relative] = dict(old=relative, new=mapped(relative), before=digest(p), bytes=p.stat().st_size)
    # 现有 Q4 正式代码也核对，以证明整理没有改动算法与配置。
    q4 = {p.relative_to(ROOT).as_posix(): digest(p) for p in (ROOT/'src/q4').rglob('*')
          if p.is_file() and p.suffix in ('.py', '.json')}
    save(MANIFEST, dict(moves=MOVES, files=list(files.values()), q4_before=q4, state='prepared'))
    print('prepared', len(files), 'files')

def fix_links(text, old, new):
    def replace(m):
        href = m.group(2)
        if re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', href) or href.startswith('#'):
            return m.group(0)
        path, mark, anchor = href.partition('#')
        if not path or path.startswith('<'):
            return m.group(0)
        absolute = Path(os.path.normpath(str(ROOT / Path(old).parent / path)))
        try:
            relative = absolute.relative_to(ROOT).as_posix()
        except ValueError:
            return m.group(0)
        target = ROOT / mapped(relative)
        revised = os.path.relpath(target, ROOT / Path(new).parent).replace('\\', '/')
        return m.group(1) + revised + (mark + anchor if mark else '') + ')'
    return re.sub(r'(!?\[[^\]]*\]\()([^\n)]+)\)', replace, text)

def finalize():
    data = json.loads(MANIFEST.read_text(encoding='utf-8'))
    assert data['state'] == 'prepared'
    # 原归档清单保持不动，另建指向新物理位置的组合清单。
    old_manifest = json.loads((ROOT/'src/exploration/q3/organization_manifest.json').read_text(encoding='utf-8'))
    current = json.loads(json.dumps(old_manifest))
    for row in current['files']:
        row['new'] = mapped(row['new'])
    for old, sha in current.get('external_dependencies', {}).items():
        current['files'].append(dict(old=old, new=mapped(old), sha256=sha))
    current['external_dependencies'] = {}
    save(ROOT/'src/q3/source_manifest.json', current)
    runtime = ROOT/'src/q3/runtime.py'
    runtime.write_text(runtime.read_text(encoding='utf-8').replace('experiments/b_q3/organization_manifest.json', 'src/q3/source_manifest.json'), encoding='utf-8')
    verifier = ROOT/'src/q3/verify_runtime.py'
    verifier.write_text(verifier.read_text(encoding='utf-8').replace('outputs/experiments/b_q3_organization_20260913', 'outputs/source_migration/q3'), encoding='utf-8')
    # 新核验入口复用原逐动作计费代码，旧核验文件本身不修改。
    original = (ROOT/'src/exploration/q3/verify_organization.py').read_text(encoding='utf-8')
    original = original.replace('MANIFEST = HERE / "organization_manifest.json"', 'MANIFEST = HERE / "source_manifest.json"')
    original = original.replace('destination.resolve().is_relative_to(HERE)', 'destination.resolve().is_relative_to(ROOT / "src")')
    original = original.replace('all_targets_inside_q3=True', 'all_targets_inside_src=True')
    original = original.replace('documents = [HERE / "README.md", HERE / "other_attempts/README.md"]', 'documents = [HERE / "START_HERE.md"]')
    original = original.replace('final = HERE / "final_methods"', 'final = HERE')
    original = original.replace('outputs/experiments/b_q3_organization_20260913/validation.json', 'outputs/source_migration/q3/evidence_validation.json')
    (ROOT/'src/q3/verify_evidence.py').write_text(original, encoding='utf-8')
    # 只修新导航及本轮研究说明。历史快照与原结果字节保留。
    frozen = {row['new'] for row in current['files']}
    for row in data['files']:
        new, old = row['new'], row['old']
        p = ROOT/new
        repair = ((new.startswith('src/q3/') and p.suffix == '.md' and '/evidence/' not in new)
                  or (new.startswith('src/exploration/q4/') and p.suffix == '.md'))
        if repair and new not in frozen:
            text = p.read_text(encoding='utf-8')
            p.write_text(fix_links(text, old, new), encoding='utf-8')
    # 正式 Q4 算法、报告生成器均不动。审计器从新物理目录读取说明。
    auditor = ROOT/'src/q4/audit_delivery.py'
    auditor.write_text(auditor.read_text(encoding='utf-8').replace("ROOT/'experiments/q4'", "ROOT/'src/exploration/q4'"), encoding='utf-8')
    # 运行器不依赖兼容联接；仅为旧阅读链接与外围任务保留兼容入口。
    for row in data['files']:
        p = ROOT/row['new']
        assert p.is_file(), row['new']
        row['after'] = digest(p)
        row['changed'] = row['before'] != row['after']
    data['q4_after'] = {name: digest(ROOT/name) for name in data['q4_before']}
    data['state'] = 'migrated'
    save(MANIFEST, data)
    print('migrated', len(data['files']), 'files; modified navigation/entry files:', sum(r['changed'] for r in data['files']))

def audit():
    data = json.loads(MANIFEST.read_text(encoding='utf-8'))
    assert data['state'] == 'migrated'
    for row in data['files']:
        assert digest(ROOT/row['new']) == row['after'], row['new']
    for name, sha in data['q4_after'].items():
        assert digest(ROOT/name) == sha, name
    result = dict(passed=True, files=len(data['files']), bytes=sum(r['bytes'] for r in data['files']),
                  preserved=sum(not r['changed'] for r in data['files']),
                  adjusted=[r['new'] for r in data['files'] if r['changed']],
                  q4_adjusted=[n for n in data['q4_before'] if data['q4_before'][n] != data['q4_after'][n]])
    save(ROOT/'outputs/source_migration/files_verified.json', result)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'finalize', 'audit'])
    globals()[parser.parse_args().action]()
