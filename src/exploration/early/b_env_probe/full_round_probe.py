"""演练专用保守整局基线；用于环境计时，不代表优化后的竞赛策略。"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time
from client import RobotClient, ProbeError


def scan_points():
    """边长 4800 米、600 米间距的 81 个格点，外含目标圆。"""
    coords = list(range(-2400, 2401, 600))
    return [(x, y) for row, y in enumerate(coords)
            for x in (coords if row % 2 == 0 else coords[::-1])]


def clear_candidates(origin, angle):
    """覆盖测向 1500 米范围、约 ±1.005 度扇形的保守条带网格。"""
    theta = math.radians(angle)
    u = (math.cos(theta), math.sin(theta))
    v = (-u[1], u[0])
    rows = (-30, -10, 10, 30)
    for column, x in enumerate(range(0, 1501, 20)):
        for y in (rows if column % 2 == 0 else rows[::-1]):
            yield (origin[0] + x*u[0] + y*v[0], origin[1] + x*u[1] + y*v[1])


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--practice-confirmed', action='store_true')
    parser.add_argument('--problem', choices=['3', '4'], required=True)
    parser.add_argument('--case', required=True, help='当前演练界面案例编码，不是种子')
    parser.add_argument('--port', type=int, default=2026)
    args = parser.parse_args()
    if not args.practice_confirmed:
        parser.error('须先核对官方界面为演练模式，禁止使用正式局')
    robot_id = os.environ.get('CUMCM_ROBOT_ID')
    if not robot_id:
        parser.error('缺少本机队号环境变量')
    root = Path(__file__).parent
    out = root / 'results' / time.strftime(f'full-p{args.problem}-%Y%m%d-%H%M%S')
    out.mkdir(parents=True, exist_ok=False)
    client = RobotClient(robot_id, port=args.port)
    cleared = set()
    error = None
    completed_scan = False
    checkpoint_at = 0
    started = time.perf_counter()

    def action(path, point=None, channel=None):
        nonlocal checkpoint_at
        if path != '/enter' and client.deadline - client.clock() < 10:
            raise ProbeError('不足 10 秒，停止当前基线')
        result = client.action(path, point, channel)
        if len(client.records) - checkpoint_at >= 200:
            checkpoint_at = len(client.records)
            (out / 'progress.json').write_text(json.dumps({
                'requests': checkpoint_at, 'cleared': len(cleared),
                'wall_s': time.perf_counter()-started,
                'virtual_s': client.virtual_time}), encoding='utf-8')
        return result

    try:
        action('/enter')
        for point in scan_points():
            for channel in range(1, 21):
                if channel in cleared:
                    continue
                observation = action('/measure', point, channel)
                kind = observation['measure_result']
                if kind == 'no_signal':
                    continue
                candidates = [point] if kind == 'near' else clear_candidates(point, observation['svd_deg'])
                for candidate in candidates:
                    if action('/clear', candidate, channel)['clear_result'] == 'success':
                        cleared.add(channel)
                        break
                else:
                    raise ProbeError('保守条带未能清除已发现源，需核对规则或几何')
                if len(cleared) == 16:
                    break
            if len(cleared) == 16:
                break
        else:
            completed_scan = True
        action('/exit')
    except Exception as exc:
        error = f'{type(exc).__name__}: {exc}'
        # 仅在协议仍明确有效时主动结束当前演练，避免留悬挂会话。
        if client.entered and not client.failed and not client.exited:
            try:
                client.action('/exit')
            except Exception:
                pass
    elapsed = time.perf_counter() - started
    times = [r['elapsed_s'] for r in client.records]
    ordered = sorted(times)
    summary = {
        'scope': 'official_practice_conservative_full_round_not_optimized',
        'problem': args.problem, 'case_code': args.case,
        'wall_s': elapsed, 'virtual_time_s': client.virtual_time,
        'cleared_count': len(cleared), 'completed_scan': completed_scan,
        'termination': 'count_upper_bound' if len(cleared)==16 else 'grid_scan' if completed_scan else 'error',
        'official_true_count': None, 'official_all_cleared': None,
        'requests': len(client.records),
        'measure_requests': sum(r['path']=='/measure' for r in client.records),
        'clear_requests': sum(r['path']=='/clear' for r in client.records),
        'retry_count': sum(r['attempts']-1 for r in client.records),
        'mean_request_s': statistics.mean(times) if times else None,
        'median_request_s': statistics.median(times) if times else None,
        'p95_request_s': ordered[min(len(ordered)-1,int(0.95*len(ordered)))] if ordered else None,
        'http_total_s': sum(times), 'exited': client.exited, 'error': error,
        'source_sha256': {p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in (Path(__file__),root/'client.py')},
        'ui_truth_check_pending': True}
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'actions.json').write_text(json.dumps(client.records,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    if error:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
