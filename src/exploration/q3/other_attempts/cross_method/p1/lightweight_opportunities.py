"""仅检查旧F3公开轨迹中的查漏机会，不选新动作、不运行策略。"""
import hashlib
import json
import math
from pathlib import Path

from p1_run import ROOT, a, load
from covering_route import SAMPLE_POINTS

HERE=Path(__file__).resolve().parent
RUN=HERE/'runs/screening_20260913'


def main():
    rows_out=[]
    for item in load(RUN/'manifest.json')['baseline_manifest']['screening_cases']:
        path=ROOT/item['artifacts']['f3/actions.jsonl']['path']
        rows=[json.loads(x) for x in path.read_text(encoding='utf-8').splitlines()]
        state=a.CoverageInformationState(); opportunities=[]; move_boundaries=[]
        for index,row in enumerate(rows):
            if math.dist(state.position,row['position'])>1e-6:
                unknown=[c for c in state.channels.values() if c.status=='unknown']
                signatures={tuple(sorted(tuple(p) for p,result,_ in c.observations if result=='no_signal')) for c in unknown}
                move_boundaries.append(dict(before_step=row['step'],unknown=len(unknown),history_groups=len(signatures)))
            state.update(row,row['response'])
            if row['kind']!='clear' or row['response'].get('clear_result')!='success' or state.complete: continue
            q=state.position; measured_before_departure=set()
            for later in rows[index+1:]:
                if math.dist(later['position'],q)>1e-6: break
                if later['kind']=='measure': measured_before_departure.add(later['channel'])
            missed=[]
            for j,c in state.channels.items():
                if c.status!='unknown' or j in measured_before_departure or tuple(q) in c.measured: continue
                past=[p for p,result,_ in c.observations if result=='no_signal']
                witnesses=[p for p in SAMPLE_POINTS if math.dist(p,q)<=990 and all(math.dist(p,x)>1000 for x in past)]
                if witnesses: missed.append(dict(channel=j,witness_count=len(witnesses)))
            if missed: opportunities.append(dict(clear_step=row['step'],position=q,channels=missed))
        rows_out.append(dict(case=item['name'],opportunities=opportunities,move_boundaries=move_boundaries,
            original_actions_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    report=dict(scope='existing F3 public logs only; not a counterfactual experiment',
        interpretation='Witnesses are coarse geometric opportunity markers, not proven time savings. Repeated opportunities overlap and must not be summed as saved measurements.',
        summary=dict(cases=len(rows_out),cases_with_opportunity=sum(bool(x['opportunities']) for x in rows_out),
            clearance_events_with_opportunity=sum(len(x['opportunities']) for x in rows_out),
            movement_boundaries_with_different_unknown_histories=sum(v['history_groups']>1 for x in rows_out for v in x['move_boundaries'])),
        cases=rows_out,code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (HERE/'lightweight_opportunities.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report['summary'],ensure_ascii=False,indent=2))


if __name__=='__main__': main()
