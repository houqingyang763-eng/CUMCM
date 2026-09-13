"""重算已保存的四场景费用，不生成场景、不调用策略。"""
import hashlib
import json
import statistics as st
from pathlib import Path

BASE=Path(__file__).resolve().parent
RUN=BASE/'runs/screening_20260913'


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def load(path): return json.loads(path.read_text(encoding='utf-8'))


def summarize(rows):
    return dict(decisions=len(rows),
        deleted_world_changes=sum(bool(x['deleted_world_changed']) for x in rows),
        deleted_world_changes_over_one_second=sum(any(v['reduced_sample_advantage_s']>1 for v in x['deleted_world_changed']) for x in rows),
        gap_below_one_paired_se=sum(x['runner_up_gap_s']<x['paired_se_s'] for x in rows),
        median_runner_up_gap_s=st.median(x['runner_up_gap_s'] for x in rows),
        median_paired_se_s=st.median(x['paired_se_s'] for x in rows))


def main():
    records=[]; hashes={}
    for case in load(RUN/'cases.json'):
        name=case['name'];path=RUN/name/'metadata.json'; hashes[name]=sha(path)
        for d in load(path)['refinement_decisions']:
            options=d['options']
            if len(options)<2 or 'fallback' in d: continue
            assert all(len(o['costs_s'])==4 for o in options)
            key=lambda o:(st.mean(o['costs_s']),o['id']!='original',o['id'])
            ordered=sorted(options,key=key);best,runner=ordered[:2]
            assert d['chosen']==best['id']
            for o in options: assert abs(st.mean(o['costs_s'])-o['mean_s'])<1e-7
            differences=[b-a for a,b in zip(best['costs_s'],runner['costs_s'])]
            dropped=[]
            for i in range(4):
                selected=min(options,key=lambda o:(st.mean(v for j,v in enumerate(o['costs_s']) if j!=i),o['id']!='original',o['id']))
                if selected['id']!=best['id']:
                    advantage=st.mean(best['costs_s'][j]-selected['costs_s'][j] for j in range(4) if j!=i)
                    dropped.append(dict(index=i,choice=selected['id'],reduced_sample_advantage_s=advantage))
            records.append(dict(case=name,at_action=d['at_action'],chosen=best['id'],runner_up=runner['id'],
                runner_up_gap_s=st.mean(differences),paired_se_s=st.stdev(differences)/2,
                paired_differences_s=differences,deleted_world_changed=dropped,
                originally_predicted_saving_s=d['predicted_saving_s']))
    result=dict(scope='arithmetic on existing four-world costs; no resampling or strategy execution',
        caveat='Deletion sensitivity and paired SE are descriptive only; n=4 and post-selection are not calibrated significance tests.',
        summary=summarize(records),by_case={c['name']:summarize([r for r in records if r['case']==c['name']]) for c in load(RUN/'cases.json')},
        records=records,metadata_sha256=hashes,code_sha256=sha(Path(__file__)))
    (BASE/'evaluator_diagnosis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result['summary'],indent=2))
    print(json.dumps(result['by_case'],indent=2))
    print('Worst-edge decisions before detours:')
    print(json.dumps([r for r in records if r['case']=='edge_biased_320109' and r['at_action'] in (20,117,141,157)],indent=2))


if __name__=='__main__': main()
