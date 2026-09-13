"""仅用于已由人确认的演练局：测量本地官方接口延迟，不执行搜索。"""
import argparse
import json
import os
from pathlib import Path
import statistics
import sys
import time
from client import RobotClient


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--practice-confirmed', action='store_true',
                        help='已在官方界面确认是演练局；接口自身不返回演练/正式模式')
    parser.add_argument('--port', type=int, default=2026)
    parser.add_argument('--count', type=int, default=40)
    args = parser.parse_args()
    if not args.practice_confirmed or not 1 <= args.count <= 100:
        parser.error('必须确认演练局，count 必须在 1—100 内')
    robot_id = os.environ.get('CUMCM_ROBOT_ID')
    if not robot_id:
        parser.error('请在本机设置 CUMCM_ROBOT_ID 为已登录参赛队号，不写入源码')
    out = Path(__file__).parent / 'results' / time.strftime('live-%Y%m%d-%H%M%S')
    out.mkdir(parents=True, exist_ok=False)
    client = RobotClient(robot_id, port=args.port)
    started = time.perf_counter()
    error = None
    try:
        client.action('/enter')
        for i in range(args.count):
            if client.deadline - client.clock() < 10:
                break
            client.action('/measure', (0, 0), i % 20 + 1)
        client.action('/exit')
    except Exception as exc:
        error = f'{type(exc).__name__}: {exc}'
    durations = [r['elapsed_s'] for r in client.records if r['path'] == '/measure']
    ordered = sorted(durations)
    summary = {'scope': 'official_interface_probe_only_not_full_robot_task',
               'wall_s': time.perf_counter() - started, 'measure_calls': len(durations),
               'median_measure_s': statistics.median(durations) if durations else None,
               'p95_measure_s': ordered[min(len(ordered)-1, int(0.95*len(ordered)))] if ordered else None,
               'virtual_time_s': client.virtual_time, 'exited': client.exited, 'error': error}
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    (out / 'actions.json').write_text(json.dumps(client.records, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if error:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
