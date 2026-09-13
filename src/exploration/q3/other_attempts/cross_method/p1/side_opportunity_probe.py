"""只读重放 A 公开日志，检查当前横向测点换侧与一对一删站的几何机会。

不调用 choose/simulate，不载入案例真值，不写回任何策略或历史日志。
输出是公开状态下的条件计划检查，名义省时不代表真实整局收益。
"""
import argparse
import copy
import hashlib
import json
import math
import platform
import sys
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE))
from light_route import a, cr, nominal
from refined import transverse_points

DEFAULT_INPUT = ROOT / 'outputs/experiments/b_q3_p1/light_screening_20260913/A'
DEFAULT_OUTPUT = ROOT / 'outputs/experiments/b_q3_p1/side_probe_20260913/probe.json'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path):
    return path.resolve().relative_to(ROOT).as_posix()


def unique_by_action(values):
    result = {v['at_action']: v for v in values}
    assert len(result) == len(values), '一个公开状态有多个同类日志，不能静默选一个'
    return result


def verify_snapshot(state, logged, channel):
    current = a.base.visible_snapshot(state, channel)
    assert math.dist(current['position'], logged['position']) < 1e-8
    assert abs(current['virtual_time_s'] - logged['virtual_time_s']) < 1e-7
    for key in ('measuring_channel', 'counts', 'ever_seen_count'):
        assert current[key] == logged[key], (key, current[key], logged[key])
    for key in ('channel', 'status', 'directions', 'measurements'):
        assert current['selected_channel'][key] == logged['selected_channel'][key]
    if current['selected_channel']['status'] == 'found':
        assert math.dist(current['selected_channel']['center'], logged['selected_channel']['center']) < 1e-7
        assert abs(current['selected_channel']['radius_m'] - logged['selected_channel']['radius_m']) < 1e-7


def certificate(past, route, cache):
    circles = list(past) + [(tuple(v['position']), 1000.) for v in route if v.get('scan_unknown')]
    key = tuple(sorted(set((tuple(q), radius) for q, radius in circles)))
    if key not in cache:
        proof = cr.coverage_certificate(key)
        cache[key] = dict(complete=proof.complete, rational_verified=proof.rational_verified)
    return dict(cache[key])


def certified(value):
    return value['complete'] and value['rational_verified']


