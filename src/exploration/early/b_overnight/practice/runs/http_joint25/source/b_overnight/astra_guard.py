"""当前 B 题的协作式额度保护；一分钟采样，不是强制中断或硬额度。"""
import argparse
import json
import math
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOCAL = ROOT / "guard_local"


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


class AppBridge:
    def __init__(self, config):
        env = dict(os.environ, CODEX_APP_TOOLS_PIPE_PATH=config["pipe"])
        self.proc = subprocess.Popen([config["node"], config["mcp_server"]],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", env=env, creationflags=subprocess.CREATE_NO_WINDOW)
        self.seq = 0
        self.thread_id = config["thread_id"]
        self.responses = queue.Queue()
        def receive():
            for line in self.proc.stdout:
                try:
                    self.responses.put(json.loads(line))
                except ValueError:
                    pass
            self.responses.put({"error": "bridge exited"})
        threading.Thread(target=receive, daemon=True).start()
        self.rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "cumcm-b-astra-guard", "version": "1"}})
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def send(self, value):
        self.proc.stdin.write(json.dumps(value) + "\n")
        self.proc.stdin.flush()

    def rpc(self, method, params):
        self.seq += 1
        self.send({"jsonrpc": "2.0", "id": self.seq, "method": method, "params": params})
        deadline = time.monotonic() + 40
        while True:
            response = self.responses.get(timeout=max(.01, deadline-time.monotonic()))
            if response.get("id") != self.seq:
                if "error" in response and "id" not in response:
                    raise RuntimeError(response["error"])
                continue
            if "error" in response:
                raise RuntimeError(response["error"])
            return response["result"]

    def call(self, name, arguments):
        response = self.rpc("tools/call", {"name": name, "arguments": arguments,
                                         "_meta": {"threadId": self.thread_id}})
        if response.get("isError"):
            raise RuntimeError(str(response)[:500])
        for item in response.get("content", []):
            if item.get("type") == "text":
                try:
                    return json.loads(item["text"])
                except ValueError:
                    continue
        raise ValueError("No structured tool response")

    def close(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.proc.stdin.close()
        self.proc.stdout.close()


def quota_payload(payload):
    bucket = (payload.get("rateLimitsByLimitId") or {}).get("codex")
    if not bucket:
        bucket = payload.get("rateLimits") or {}
        if bucket.get("limitId") not in (None, "codex"):
            raise ValueError("Missing codex bucket")
    windows = []
    for key in ("primary", "secondary"):
        w = bucket.get(key)
        if not w:
            continue
        used = w.get("usedPercent")
        if isinstance(used, bool) or not isinstance(used, (int, float)) or not math.isfinite(used):
            raise ValueError("Missing or invalid quota")
        windows.append({"window_minutes": w["windowDurationMins"],
                        "remaining_percent": max(0, min(100, 100-used)), "resets_at": w.get("resetsAt")})
    if not windows or not any(w["window_minutes"] == 10080 for w in windows):
        raise ValueError("Weekly quota unavailable")
    return {"checked_at": time.time(), "remaining_percent": min(w["remaining_percent"] for w in windows),
            "bucket": "codex", "windows": windows}


def probe(config):
    bridge = AppBridge(config)
    try:
        return quota_payload(bridge.call("get_usage_limits", {}))
    finally:
        bridge.close()


def latch_stop(reason):
    LOCAL.mkdir(exist_ok=True)
    try:
        with (LOCAL / "STOP.json").open("x", encoding="utf-8") as stream:
            json.dump({"at": time.time(), "reason": reason, "latched": True}, stream, ensure_ascii=False)
    except FileExistsError:
        pass


def check_cached():
    if (LOCAL / "STOP.json").exists():
        raise RuntimeError("ASTRA_STOP: " + read(LOCAL / "STOP.json")["reason"])
    if not (LOCAL / "ACTIVE.json").exists():
        raise RuntimeError("保护未激活")
    q = read(LOCAL / "quota.json")
    if time.time() - q["checked_at"] > 150:
        raise RuntimeError("额度读数过期，停止新实验")
    if q["remaining_percent"] <= 10:
        latch_stop("剩余额度达到 10% 收尾门槛")
        raise RuntimeError("ASTRA_STOP")
    return q


def notify_stop(config):
    if (LOCAL / "notified.json").exists():
        return
    bridge = AppBridge(config)
    try:
        reason = read(LOCAL / "STOP.json")["reason"]
        message = (f"[用户授权的 Astra 额度保护] {reason}。本次夜间研究已进入收尾。"
                   f"先读取 {LOCAL / 'STOP.json'}；立即停止新研究与实验，通知所有子代理停止，"
                   f"仅整理现有成果、失败、代码和续接点至 {ROOT / 'ARCHIVE.md'}。"
                   "暂停本任务夜间研究自动续跑，写 guard_local/ARCHIVED.json 后结束。"
                   "不得自行解除停止或使用额度重置信用。")
        result = bridge.call("send_message_to_thread", {"threadId": config["thread_id"], "prompt": message})
        save(LOCAL / "notified.json", {"at": time.time(), "result": result})
    finally:
        bridge.close()


def daemon(config):
    import msvcrt
    lock = (LOCAL / "daemon.lock").open("a+b")
    lock.seek(0)
    lock.write(b"0")
    lock.flush()
    lock.seek(0)
    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    save(LOCAL / "daemon.json", {"pid": os.getpid(), "started_at": time.time()})
    while (LOCAL / "ACTIVE.json").exists() and not (LOCAL / "ARCHIVED.json").exists():
        if not (LOCAL / "STOP.json").exists():
            try:
                q = probe(config)
                save(LOCAL / "quota.json", q)
                if q["remaining_percent"] <= config["stop_remaining_percent"]:
                    latch_stop(f"codex 最少剩余额度 {q['remaining_percent']}%，达到 10% 门槛")
            except Exception as error:
                save(LOCAL / "error.json", {"at": time.time(), "error": str(error)[:500]})
                latch_stop("无法取得实时额度，保护性停止")
        save(LOCAL / "heartbeat.json", {"at": time.time(), "pid": os.getpid(),
             "mode": "STOP" if (LOCAL / "STOP.json").exists() else "ON"})
        if (LOCAL / "STOP.json").exists():
            try:
                notify_stop(config)
            except Exception as error:
                save(LOCAL / "notification_error.json", {"at": time.time(), "error": str(error)[:500]})
        time.sleep(config["interval_seconds"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["setup", "activate", "daemon", "check", "status"])
    parser.add_argument("--node")
    parser.add_argument("--server")
    args = parser.parse_args()
    LOCAL.mkdir(exist_ok=True)
    if args.command == "setup":
        if (LOCAL / "ACTIVE.json").exists() or (LOCAL / "STOP.json").exists():
            raise RuntimeError("已有保护状态，不覆盖")
        config = {"pipe": os.environ["CODEX_APP_TOOLS_PIPE_PATH"],
                  "thread_id": os.environ["CODEX_THREAD_ID"], "node": args.node,
                  "mcp_server": args.server, "interval_seconds": 60, "stop_remaining_percent": 10}
        save(LOCAL / "config.json", config)
        q = probe(config)
        save(LOCAL / "quota.json", q)
        print(json.dumps(q))
        return
    if args.command == "check":
        print(json.dumps(check_cached()))
        return
    if args.command == "status":
        print(json.dumps({p.stem: read(p) for p in LOCAL.glob("*.json") if p.name != "config.json"}))
        return
    config = read(LOCAL / "config.json")
    if args.command == "activate":
        if (LOCAL / "STOP.json").exists():
            raise RuntimeError("STOP 已锁存，不可自动解除")
        if (LOCAL / "ACTIVE.json").exists():
            raise RuntimeError("已经激活")
        q = probe(config)
        save(LOCAL / "quota.json", q)
        if q["remaining_percent"] <= 10:
            latch_stop("激活时额度已达 10% 门槛")
            raise RuntimeError("只允许收尾")
        save(LOCAL / "ACTIVE.json", {"at": time.time(), "threshold": 10,
             "authorization": "2026-09-11 用户明确启动 Astra 检测保护"})
        proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "daemon"],
             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
             creationflags=subprocess.CREATE_NO_WINDOW, cwd=ROOT)
        print(json.dumps({"started_pid": proc.pid, "threshold": 10, "remaining_percent": q["remaining_percent"]}))
    else:
        daemon(config)


if __name__ == "__main__":
    main()
