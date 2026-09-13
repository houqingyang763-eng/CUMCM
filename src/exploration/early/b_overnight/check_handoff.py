"""只核对已完成成果的源码版本和入口链接，不连接官方程序。"""
import hashlib
import json
from pathlib import Path
import re
from datetime import datetime, timezone
from astra_guard import check_cached

ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == '__main__':
    quota = check_cached()
    evidence = ROOT / 'practice/local_runs/q3_sweep_20260911/manifest.json'
    recorded = json.loads(evidence.read_text(encoding='utf-8'))['source_sha256']
    checked = {}
    for relative, expected in recorded.items():
        path = ROOT.parent / relative
        actual = sha(path)
        assert actual == expected, relative
        checked[relative] = actual
    docs = ['README.md', 'RESULTS.md', 'HANDOFF.md', 'MODEL_Q1_Q2.md',
            'MODEL_Q3.md', 'MODEL_Q4.md', 'SCORECARD.md', 'practice/README.md']
    missing, pending = [], []
    for relative in docs:
        path = ROOT / relative
        body = re.sub(r'```.*?```', '', path.read_text(encoding='utf-8'), flags=re.S)
        for href in re.findall(r'\]\(([^)]+)\)', body):
            if '://' in href or href.startswith('#'):
                continue
            target = (path.parent / href.split('#')[0]).resolve()
            if not target.exists():
                item = {'document': relative, 'target': href}
                if target in (ROOT / 'ARCHIVE.md', ROOT / 'HANDOFF_MANIFEST.json'):
                    pending.append(item)
                else:
                    missing.append(item)
    assert not missing, missing
    data = dict(created_at_utc=datetime.now(timezone.utc).isoformat(), quota_remaining=quota['remaining_percent'],
                interpretation='当前源码与第三次官方演练冻结快照完全一致；不重跑实验。文档之后仅作归档更新，文档散列不冻结。',
                source_evidence=evidence.relative_to(ROOT).as_posix(), source_sha256=checked,
                checked_documents=docs, missing_links=missing, archive_links_pending_at_check=pending)
    (ROOT / 'HANDOFF_MANIFEST.json').write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(source_files=len(checked), missing_links=len(missing), pending_archive_links=len(pending))))
