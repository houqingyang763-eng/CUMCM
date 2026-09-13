"""逐频道的已测记忆、计划扫描分配和连续覆盖证明。"""
import math
from covering_route import SAMPLE_POINTS,CANDIDATE_POINTS,insertion,optimize_route,route_length
from coverage_state import coverage_certificate


def negative_circles(c):
    return [(q,1000.) for q,result,_ in c.observations if result=='no_signal']


def channel_route(state,service_jobs):
    unknown=[j for j,c in state.channels.items() if c.status=='unknown']
    jobs=[dict(job,channels=[],scan_unknown=False) for job in service_jobs]
    if not unknown:return optimize_route(state.position,jobs),{'per_channel':{},'planned_jobs':jobs}
    past={j:negative_circles(state.channels[j]) for j in unknown}
    points=list(SAMPLE_POINTS)+list(state.discovery_points(limit=24))
    points=list(dict.fromkeys(tuple(p) for p in points))
    required={j:sum(1<<i for i,p in enumerate(points) if all(math.dist(p,q)>=r-1e-7 for q,r in past[j])) for j in unknown}
    masks={}
    def mask(q):
        q=tuple(q)
        if q not in masks:masks[q]=sum(1<<i for i,p in enumerate(points) if math.dist(p,q)<=990.)
        return masks[q]
    route=optimize_route(state.position,jobs)
    remaining=required.copy()
    for job in route:
        for j in unknown:
            gain=remaining[j]&mask(job['position'])
            if gain:job['channels'].append(j);remaining[j]&=~mask(job['position'])
    candidates=list(dict.fromkeys(list(CANDIDATE_POINTS)+[tuple(state.position)]+[tuple(j['position']) for j in jobs]))
    for _ in range(30):
        if not any(remaining.values()):break
        choices=[]
        for q in candidates:
            js=[j for j in unknown if remaining[j]&mask(q)]
            if not js:continue
            gain=sum((remaining[j]&mask(q)).bit_count() for j in js)
            extra,index=insertion(state.position,route,q)
            choices.append(((extra/5+6*len(js))/gain,extra,q,index,js))
        if not choices:raise AssertionError('uncovered channel witness without candidate')
        _,_,q,index,js=min(choices)
        # Existing service stops are augmented instead of adding duplicate travel stops.
        same=next((job for job in route if math.dist(q,job['position'])<1e-6),None)
        if same is None:route.insert(index,{'kind':'scan','position':q,'channels':js,'scan_unknown':True})
        else:same['channels']=sorted(set(same['channels'])|set(js))
        for j in js:remaining[j]&=~mask(q)
    def cert(j,omit=None):
        circles=past[j]+[(job['position'],1000.) for k,job in enumerate(route) if j in job['channels'] and k!=omit]
        return coverage_certificate(circles)
    # Repair continuous slivers independently for each channel; never mutate state.
    for j in unknown:
        for _ in range(20):
            proof=cert(j)
            if proof.complete:break
            points=proof.witness_points() or tuple(b.point_in_domain(1800) for b in proof.unresolved)
            points=[p for p in points if p is not None]
            q=min(points,key=lambda p:insertion(state.position,route,p)[0])
            _,index=insertion(state.position,route,q)
            same=next((job for job in route if math.dist(q,job['position'])<1e-6),None)
            if same is None:route.insert(index,{'kind':'scan','position':q,'channels':[j],'scan_unknown':True})
            elif j not in same['channels']:same['channels'].append(j)
            else:raise AssertionError('continuous repair made no progress')
        if not cert(j).complete:raise AssertionError('continuous channel cover incomplete')
    # Drop assignments only with a continuous certificate, never just grid coverage.
    for i,job in enumerate(route):
        for j in list(job['channels']):
            if cert(j,omit=i).complete:job['channels'].remove(j)
    route=[job for job in route if job['kind']=='service' or job['channels']]
    for job in route:job['scan_unknown']=bool(job['channels'])
    route=optimize_route(state.position,route)
    proofs={j:cert(j) for j in unknown}
    assert all(p.complete and p.rational_verified for p in proofs.values())
    return route,{'planned_jobs':route,'planned_route_m':route_length(state.position,route),
        'per_channel':{j:{'actual_negative_scans':len(past[j]),
            'planned_scans':sum(j in job['channels'] for job in route),
            'conditional_coverage_complete':p.complete} for j,p in proofs.items()}}
