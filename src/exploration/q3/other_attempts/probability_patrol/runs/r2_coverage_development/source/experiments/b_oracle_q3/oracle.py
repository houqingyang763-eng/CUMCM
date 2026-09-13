"""Q3离线真值参照：整数动态规划、清除圆盘路线下界、可行全清轨迹。"""
from array import array
from fractions import Fraction
from itertools import permutations
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parent
EXPERIMENTS = ROOT.parent
REPO = EXPERIMENTS.parent
SCALE = 1_000_000  # 米转微米，整数边长向下取整
INF = 2**62


def distance_floor(a, b):
    """对加载后的binary64坐标精确转有理数，再精确取欧氏距离的微米下界。"""
    dx = Fraction(a[0]) - Fraction(b[0])
    dy = Fraction(a[1]) - Fraction(b[1])
    squared = (dx*dx + dy*dy) * SCALE*SCALE
    return math.isqrt(squared.numerator // squared.denominator)


def weights(points, disks=False):
    start = [max(0, distance_floor((0., 0.), p) - (20*SCALE if disks else 0)) for p in points]
    edges = [[max(0, distance_floor(a, b) - (40*SCALE if disks else 0))
              for b in points] for a in points]
    return start, edges


def shortest_open_path(start, edges):
    """从原点出发、不返回原点的Hamilton路径。输入是整数，组合最优无浮点误差。"""
    n = len(start)
    if n == 0:
        return 0, []
    assert 1 <= n <= 16 and len(edges) == n
    size = 1 << n
    dp = array('q', [INF]) * (size*n)
    parent = array('b', [-1]) * (size*n)
    for j in range(n):
        dp[(1 << j)*n+j] = start[j]
    for mask in range(1, size):
        bitset = mask
        while bitset:
            bit = bitset & -bitset
            j = bit.bit_length()-1
            previous = mask ^ bit
            if previous:
                best, best_i = INF, -1
                remaining = previous
                offset = previous*n
                while remaining:
                    b = remaining & -remaining
                    i = b.bit_length()-1
                    candidate = dp[offset+i] + edges[i][j]
                    if candidate < best:
                        best, best_i = candidate, i
                    remaining ^= b
                dp[mask*n+j], parent[mask*n+j] = best, best_i
            bitset ^= bit
    mask = size-1
    j = min(range(n), key=lambda k: dp[mask*n+k])
    value, order = dp[mask*n+j], []
    while mask:
        order.append(j)
        i = parent[mask*n+j]
        mask ^= 1 << j
        j = i
    return value, list(reversed(order))


def solve(case):
    began = time.perf_counter()
    sources = case['sources']
    points = [tuple(s['position']) for s in sources]
    n = len(points)
    assert 10 <= n <= 16 and len({s['channel'] for s in sources}) == n
    assert all(s.get('orientation') is None for s in sources)
    assert all(math.hypot(*p) <= 1800+1e-8 for p in points)
    center_length, order = shortest_open_path(*weights(points))
    disk_length, relaxed_order = shortest_open_path(*weights(points, disks=True))
    # 独立单边最短间隔不能总同时实现，因此disk_length只是下界，不能当路线。
    coarse = max(0, center_length - 20*SCALE*(2*n-1))
    lower_micrometres = max(coarse, disk_length)
    current, move, actions = (0., 0.), 0., []
    for i in order:
        p = points[i]
        segment = math.dist(current, p)
        move += segment/5
        actions.append(dict(kind='clear', channel=sources[i]['channel'], position=p,
                            move_s=segment/5, operation_s=5, virtual_time_s=move+5*len(actions)+5))
        current = p
    total = move+5*n
    lower = lower_micrometres / SCALE/5+5*n
    assert center_length/SCALE-1e-8 <= move*5 <= (center_length+n)/SCALE+1e-8
    assert lower <= total+1e-8
    return dict(case=case['name'], source_count=n, center_order=order,
                center_integer_optimum_um=center_length,
                relaxed_disk_integer_optimum_um=disk_length,
                relaxed_disk_order_not_a_feasible_route=relaxed_order,
                lower_bound_s=lower, oracle_feasible_s=total, oracle_move_s=move,
                unavoidable_clear_s=5*n, ideal_interval_width_s=total-lower,
                lower_bound_per_source_s=lower/n, oracle_per_source_s=total/n,
                wall_s=time.perf_counter()-began, actions=actions)


def summarize(v):
    v = sorted(v)
    return dict(mean=statistics.mean(v), maximum=max(v),
                tail_quarter_mean=statistics.mean(v[-math.ceil(len(v)/4):]))


def main():
    out = ROOT / 'runs' / 'sweep_validation_48100'
    out.mkdir(parents=True, exist_ok=False)
    case_path = EXPERIMENTS / 'b_overnight/runs/q3_sweep_validation/cases.json'
    result_path = case_path.with_name('results.json')
    cases = json.loads(case_path.read_text(encoding='utf-8'))
    policies = json.loads(result_path.read_text(encoding='utf-8'))
    sys.path.insert(0, str(EXPERIMENTS / 'b_adaptive_q3'))
    from simulation import LocalEnvironment, Scenario
    answers = []
    for case in cases:
        answer = solve(case)
        environment = LocalEnvironment(Scenario.from_dict(case))
        for a in answer['actions']:
            response = environment.act({k: a[k] for k in ('kind', 'channel', 'position')})
            assert response['clear_result'] == 'success'
            assert abs(response['virtual_time_s']-a['virtual_time_s']) < 1e-7
        assert len(environment.cleared) == answer['source_count']
        answer['local_environment_verified'] = True
        answers.append(answer)
        (out / 'results.json').write_text(json.dumps(answers, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print(json.dumps({k: answer[k] for k in ('case','lower_bound_s','oracle_feasible_s','wall_s')}), flush=True)
    by_case = {r['case']: r for r in answers}
    summary = {}
    for name, key in [('lower_bound','lower_bound_s'),('oracle_centers','oracle_feasible_s')]:
        summary[name] = dict(per_source=summarize([r[key]/r['source_count'] for r in answers]),
                             total=summarize([r[key] for r in answers]))
    for name in dict.fromkeys(r['policy'] for r in policies):
        selected = [r for r in policies if r['policy'] == name]
        assert len(selected) == len(cases) and {r['case'] for r in selected} == set(by_case)
        assert all(r['success'] and r['cleared'] == r['source_count'] == by_case[r['case']]['source_count'] for r in selected)
        ratios = [r['virtual_time_s']/by_case[r['case']]['oracle_feasible_s'] for r in selected]
        gaps = [r['virtual_time_s']-by_case[r['case']]['oracle_feasible_s'] for r in selected]
        summary[name] = dict(per_source=summarize([r['virtual_time_s']/r['source_count'] for r in selected]),
                             total=summarize([r['virtual_time_s'] for r in selected]),
                             mean_case_ratio_to_oracle=statistics.mean(ratios),
                             excess_total_s_mean=statistics.mean(gaps),
                             direct_sensing_switch_mean_s=statistics.mean(r['measure_s']+r['switch_s'] for r in selected),
                             excess_movement_mean_s=statistics.mean(r['move_s']-by_case[r['case']]['oracle_move_s'] for r in selected))
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    inputs = [case_path, result_path, Path(__file__), EXPERIMENTS/'b_adaptive_q3/simulation.py', EXPERIMENTS/'b_adaptive_q3/geometry.py']
    manifest = dict(scale=SCALE, starting_point=[0,0], return_to_origin=False,
                    official_cases_used=False, cases=len(cases), all_oracle_cleared=True,
                    sha256={str(p.relative_to(REPO)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs})
    (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
