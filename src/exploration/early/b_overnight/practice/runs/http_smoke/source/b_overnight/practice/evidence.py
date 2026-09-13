"""实际演练 UI 的人工核验收据；HTTP 本身不能证明演练/正式模式。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time


def validate_receipt(path, problem, port, now=None):
    path = Path(path).resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    required = {"observed_at_utc", "problem", "case_code", "mode_visible_text", "window_title",
                "screenshot_path", "screenshot_sha256", "review_note", "port"}
    if set(data) != required or data["mode_visible_text"] != "演练测试" or data["problem"] != problem or data["port"] != port:
        raise ValueError("收据必须精确对应当前问题、端口与官方演练测试界面")
    if not isinstance(problem, int) or isinstance(problem, bool) or problem not in (3, 4):
        raise ValueError("只支持问题3/4演练")
    for key in ("case_code", "window_title", "review_note"):
        if not isinstance(data[key], str) or not data[key].strip() or len(data[key]) > 500:
            raise ValueError("缺少当前案例、实际窗口标题或人工核验说明")
    observed = datetime.fromisoformat(data["observed_at_utc"].replace("Z", "+00:00"))
    if observed.tzinfo is None:
        raise ValueError("核验时间必须带时区")
    age = (time.time() if now is None else now) - observed.timestamp()
    if not 0 <= age <= 120:
        raise ValueError("界面核验超过120秒或时间在未来；请重新实际查看当前官方界面")
    image_path = Path(data["screenshot_path"])
    if not image_path.is_absolute() or not image_path.is_file():
        raise ValueError("必须提供本次实际界面截图的绝对路径")
    raw = image_path.read_bytes()
    if len(raw) < 100 or not (raw.startswith(b"\x89PNG\r\n\x1a\n") or raw.startswith(b"\xff\xd8\xff")):
        raise ValueError("截图必须是实际PNG/JPEG文件")
    if hashlib.sha256(raw).hexdigest() != data["screenshot_sha256"]:
        raise ValueError("截图散列不匹配")
    if path.with_suffix(path.suffix + ".consumed").exists():
        raise ValueError("该核验收据已使用；不得自动重新进入")
    return data


class ReviewedPracticeAuthorization:
    scope = "official_practice"
    def __init__(self, receipt_path, problem, port, reviewed_phrase):
        self.receipt_path = Path(receipt_path).resolve()
        self.problem, self.port, self.reviewed_phrase = problem, port, reviewed_phrase

    def authorize(self, port, problem):
        if (port, problem) != (self.port, self.problem):
            raise ValueError("授权与本次连接不匹配")
        data = validate_receipt(self.receipt_path, problem, port)
        expected = f"当前是演练测试 问题{problem} 案例{data['case_code']}"
        if self.reviewed_phrase != expected:
            raise ValueError("没有逐字确认本次实际演练界面")
        # 在 /enter 前原子消费一次；网络结果不明时也不自动重新进入。
        with self.receipt_path.with_suffix(self.receipt_path.suffix + ".consumed").open("x", encoding="utf-8") as stream:
            json.dump({"consumed_at": datetime.now(timezone.utc).isoformat(), "problem": problem,
                       "case_code": data["case_code"], "screenshot_sha256": data["screenshot_sha256"]}, stream, ensure_ascii=False)


def review_current_practice_ui(receipt_path, problem, port):
    data = validate_receipt(receipt_path, problem, port)
    if not sys.stdin.isatty():
        raise ValueError("live入口要求人工交互终端；不能通过管道或布尔参数替代当前UI核验")
    expected = f"当前是演练测试 问题{problem} 案例{data['case_code']}"
    print("请亲眼复核当前官方窗口和收据截图：模式必须为“演练测试”，问题与案例编码一致。")
    print(f"逐字输入：{expected}")
    phrase = input().strip()
    if phrase != expected:
        raise ValueError("本次界面核验未通过，没有连接或进入官方接口")
    return ReviewedPracticeAuthorization(receipt_path, problem, port, phrase)
