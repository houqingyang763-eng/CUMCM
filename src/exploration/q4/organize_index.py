"""只生成Q4目录清单和导航，不导入模型、执行试验或删除文件。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AREAS = ('experiments/q4', 'src/q4', 'outputs/q4', 'outputs/experiments/q4')
STATUS = {
    'outputs/q4': {
        'holdout01':'当前交付依据：24例三策略', 'pressure01':'当前交付依据：8例三策略',
        'delivery01':'当前交付报告与CSV', 'figures01':'当前论文图PNG/PDF',
        'diagnostics01':'当前逐例退步诊断', 'migration_smoke':'迁移等价性证据，不是新泛化样本',
        'replays01':'历史首次回放；同步终点显示已由replays02替代',
        'replays02':'当前两局新旧方案配对回放',
        'organization01':'本次目录清单；只作文件整理',
    },
    'outputs/experiments/q4': {
        'baseline_smoke':'基线小规模检查', 'runner_smoke_20260913_0304':'运行器小规模检查',
        'candidate_smoke01':'初始候选小规模检查',
        'develop01':'基线/旧参照/首版开发比较', 'develop02':'共享方案/几何方案开发比较',
        'develop03':'22点发现候选开发比较，未选', 'develop04':'按已见源数顺扫候选，未选',
        'develop_comparison01':'开发跨批次统计', 'exploration_comparison01':'探索方案汇总',
        'discovery_design':'发现点构造与连续覆盖设计',
        'rollout_pilot01':'完整续行仅4例试验，未选',
        'cap_diagnostic':'概率诊断过程', 'cap_diagnostic_confirm':'概率诊断独立池复核',
        'cap_value_pilot01':'历史含预算扣除缺陷，保留证据，不作当前效果依据',
        'cap_value_pilot02':'修复后的概率顺扫试验，未选',
        'holdout01':'研究24例确认；与正式同名批次是相同案例，不重复计数',
        'practice_shared01':'官方演练原始记录及核验',
        'practice_ui':'实际官方界面证据', 'practice_receipt_uses':'演练收据消费记录',
        'micro_diagnosis01':'两局诊断生成过程历史记录',
        'micro_diagnosis02':'历史诊断文稿，由03替代',
        'micro_diagnosis03':'当前小改法前置诊断，含条件反事实',
        'micro_changes':'A/B各48例已完成但未采纳；用户已停止追加研究',
    },
}


def main():
    output=ROOT/'outputs/q4/organization01'
    if output.exists(): raise ValueError('清单批次已存在，不覆盖原快照')
    output.mkdir(parents=True)
    now=datetime.now(timezone.utc).isoformat()
    entries=[]; groups=[]
    for area in AREAS:
        base=ROOT/area
        for item in sorted(base.iterdir()):
            if item==output or item.name=='__pycache__': continue
            files=[item] if item.is_file() else [p for p in item.rglob('*') if p.is_file()]
            kept=[p for p in files if '__pycache__' not in p.parts and p.suffix!='.pyc']
            for p in kept:
                entries.append(dict(path=p.relative_to(ROOT).as_posix(),bytes=p.stat().st_size))
            groups.append(dict(area=area,name=item.name,files=len(kept),bytes=sum(p.stat().st_size for p in kept),
                               status=STATUS.get(area,{}).get(item.name,'按文件分组清单查看职责')))
    numerical_sources={}
    # 仅检查现存交付依赖指纹，证明整理没有改动模型或配置；不执行模型核验。
    for batch in ('holdout01','pressure01'):
        manifest=ROOT/f'outputs/q4/{batch}/manifest.json'
        d=json.loads(manifest.read_text(encoding='utf-8'))
        for path,expected in d['code_sha256'].items():
            actual=hashlib.sha256((ROOT/path).read_bytes()).hexdigest()
            if actual!=expected: raise ValueError(f'交付源码指纹变化：{path}')
            numerical_sources[path]=actual
    data=dict(created_utc=now,scope=list(AREAS),excluded='__pycache__、pyc及本清单自身；未删除任何文件',
              groups=groups,files=entries,formal_runtime_sha256=numerical_sources)
    (output/'FILES.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['# 第四问目录整理清单','',f'生成时间（UTC）：{now}。由experiments/q4/organize_index.py生成；只盘点现存文件，不运行试验。','',
           '当前选定策略为shared25；A/B均未采纳，用户已停止追加优化。',
           '', '[交接说明](../../../experiments/q4/HANDOFF.md) · [文件分组](../../../experiments/q4/FILES.md) · [完整文件路径与字节数](FILES.json)','',
           f'盘点非缓存文件{len(entries)}项，合计{sum(p["bytes"] for p in entries)/1024**2:.2f} MiB。该数值是生成时快照，不用于模型性能评价。','']
    for area in AREAS:
        lines.extend([f'## {area}','','| 项目 | 文件数 | MiB | 状态/用途 |','|---|---:|---:|---|'])
        for group in groups:
            if group['area']==area:
                lines.append(f'| {group["name"]} | {group["files"]} | {group["bytes"]/1024**2:.2f} | {group["status"]} |')
        lines.append('')
    lines.extend(['正式运行依赖和配置的现存指纹均与原holdout01/pressure01一致。原始日志、代码快照、失败记录及旧批次均保留；缓存与派生预览仅标为可再生成，未删除。',''])
    (output/'INDEX.md').write_text('\n'.join(lines),encoding='utf-8')
    for area in ('outputs/q4','outputs/experiments/q4'):
        formal=area=='outputs/q4'
        handoff='../../experiments/q4/HANDOFF.md' if formal else '../../../experiments/q4/HANDOFF.md'
        index='organization01/INDEX.md' if formal else '../../q4/organization01/INDEX.md'
        text=['# 第四问'+('交付结果' if formal else '研究结果')+'目录','',
              '本导航由experiments/q4/organize_index.py生成。当前正式方案为shared25，后续A/B探索未采纳；已停止追加优化。','',
              f'[整理与交接]({handoff}) · [全部目录清单]({index})','',
              '| 批次目录 | 当前定位 |','|---|---|']
        for name,description in STATUS[area].items():
            if (ROOT/area/name).exists(): text.append(f'| [{name}]({name}/) | {description} |')
        if not formal:
            text.extend(['','最后一轮：[A/B已完成结果归档](micro_changes/archive_summary/REPORT.md)。失败、未采纳及被替代批次保留，不按目录名中的序号推断当前有效性。'])
        (ROOT/area/'README.md').write_text('\n'.join(text)+'\n',encoding='utf-8')
    print(json.dumps(dict(files=len(entries),MiB=sum(p['bytes'] for p in entries)/1024**2,
                          unchanged_runtime_files=len(numerical_sources),output=output.relative_to(ROOT).as_posix())))

if __name__=='__main__': main()