def inspect_start(state, row, plan, decision, case):
    route = copy.deepcopy(plan['after_route'])
    first = route[0]
    channel = first['channel']
    c = state.channels[channel]
    points = transverse_points(state, c)
    chosen_side = min(range(2), key=lambda i: math.dist(points[i], row['position']))
    assert math.dist(points[chosen_side], row['position']) < 1e-5, '实际动作不是现有两侧点'
    alternative = points[1 - chosen_side]
    plan_scan = bool(first.get('scan_unknown'))
    chosen_id = decision['chosen'] if decision else 'original_without_refinement_record'
    # planned_transverse_scan 的 super().choose_joint 已执行 start_station，
    # 所以决策记录里的 pending 标志应当与路线首服务任务相同。
    if decision:
        assert decision['original_reason'] == 'planned_transverse_scan'
        assert decision['channel'] == channel
        assert decision['scan_unknown'] == plan_scan, '路线标签与原动作 pending 不一致'
        assert math.dist(decision['original_action']['position'], first['position']) < 1e-5
        assert row.get('refinement_choice') == chosen_id
    actual_scan = plan_scan
    if decision and chosen_id != 'original':
        option = next(v for v in decision['options'] if v['id'] == chosen_id)
        assert option['kind'] == 'scan'
        assert math.dist(option['q'], row['position']) < 1e-5
        actual_scan = bool(option['scan_unknown'])
    else:
        assert math.dist(first['position'], row['position']) < 1e-5
    # 最终 mirror 选择可更换坐标或扫描标签，两项均对齐到实际即将执行的站。
    first['position'] = tuple(row['position'])
    first['scan_unknown'] = actual_scan
    past = cr.common_negative_circles(state)
    cache = {}
    original_proof = certificate(past, plan['after_route'], cache)
    aligned_proof = certificate(past, route, cache)
    assert certified(original_proof), '历史 A 原计划不具有连续证书'
    unknown = sum(v.status == 'unknown' for v in state.channels.values())
    assert unknown == plan['unknown']
    opposite_unmeasured = not any(math.dist(alternative, q) < 1e-3 for q in c.measured)
    record = dict(
        case=case, at_action=state.actions, next_action_step=row['step'],
        public_position=state.position, unknown_channels=[j for j, v in state.channels.items() if v.status == 'unknown'],
        channel=channel, target_support=c.support(), target_circle=c.circle(),
        target_measured=sorted(c.measured), common_negative_circles=past,
        actual_action={k: row[k] for k in ('kind', 'position', 'channel', 'reason')},
        f3_chosen=chosen_id, f3_options=[] if not decision else [
            {k: v[k] for k in ('id', 'kind', 'q', 'scan_unknown', 'mean_s') if k in v}
            for v in decision.get('options', [])],
        plan_first_scan_unknown=plan_scan,
        original_pending_scan_unknown=None if not decision else decision['scan_unknown'],
        actual_scan_unknown=actual_scan, pending_alignment_source='chosen_scan_option' if decision and chosen_id != 'original' else 'original_start_station',
        original_plan_route=copy.deepcopy(plan['after_route']), actual_aligned_route=route,
        original_plan_certificate=original_proof, actual_aligned_certificate=aligned_proof,
        original_chosen_side=chosen_side, opposite_position=alternative,
        opposite_unmeasured=opposite_unmeasured,
        nominal_before_s=nominal(state.position, route, unknown), trials=[],
    )
    for condition in ('fixed_labels', 'allow_enable'):
        if not opposite_unmeasured or (condition == 'fixed_labels' and not actual_scan):
            continue
        for index, stop in enumerate(route):
            if stop['kind'] != 'scan':
                continue
            trial = copy.deepcopy(route)
            trial[0]['position'] = alternative
            if condition == 'allow_enable':
                trial[0]['scan_unknown'] = True
            removed = trial.pop(index)
            proof = certificate(past, trial, cache)
            after = nominal(state.position, trial, unknown)
            saving = record['nominal_before_s'] - after
            record['trials'].append(dict(
                condition=condition, removed_index=index, removed_job=removed,
                final_service_scan_unknown=trial[0]['scan_unknown'],
                certificate=proof, nominal_after_s=after, nominal_saving_s=saving,
                positive_nominal=saving > 1e-7,
                eligible_exchange=certified(aligned_proof) and certified(proof) and saving > 1e-7,
            ))
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=DEFAULT_INPUT)
    parser.add_argument('--out', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    base, out = args.input.resolve(), args.out.resolve()
    assert out.is_relative_to(ROOT / 'outputs/experiments')
    assert not out.parent.exists(), '仅允许创建尚不存在的证据目录'
    directories = sorted(p for p in base.iterdir() if p.is_dir())
    assert len(directories) == 8
    logs = [d / name for d in directories for name in ('actions.jsonl', 'metadata.json')]
    # 记录本进程实际导入的仓库源文件。包括导入但未调用的环境定义，
    # 并不表示运行过环境；唯一状态推进来源是历史 actions.jsonl 的 response。
    source_paths = {Path(__file__).resolve()}
    for module in tuple(sys.modules.values()):
        path = getattr(module, '__file__', None)
        if path:
            path = Path(path).resolve()
            if path.is_relative_to(ROOT) and path.suffix == '.py':
                source_paths.add(path)
    inputs = dict(source_sha256={relative(p): sha(p) for p in sorted(source_paths)},
                  public_log_sha256={relative(p): sha(p) for p in logs})
    cases, records = [], []
    total = Counter()
    for directory in directories:
        meta = json.loads((directory / 'metadata.json').read_text(encoding='utf-8'))
        assert meta['lightweight']['mode'] == 'A'
        plans = unique_by_action(meta['lightweight']['online_plans'])
        decisions = unique_by_action(meta['refinement_decisions'])
        state, counts = a.CoverageInformationState(), Counter()
        for line in (directory / 'actions.jsonl').read_text(encoding='utf-8').splitlines():
            row = json.loads(line)
            assert row['step'] == state.actions + 1
            verify_snapshot(state, row['before'], row['channel'])
            plan = plans.get(state.actions)
            if plan and plan['unknown'] and plan['after_route'] and plan['after_route'][0]['kind'] == 'service':
                counts['current_service_plans'] += 1
                channel = plan['after_route'][0]['channel']
                # 同点队列不是新站；current_view 不是横向移动；第一服务任务必须
                # 真正成为此步动作，避免将未来计划或被 multiclear 替换的任务算入。
                if (row['kind'] == 'measure' and row['channel'] == channel
                        and row['reason'] in ('planned_transverse_scan', 'refined_shared_scan')
                        and math.dist(state.position, row['position']) > 1e-3
                        and state.channels[channel].status == 'found'):
                    r = inspect_start(state, row, plan, decisions.get(state.actions), directory.name)
                    records.append(r)
                    counts['actual_transverse_starts'] += 1
                    counts['opposite_unmeasured'] += int(r['opposite_unmeasured'])
                    counts['f3_already_mirror'] += int(r['f3_chosen'].startswith('mirror'))
                    scans = sum(v['kind'] == 'scan' for v in r['actual_aligned_route'])
                    counts['with_future_pure_station'] += int(scans > 0)
                    counts['already_scans_unknown'] += int(r['actual_scan_unknown'])
                    counts['with_station_and_unknown_scan'] += int(scans > 0 and r['actual_scan_unknown'])
                    counts['plan_actual_scan_flag_differences'] += int(r['plan_first_scan_unknown'] != r['actual_scan_unknown'])
                    counts['original_pending_verified'] += int(r['original_pending_scan_unknown'] is not None)
                    counts['actual_aligned_route_certified'] += int(certified(r['actual_aligned_certificate']))
                    for condition in ('fixed_labels', 'allow_enable'):
                        trials = [t for t in r['trials'] if t['condition'] == condition]
                        counts[condition + '_pair_attempts'] += len(trials)
                        counts[condition + '_states_certificate_feasible'] += int(any(certified(t['certificate']) for t in trials))
                        counts[condition + '_states_positive_exchange'] += int(any(t['eligible_exchange'] for t in trials))
            state.update(row, row['response'])
            verify_snapshot(state, row['after'], row['channel'])
            counts['historical_actions_replayed'] += 1
        assert state.complete
        total.update(counts)
        cases.append(dict(case=directory.name, counts=dict(counts)))
    for field in inputs.values():
        assert all(sha(ROOT / path) == value for path, value in field.items()), '读取过程中输入发生变化'
    result = dict(
        schema='p1_side_opportunity_probe_v1', python=platform.python_version(),
        input_directory=relative(base), evidence_kind='只读公开反馈重放和条件计划几何检查',
        scope='固定 A 的 8 条历史轨迹；不运行策略，不读取案例真值，不能推断隐藏测试或未访问状态',
        current_start_definition='有在线计划，首任务为服务，未知频道非空；当前实际动作服务同一频道，是移动到横向点的测量；排除原地、队列、清除和未来任务',
        cost_definition='当前整条路线长度/5 + 6*未知频道数*计划扫描标签数；这是名义费用，不是实际动作账单',
        limits=['换侧可能改变定位信息和以后反馈，覆盖可行不等于收益',
                'allow_enable 包含 fixed_labels 的重复几何候选，不作为两个独立样本相加',
                '将原计划首点替成 F3 实际 mirror 后失去计划证书，仅诊断静态路线失配；滚动重规划可完成，不能判整局失败',
                '即使计划删站可行，执行仍可能重规划重新加站，需后续实际日志确认'],
        fingerprints=inputs, input_hashes_unchanged=True, cases=cases, totals=dict(total), starts=records,
    )
    out.parent.mkdir(parents=True, exist_ok=False)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(output=relative(out), totals=dict(total)), ensure_ascii=False))


if __name__ == '__main__':
    main()
