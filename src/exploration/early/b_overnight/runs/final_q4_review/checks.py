"""最终Q4审查的有限构造检查；不调用官方接口、不新增完整性能案例。"""
from fractions import Fraction as F
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from astra_guard import check_cached
from q4_anchor_design import Q4_SYMMETRIC25_ANCHORS, Q4Symmetric25Policy
from q4_joint_state import Q4JointCoverageInformationState, joint_cell_certificate
from q4_coverage import Q4CoverageCertificate, Q4CoverageLeaf, verify_q4_certificate
from coverage import Box
from q4 import Q4Config
from q4_compare import factories
from simulation import Scenario, Source, LocalEnvironment
from state import audit_state
import geometry as g

check_cached()
out = Path(__file__).parent
proof = json.loads((ROOT / 'runs/q4_anchor_design/symmetric25_geometry/symmetric25_geometry.json').read_text(encoding='utf-8'))
points = [tuple(q) for q in proof['points']]
assert tuple(points) == Q4_SYMMETRIC25_ANCHORS
triangles = proof['triangulation']
assert len(triangles) == 36
exact_edges2 = []
for tri in triangles:
    for i,j in ((tri[0],tri[1]),(tri[1],tri[2]),(tri[2],tri[0])):
        edge2 = sum((F(points[i][k])-F(points[j][k]))**2 for k in (0,1))
        assert edge2 < 1000**2
        exact_edges2.append(edge2)
hull = g.hull(points)
assert len(hull) == 12
for a,b in zip(hull,hull[1:]+hull[:1]):
    ax,ay,bx,by = map(F, (*a,*b))
    cross = ax*by-ay*bx
    length2 = (bx-ax)**2+(by-ay)**2
    assert cross > 0 and cross**2 > 1800**2*length2
d = proof['certificate']
leaves = tuple(Q4CoverageLeaf(Box(*leaf['bounds'],code=leaf['code'],depth=leaf['depth']),
                              leaf['kind'],tuple(leaf['hull_indices'])) for leaf in d['leaves'])
cert = Q4CoverageCertificate(d['domain_radius_m'], d['reception_radius_m'],
       tuple(map(tuple,d['measurements'])), leaves, d['boxes_visited'], d['requested_depth'],
       d['safety_margin_m'], d['rational_verified'])
assert verify_q4_certificate(cert,require_complete=True)

# Q4未知源不能因一个距格中心<1000的阴性直接约束整格方向。
poly=[(-20,-10),(20,-10),(20,10),(-20,10)]
whole=joint_cell_certificate(poly,[(0,500)],[(990,0)])
assert not whole['discarded'] and whole['omni_possible']
assert not whole['effective_negative_positions']
# 大格跨越观测点，仍含物理相容位置(300,0)，不能以代表点不相容删格。
spanning=joint_cell_certificate([(-10,-10),(310,-10),(310,10),(-10,10)],
                                [(1450,-190),(1450,190)],[(150,0)])
assert not spanning['discarded']

# 只作空频道控制流检查；零源不是题面完整案例。
check_cached()
empty = LocalEnvironment(Scenario('all_empty_control_unit',0,'unit','zero',()))
state = Q4JointCoverageInformationState()
policy = Q4Symmetric25Policy(reference_only=True)
actions=[]
while not state.complete:
    if len(actions)%10==0: check_cached()
    assert len(actions)<600
    action=policy.choose(state)
    response=empty.act(action)
    state.update(action,response)
    audit_state(state,empty)
    actions.append(action)
assert len(actions)==500
assert set(a['position'] for a in actions)==set(Q4_SYMMETRIC25_ANCHORS)
assert all(a['reason']=='q4_symmetric25_fallback_discovery' for a in actions)
assert all(p['kind']=='q4_local_hull_union' for p in state.absence_proofs.values())

# 单源清除控制流：接收半圆朝西，清除仍按<=20米，与方向无关。
env=LocalEnvironment(Scenario('strip_clear_control_unit',0,'unit','zero',(Source(1,(1499,26),1500,180),)))
known=Q4JointCoverageInformationState()
first=dict(kind='measure',position=(0,0),channel=1)
known.update(first,env.act(first))
assert known.channels[1].status=='found'
for j in range(2,21): known.channels[j].status='absent'
policy2=Q4Symmetric25Policy(reference_only=True)
clear_actions=[]
while not known.complete:
    if len(clear_actions)%10==0: check_cached()
    assert len(clear_actions)<100
    action=policy2.choose(known)
    assert action['kind']=='clear'
    response=env.act(action)
    known.update(action,response)
    audit_state(known,env)
    clear_actions.append(action)
assert env.cleared=={1}
policy_cls,state_cls,config=factories('joint25')
assert policy_cls is Q4Symmetric25Policy and state_cls is Q4JointCoverageInformationState
trigger=[]
for attr,value in [('actions',1000),('virtual_time_s',12000)]:
    s=state_cls()
    setattr(s,attr,value)
    p=policy_cls(config)
    a=p.choose(s)
    assert p.fallback_started and 'fallback' in a['reason']
    trigger.append(dict(attribute=attr,value=value,reason=a['reason']))

# 两个发现阶段都计满，给实际继承链留保守上界。
D=5000
adaptive=12000+2*D/5+6
discovery25=(D+1888)/5+24*2*1888/5+20*25*6
discovery37=(D+2700)/5+36*2*2700/5+20*37*6
clear16=16*(2*D/5+(2966.4+1600)/5+99*3+5)
total=adaptive+discovery25+discovery37+clear16
assert total<100*3600 and 1000+500+740+1600<5000
result=dict(exact_triangle_edges_and_polygon_inradius=True, serialized_certificate_verified=True,
    cell_wide_negative_reception_check=True, possible_position_in_large_cell_kept=True,
    empty_control=dict(actions=len(actions),positions=len(set(a['position'] for a in actions)),
                       virtual_time_s=empty.virtual_time_s,all_twenty_certified=True),
    clear_control=dict(clear_actions=len(clear_actions),all_cleared=True,virtual_time_s=env.virtual_time_s),
    budget_triggers=trigger, bound_s=dict(adaptive=adaptive,discovery25=discovery25,discovery37=discovery37,
                                       clear16=clear16,total=total),max_actions=3840,
    config=config.to_dict(),code_sha256={})
for path in [ROOT/n for n in ('q4_anchor_design.py','q4_joint_state.py','q4_compare.py','q4.py','q4_coverage.py',
                               'q4run.py','q2_geometry.py','task_cost.py')]+[ROOT.parent/'b_adaptive_q3'/n for n in ('state.py','policy.py','geometry.py')]:
    result['code_sha256'][str(path.relative_to(ROOT.parent))]=hashlib.sha256(path.read_bytes()).hexdigest()
(out/'checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k not in ('config','code_sha256')},ensure_ascii=False))
