"""测试专用公开协议假服务；仅绑定本进程的随机回环端口，绝不使用 2026。"""
import http.server
import json
import math
import socket
import threading
import time

from adapter import NIGHT
from simulation import LocalEnvironment


class MockAuthorization:
    scope = "self_built_http_mock"
    def __init__(self, service, problem):
        self.service = service
        self.problem = problem

    def authorize(self, port, problem):
        if self.service.thread is None or not self.service.thread.is_alive() or port != self.service.port or problem != self.problem:
            raise ValueError("假服务授权与当前进程/端口/问题不匹配")


class MockService:
    def __init__(self, scenario, remaining_real=1200, max_virtual=360000, drop_once_path=None):
        self.environment = LocalEnvironment(scenario)
        self.remaining_real = remaining_real
        self.max_virtual = max_virtual
        self.drop_once_path = drop_once_path
        self.dropped = False
        self.entered, self.exited = False, False
        self.cache = {}
        self.calls = []
        self.thread = None
        owner = self
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                status, result, drop = owner.handle(self.path, raw)
                if drop:
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                data = json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        if self.port == 2026:
            self.server.server_close()
            raise RuntimeError("假服务不得占用官方端口")

    def handle(self, path, body):
        base = {"accepted": False, "real_timestamp_ms": time.time() * 1000, "virtual_time_s": self.environment.virtual_time_s}
        try:
            data = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            return 400, base, False
        rid = data.get("request_id")
        self.calls.append({"path": path, "request_id": rid, "body_sha256": __import__("hashlib").sha256(body).hexdigest()})
        if rid in self.cache:
            old_path, old_body, old_status, old_result = self.cache[rid]
            return (old_status, old_result, False) if (path, body) == (old_path, old_body) else (409, base, False)
        allowed = {"arena_id", "robot_id", "request_id"}
        if path in ("/measure", "/clear"):
            allowed |= {"position", "channel"}
        if path not in ("/enter", "/measure", "/clear", "/exit"):
            return 404, base, False
        if set(data) != allowed or data.get("arena_id") != "default" or data.get("robot_id") != "MOCK_ONLY" or not isinstance(rid, str):
            return 200, base, False
        if path == "/enter":
            if self.entered:
                return 200, base, False
            self.entered = True
            result = dict(base, accepted=True, max_virtual_duration_s=self.max_virtual, max_real_duration_s=1200,
                          remaining_real_duration_s=self.remaining_real)
        elif not self.entered or self.exited:
            return 200, base, False
        elif path == "/exit":
            self.exited = True
            result = dict(base, accepted=True, exit_reason="user_exit")
        else:
            try:
                p = data["position"]
                if set(p) != {"x", "y"}:
                    return 200, base, False
                if not all(isinstance(p[k], (int, float)) and not isinstance(p[k], bool) and math.isfinite(p[k]) and abs(p[k]) <= 2000000 for k in ("x", "y")):
                    return 400, base, False
                response = self.environment.act({"kind": path[1:], "position": (p["x"], p["y"]), "channel": data["channel"]})
            except (ValueError, KeyError, TypeError):
                return 400, base, False
            result = {key: value for key, value in response.items() if key != "costs"}
            result["real_timestamp_ms"] = time.time() * 1000
        self.cache[rid] = (path, body, 200, result)
        drop = path == self.drop_once_path and not self.dropped
        self.dropped |= drop
        return 200, result, drop

    def __enter__(self):
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
