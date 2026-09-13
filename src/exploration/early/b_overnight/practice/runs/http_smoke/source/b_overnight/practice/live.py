"""仅供人工核对当前官方演练界面后的单局入口；本轮不会运行此脚本。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from adapter import NIGHT, PracticeClient, dump, run_session, strategy
from evidence import review_current_practice_ui
from astra_guard import check_cached


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--problem", type=int, choices=(3, 4), required=True)
    parser.add_argument("--strategy", choices=("completion", "configured", "directional"), required=True)
    parser.add_argument("--ui-receipt", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--port", type=int, default=2026)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    check_cached()
    if not 1 <= args.port <= 65535:
        parser.error("端口范围不合法")
    robot_id = os.environ.get("CUMCM_ROBOT_ID")
    if not robot_id:
        parser.error("缺少当前登录队号环境变量；不得把队号写进命令参数或日志")
    overrides = json.loads(args.config.read_text(encoding="utf-8")) if args.config else None
    policy, state = strategy(args.problem, args.strategy, overrides)
    authorization = review_current_practice_ui(args.ui_receipt, args.problem, args.port)
    client = PracticeClient(robot_id, port=args.port, timeout=5, retries=2)
    result = run_session(client, policy, state, args.problem, authorization, args.output)
    files = [Path(__file__), Path(__file__).with_name("adapter.py"), Path(__file__).with_name("evidence.py"),
             NIGHT / "task_cost.py", NIGHT / "q4.py", NIGHT.parent / "b_env_probe" / "client.py"]
    manifest = {"created_at": time.time(), "strategy": args.strategy, "problem": args.problem,
                "source_sha256": {str(path.relative_to(NIGHT.parent)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files},
                "config_sha256": hashlib.sha256((args.output / "config.json").read_bytes()).hexdigest(),
                "official_ui_verification": "manual_current_screenshot_and_interactive_case_confirmation",
                "official_result_still_requires_ui_review": True}
    dump(args.output / "manifest.json", manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["error_type"] or not result["complete_by_evidence"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
