"""第三问概率巡检实验运行器：冻结基线、同案配对、独立计费与失败保留。"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import multiprocessing as mp
import platform
import random
import statistics
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
for folder in (ROOT / 'experiments/b_adaptive_q3',
               ROOT / 'experiments/b_benchmark_scale', HERE):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from simulation import LocalEnvironment, Scenario, Source, generate
from state import InformationState, audit_state


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def make_cases(stage):
    """开发包含已知共线退化例；新验证种子不进入参数选择。"""
    if stage in ('development', 'holdout'):
        base, repeats = (170100, 1) if stage == 'development' else (180100, 2)
        cases = []
        for layout in ('uniform', 'edge', 'cluster', 'line'):
            for noise in ('smooth', 'biased', 'hashed'):
                for _ in range(repeats):
                    seed = base + len(cases)
                    if stage == 'development' and layout == 'edge' and noise == 'biased':
                        seed = 161104
                    cases.append(generate(seed, layout, noise))
        return cases
    if stage != 'stress':
        raise ValueError(stage)
    cases = []
    for i in range(8):
        seed, n = 190100 + i, 10 if i % 2 == 0 else 16
        rng = random.Random(seed)
        channels = rng.sample(range(1, 21), n)
        sources = []
        for k, channel in enumerate(channels):
            if i < 4:
                angle = 2 * math.pi * k / n + (i // 2) * math.pi / 6
                point = (1800 * math.cos(angle), 1800 * math.sin(angle))
            elif i < 6:
                point = (0., 0.) if k < 3 else (1200 + (k - 3) * .01, 0.)
            else:
                point = (-1799 + 3598 * k / (n - 1), (k % 2) * .01)
            sources.append(Source(channel, point, 1000.))
        cases.append(Scenario(f'stress_{i}_{seed}', seed, 'stress',
                              'biased' if i % 2 else 'zero', tuple(sources)))
    return cases


def read_cases(path):
    cases = [Scenario.from_dict(x) for x in json.loads(Path(path).read_text(encoding='utf-8'))]
    if not cases or len({c.name for c in cases}) != len(cases):
        raise ValueError('案例为空或名称重复')
    for case in cases:
        if not 10 <= len(case.sources) <= 16:
            raise ValueError(f'{case.name}: 源数不符合第三问')
        if len({s.channel for s in case.sources}) != len(case.sources):
            raise ValueError(f'{case.name}: 频道重复')
        if not all(1 <= s.channel <= 20 and s.orientation is None
                   and 1000 <= s.radius <= 1500
                   and math.hypot(*s.position) <= 1800 + 1e-6 for s in case.sources):
            raise ValueError(f'{case.name}: 位置、频道、接收半径或方向不符合第三问')
    return cases


def independent_cost(previous, measuring_channel, action, response):
    """不读取 response.costs 或环境内部累计值，按题面独立重算。"""
    result = dict(move_s=math.dist(previous, action['position']) / 5.,
                  measure_s=0., switch_s=0., success_clear_s=0., fail_clear_s=0.)
    if action['kind'] == 'measure':
        result['measure_s'] = 5.
        result['switch_s'] = float(measuring_channel != action['channel'])
        measuring_channel = action['channel']
    elif action['kind'] == 'clear':
        key = 'success_clear_s' if response['clear_result'] == 'success' else 'fail_clear_s'
        result[key] = 5. if key == 'success_clear_s' else 3.
    else:
        raise ValueError('未知动作')
    return result, measuring_channel


def visible_snapshot(state, channel=None):
    counts = {name: sum(c.status == name for c in state.channels.values())
              for name in ('unknown', 'found', 'absent', 'cleared')}
    result = dict(position=state.position, measuring_channel=state.measuring_channel,
                  virtual_time_s=state.virtual_time_s, counts=counts,
                  ever_seen_count=len(state.ever_seen))
    if channel is not None:
        c = state.channels[channel]
        detail = dict(channel=channel, status=c.status,
                      directions=sum(o[1] == 'direction' for o in c.observations),
                      measurements=len(c.observations))
        if c.status == 'found':
            center, radius = c.circle()
            detail.update(center=center, radius_m=radius)
        result['selected_channel'] = detail
    return result


def create_policy(name, config):
    if name == 'baseline':
        from two_stage import TwoStagePolicy, CONFIGS
        return TwoStagePolicy(CONFIGS['scan7_r60']), InformationState()
    if name == 'patrol':
        from patrol import PatrolPolicy
        from coverage_state import CoverageInformationState
        return PatrolPolicy(dict(config)), CoverageInformationState()
    raise ValueError(name)


def resolve_config(raw, policy):
    if policy == 'baseline':
        if raw not in (None, '', 'default', 'scan7_r60', '{}'):
            raise ValueError('baseline 只允许冻结的 scan7_r60')
        return {'baseline_name': 'scan7_r60'}
    if raw in (None, '', 'default'):
        return {}
    if raw.lstrip().startswith('{'):
        value = json.loads(raw)
    elif Path(raw).is_file():
        value = json.loads(Path(raw).read_text(encoding='utf-8'))
    else:
        import patrol
        presets = getattr(patrol, 'CONFIGS', {})
        if raw in presets:
            value = presets[raw]
        elif raw == getattr(patrol, 'DEFAULT_CONFIG', {}).get('name'):
            value = {'name': raw}
        else:
            raise ValueError(f'未知配置名: {raw}')
    if not isinstance(value, dict):
        raise ValueError('策略配置必须为JSON对象')
    return value


def initial_summary(policy, actions):
    metadata = policy.metadata()
    initial_s = metadata.get('initial_finish_s')
    if initial_s is None and isinstance(metadata.get('phase_change'), dict):
        initial_s = metadata['phase_change'].get('time_s')
    if initial_s is None:
        initial = [a for a in actions if a.get('phase') in ('initial', 'initial_scan', 'scan', 'opening')]
        if initial:
            initial_s = initial[-1]['response']['virtual_time_s']
    return metadata, initial_s


def execute_case(case_data, name, config, case_dir, limits):
    """子进程入口；真值仅环境/核验器可见，不交给策略。"""
    case_dir = Path(case_dir)
    case_dir.mkdir(parents=True, exist_ok=True)
    case = Scenario.from_dict(case_data)
    began = time.perf_counter()
    ledger = dict(move_s=0., measure_s=0., switch_s=0., success_clear_s=0., fail_clear_s=0.)
    phases, actions, errors, pending_action = {}, [], None, None
    previous, channel = (0., 0.), 1
    env, state, policy = LocalEnvironment(case), None, None
    result = dict(case=case.name, seed=case.seed, layout=case.layout, noise=case.noise,
                  policy=name, real_n=len(case.sources), source_count=len(case.sources),
                  success=False, cleared=0, total_s=0., per_source_s=None,
                  wall_s=0., actions=0, initial_finish_s=None)
    try:
        policy, state = create_policy(name, config)
        with (case_dir / 'actions.jsonl').open('w', encoding='utf-8', buffering=1) as stream:
            while not state.complete:
                if len(actions) >= limits['action_limit']:
                    raise TimeoutError('action_limit')
                if time.perf_counter() - began > limits['wall_limit_s']:
                    raise TimeoutError('wall_limit')
                decision_began = time.perf_counter()
                action = policy.choose(state)
                decision_wall_s = time.perf_counter() - decision_began
                if action is None:
                    raise AssertionError('state 未完成但策略无动作')
                if action.get('kind') not in ('measure', 'clear'):
                    raise AssertionError('动作类别非法')
                if not all(math.isfinite(v) for v in action['position']) or math.hypot(*action['position']) > 5000 + 1e-5:
                    raise AssertionError('动作坐标非法或超出实验5000米边界')
                before = visible_snapshot(state, action['channel'])
                step_began = time.perf_counter()
                pending_action = dict(action)
                pending_action.update(step=len(actions) + 1, before=before,
                                      decision_wall_s=decision_wall_s)
                response = env.act(action)
                pending_action['response'] = response
                costs, channel = independent_cost(previous, channel, action, response)
                pending_action['independent_costs'] = costs
                for key, value in costs.items():
                    ledger[key] += value
                previous = tuple(action['position'])
                if abs(sum(ledger.values()) - env.virtual_time_s) > 1e-5:
                    raise AssertionError('独立计费与环境不一致')
                state.update(action, response)
                audit_state(state, env)
                phase = action.get('phase', 'unspecified')
                phase_ledger = phases.setdefault(phase, dict(actions=0, **{k: 0. for k in ledger}))
                phase_ledger['actions'] += 1
                for key, value in costs.items():
                    phase_ledger[key] += value
                row = dict(action)
                row.update(step=len(actions) + 1, phase=phase,
                           response=response, independent_costs=costs,
                           before=before, after=visible_snapshot(state, action['channel']),
                           decision_wall_s=decision_wall_s,
                           execute_audit_wall_s=time.perf_counter() - step_began)
                actions.append(row)
                stream.write(json.dumps(row, ensure_ascii=False) + '\n')
                pending_action = None
                result.update(cleared=len(env.cleared), total_s=env.virtual_time_s,
                              actions=len(actions), wall_s=time.perf_counter() - began,
                              phase_costs=phases, **ledger)
                dump(case_dir / 'progress.json', result)
                if env.virtual_time_s > limits['virtual_limit_s']:
                    raise TimeoutError('virtual_time_limit')
                if time.perf_counter() - began > limits['wall_limit_s']:
                    raise TimeoutError('wall_limit')
            if len(env.cleared) != len(case.sources):
                raise AssertionError('宣称完成但真值尚未全清')
            result['success'] = True
            result['per_source_s'] = env.virtual_time_s / len(case.sources)
    except Exception:
        errors = traceback.format_exc()
        if pending_action is not None:
            pending_action['validation_error'] = errors
            actions.append(pending_action)
            with (case_dir / 'actions.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(pending_action, ensure_ascii=False) + '\n')
    try:
        if policy is not None:
            metadata, initial_s = initial_summary(policy, actions)
            dump(case_dir / 'metadata.json', metadata)
            result['initial_finish_s'] = initial_s
    except Exception:
        errors = (errors or '') + '\nmetadata_error:\n' + traceback.format_exc()
        result['success'] = False
        result['per_source_s'] = None
    result.update(cleared=len(env.cleared), total_s=env.virtual_time_s,
                  wall_s=time.perf_counter() - began, actions=len(actions), error=errors,
                  failreason=errors.splitlines()[-1] if errors else None,
                  fail_clears=int(ledger['fail_clear_s'] / 3),
                  measure_count=int(ledger['measure_s'] / 5), phase_costs=phases, **ledger)
    dump(case_dir / 'result.json', result)


def summarize(rows, out):
    successes = [r for r in rows if r['success']]
    stats = dict(cases=len(rows), successes=len(successes), failures=len(rows) - len(successes),
                 all_clear=len(successes) == len(rows), wall_s=sum(r['wall_s'] for r in rows))
    if stats['all_clear']:
        for key in ('total_s', 'per_source_s', 'move_s', 'measure_s', 'switch_s',
                    'success_clear_s', 'fail_clear_s', 'fail_clears', 'measure_count'):
            stats['mean_' + key] = statistics.mean(r[key] for r in rows)
        stats['mean_total_min'] = stats['mean_total_s'] / 60
        stats['max_total_min'] = max(r['total_s'] for r in rows) / 60
        stats['tail_quarter_per_source_s'] = statistics.mean(
            sorted((r['per_source_s'] for r in rows), reverse=True)[:math.ceil(len(rows) / 4)])
        initial = [r['initial_finish_s'] for r in rows if r.get('initial_finish_s') is not None]
        stats['mean_initial_finish_s'] = statistics.mean(initial) if len(initial) == len(rows) else None
    else:
        stats['performance_mean_s'] = None
        stats['note'] = '存在失败，不报告成功子集均值作为整体性能。'
    dump(out / 'results.json', rows)
    dump(out / 'summary.json', stats)
    keys = sorted(set().union(*(r.keys() for r in rows)) - {'phase_costs'})
    with (out / 'results.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        writer.writerows({k: r.get(k) for k in keys} for r in rows)
    lines = ['# 概率巡检配对实验单策略结果', '',
             '自建第三问案例；每次动作独立复算费用，并核对真实位置保留及全清。', '',
             f'全清：{len(successes)}/{len(rows)}。', '']
    if stats['all_clear']:
        lines += [f'平均整局 {stats["mean_total_min"]:.3f} 分钟；逐局每源均值 {stats["mean_per_source_s"]:.3f} 秒。',
                  f'最慢整局 {stats["max_total_min"]:.3f} 分钟；最慢四分之一每源 {stats["tail_quarter_per_source_s"]:.3f} 秒。', '']
    else:
        lines += ['存在失败，整体均值不成立；失败轨迹保留。', '']
    lines += ['| 案例 | 全清 | 源数 | 已清 | 整局/分 | 每源/秒 | 墙钟/秒 | 失败原因 |',
              '|---|---:|---:|---:|---:|---:|---:|---|']
    for r in rows:
        per_source = f'{r["per_source_s"]:.2f}' if r.get('per_source_s') is not None else '—'
        lines.append(f'| {r["case"]} | {r["success"]} | {r["real_n"]} | {r["cleared"]} | {r["total_s"]/60:.2f} | {per_source} | {r["wall_s"]:.2f} | {r.get("failreason") or ""} |')
    lines += ['', '案例数有限；样本最坏值不是总体保证。外生固定误差场和布局均为团队实验设定。', '']
    (out / 'RESULTS.md').write_text('\n'.join(lines), encoding='utf-8')
    return stats


def snapshot_sources(out, policy):
    files = [HERE / 'runner.py']
    files += [ROOT / 'experiments/b_adaptive_q3' / name
              for name in ('geometry.py', 'state.py', 'simulation.py')]
    if policy == 'baseline':
        files += [ROOT / 'experiments/b_adaptive_q3/policy.py',
                  ROOT / 'experiments/b_benchmark_scale/two_stage.py',
                  ROOT / 'experiments/b_overnight/task_cost.py',
                  ROOT / 'experiments/b_oracle_q3/oracle.py']
    else:
        # initial_design/test_validation 是离线研究或测试，不进入运行依赖。
        files += [p for p in HERE.glob('*.py')
                  if p.name not in ('runner.py', 'initial_design.py', 'test_validation.py')]
        files += [ROOT / 'experiments/b_overnight/coverage.py',
                  ROOT / 'experiments/b_oracle_q3/oracle.py']
    hashes = {}
    for path in sorted(set(files)):
        relative = path.relative_to(ROOT)
        target = out / 'source' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
        hashes[str(relative).replace('\\', '/')] = sha(path)
    return hashes


def run_batch(cases, policy, config, out, workers, limits):
    context = mp.get_context('spawn')
    pending = list(enumerate(cases))
    running, completed = {}, {}
    while pending or running:
        while pending and len(running) < workers:
            index, case = pending.pop(0)
            folder = out / 'cases' / case.name
            process = context.Process(target=execute_case,
                                      args=(case.to_dict(), policy, config, folder, limits))
            process.start()
            running[index] = dict(process=process, start=time.perf_counter(), case=case, folder=folder)
        for index, item in list(running.items()):
            process, folder, case = item['process'], item['folder'], item['case']
            exceeded = time.perf_counter() - item['start'] > limits['wall_limit_s'] + 5
            if process.is_alive() and not exceeded:
                continue
            if process.is_alive():
                process.terminate()
            process.join(timeout=5)
            path = folder / 'result.json'
            if path.exists():
                row = json.loads(path.read_text(encoding='utf-8'))
            else:
                progress = folder / 'progress.json'
                row = json.loads(progress.read_text(encoding='utf-8')) if progress.exists() else dict(
                    case=case.name, seed=case.seed, layout=case.layout, noise=case.noise,
                    policy=policy, real_n=len(case.sources), source_count=len(case.sources),
                    cleared=0, total_s=0., actions=0, initial_finish_s=None)
                reason = 'parent_wall_limit' if exceeded else f'worker_exit_{process.exitcode}'
                row.update(success=False, per_source_s=None, error=reason, failreason=reason,
                           wall_s=time.perf_counter() - item['start'])
                dump(path, row)
            completed[index] = row
            print(json.dumps({k: row.get(k) for k in ('case', 'success', 'total_s', 'cleared', 'wall_s', 'failreason')}, ensure_ascii=False), flush=True)
            del running[index]
            dump(out / 'results.partial.json', [completed[i] for i in sorted(completed)])
        if running:
            time.sleep(.1)
    return [completed[i] for i in sorted(completed)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy', choices=('baseline', 'patrol'))
    parser.add_argument('--config')
    parser.add_argument('--cases', type=Path)
    parser.add_argument('--stage', choices=('development', 'holdout', 'stress'))
    parser.add_argument('--generate-only', action='store_true')
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--workers', type=int, default=1)
    parser.add_argument('--action-limit', type=int, default=3000)
    parser.add_argument('--virtual-limit-s', type=float, default=180 * 60)
    parser.add_argument('--wall-limit-s', type=float, default=120.)
    args = parser.parse_args()
    out = args.out.resolve()
    if HERE not in out.parents:
        parser.error('输出必须位于本轮 probability_patrol 目录内')
    if args.workers < 1 or min(args.action_limit, args.virtual_limit_s, args.wall_limit_s) <= 0:
        parser.error('workers 和运行上限必须为正')
    if bool(args.cases) == bool(args.stage):
        parser.error('--cases 与 --stage 必须且只能指定一项')
    out.mkdir(parents=True, exist_ok=False)
    if args.stage:
        cases = make_cases(args.stage)
        dump(out / 'cases.json', [c.to_dict() for c in cases])
    else:
        cases = read_cases(args.cases)
        (out / 'cases.json').write_bytes(args.cases.read_bytes())
    cases = read_cases(out / 'cases.json')
    if args.generate_only:
        print(str(out / 'cases.json'))
        return
    if not args.policy:
        parser.error('运行实验必须给 --policy')
    config = resolve_config(args.config, args.policy)
    limits = dict(action_limit=args.action_limit, virtual_limit_s=args.virtual_limit_s,
                  wall_limit_s=args.wall_limit_s)
    hashes = snapshot_sources(out, args.policy)
    dump(out / 'manifest.json', dict(policy=args.policy, config=config, stage=args.stage,
         case_sha256=sha(out / 'cases.json'), source_sha256=hashes,
         python=platform.python_version(), platform=platform.platform(), workers=args.workers,
         created_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), limits=limits,
         environment='自建第三问；固定空间误差，不读取官方隐藏案例',
         executor='AI', verification='AI独立账本与逐动作几何核验，未标人工复核'))
    began = time.perf_counter()
    rows = run_batch(cases, args.policy, config, out, args.workers, limits)
    stats = summarize(rows, out)
    stats['batch_wall_s'] = time.perf_counter() - began
    drift = [relative for relative, expected in hashes.items() if not (ROOT / relative).exists() or sha(ROOT / relative) != expected]
    stats['source_drift'] = drift
    dump(out / 'summary.json', stats)
    print(json.dumps(stats, ensure_ascii=False), flush=True)
    if drift:
        print('警告：运行期间源码发生变化，须用冻结版本复跑后才能作为最终结果。', flush=True)
    if not stats['all_clear']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
