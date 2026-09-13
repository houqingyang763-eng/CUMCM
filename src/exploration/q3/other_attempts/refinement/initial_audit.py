"""随机例两点后，公开几何可提供的直接清除候选；不改控制器。"""
import json
from pathlib import Path
from posterior import a
from refined import clearing_plans

root=Path(__file__).resolve().parent/'runs/random_audit'
case=json.loads((root/'cases.json').read_text())[0]
p=root/case['name']/'f3'
actions=[json.loads(x) for x in (p/'actions.jsonl').read_text().splitlines()]
s=a.CoverageInformationState()
for row in actions[:40]:s.update(row,row['response'])
plans=[]
for c in s.channels.values():
    if c.status=='found':
        opts=clearing_plans(s,c)
        plans.append({'channel':c.channel,'radius_m':c.circle()[1],
                      'direct_options':[{'id':o['id'],'worst_local_s':o['worst_local_s']} for o in opts]})
result={'prefix':40,'position':s.position,'chosen_action':actions[40],
        'clear_candidates':plans,'scope':'public_state_feasibility_only_not_full_cost_comparison'}
a.base.dump(root/'initial_service_audit.json',result)
print(json.dumps(plans,ensure_ascii=False))
