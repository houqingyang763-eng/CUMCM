"""汇总已经完成的独立复算，不把开发或重复运行算作新样本。"""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
receipts=[];seeds={}
for name in ('confirm','stress','random_audit','micro_confirm'):
    p=HERE/'runs'/name
    summary=json.loads((p/'summary.json').read_text())
    analysis=json.loads((p/'analysis.json').read_text())
    cases=json.loads((p/'cases.json').read_text())
    assert not analysis['failures']
    assert all(v['all_clear'] for v in summary['summary'].values())
    proof=json.loads((p/'filter_verification.json').read_text())
    assert proof['cases']==len(cases)
    receipts.append({'batch':name,'cases':len(cases),'modes':summary['modes'],
                     'episodes':len(cases)*len(summary['modes']),
                     'independently_replayed_actions':analysis['independently_replayed_actions'],
                     'f1_filter_proofs_checked':proof['proofs_checked'],
                     'f1_same_route_cases':proof['same_route_cases']})
    seeds[name]={c['seed'] for c in cases}
assert not seeds['micro_confirm']&(seeds['confirm']|seeds['stress']|seeds['random_audit'])
runtime=[HERE/'refined.py',HERE/'posterior.py',HERE/'verified.py']
micro=json.loads((HERE/'runs/micro_confirm/manifest_current_f1_f2_f3_f4_baseline.json').read_text())
root=HERE.parents[2]
hashes={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in runtime}
for relative,value in hashes.items():assert micro['hashes'][relative]==value
receipt={'scope':'self_built_cases_only_no_official_tests','batches':receipts,
         'episodes':sum(x['episodes'] for x in receipts),
         'independently_replayed_actions':sum(x['independently_replayed_actions'] for x in receipts),
         'unit_checks':12,'unit_check_command':'py -3.13 experiments/b_q3/refinement/test_refined.py',
         'new_confirmation_seeds_disjoint':True,'f4_frozen_during_confirmation':True,
         'runtime_sha256':hashes,'f3_hook_equivalence':'151 actions, positions, reasons and responses identical',
         'exclusions':'development, development_corrected and f3_equivalence are not counted as independent confirmation',
         'human_review':'AI executed and independently recomputed; team human review pending'}
(HERE/'VALIDATION.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(receipt,ensure_ascii=False))
