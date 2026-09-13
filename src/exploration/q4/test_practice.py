"""Q4演练适配器检查：所有HTTP连接均为本进程随机端口的假服务。"""
from datetime import datetime, timedelta, timezone
import hashlib
import http.server
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest

import common
from practice import (PracticeClient, ProbeError, ReviewedPracticeAuthorization,
                      policy_and_state, public_response, run_session, validate_receipt)
from simulation import LocalEnvironment, Scenario, Source
from state import audit_state


class MockService:
    """本进程拥有的假服务；不占用2026，不启动任何官方模拟器。"""
    def __init__(self, scene, remaining_real=1200, max_virtual=360000,
                 drop_path=None, corrupt_cost=False, robot_id="MOCK_ONLY"):
        self.environment = LocalEnvironment(scene)
        self.remaining_real, self.max_virtual = remaining_real, max_virtual
        self.drop_path, self.corrupt_cost, self.robot_id = drop_path, corrupt_cost, robot_id
        self.entered = self.exited = False
        self.calls = []
        self.thread = None
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                code, response, drop = owner.handle(self.path, data)
                if drop:
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                raw = json.dumps(response, allow_nan=False).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        if self.port == 2026:
            self.server.server_close()
            raise RuntimeError("假服务禁止使用真实默认端口")

    def handle(self, path, data):
        self.calls.append(dict(path=path, request_id=data.get("request_id")))
        response = dict(accepted=False, real_timestamp_ms=1, virtual_time_s=0)
        if data.get("robot_id") != self.robot_id or data.get("arena_id") != "default":
            return 200, response, False
        if path == "/enter" and not self.entered:
            self.entered = True
            response.update(accepted=True, remaining_real_duration_s=self.remaining_real,
                            max_real_duration_s=1200, max_virtual_duration_s=self.max_virtual)
        elif path == "/exit" and self.entered and not self.exited:
            self.exited = True
            response.update(accepted=True, virtual_time_s=self.environment.virtual_time_s, exit_reason="user_exit")
        elif path in ("/measure", "/clear") and self.entered and not self.exited:
            q = data["position"]
            action = dict(kind=path[1:], position=(q["x"], q["y"]), channel=data["channel"])
            response = {key: value for key, value in self.environment.act(action).items() if key != "costs"}
            response["real_timestamp_ms"] = 1
            if self.corrupt_cost:
                response["virtual_time_s"] += 10
        response["robot_id"] = "SENSITIVE_RESPONSE_TEXT"
        return 200, response, path == self.drop_path

    def __enter__(self):
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .02}, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


class MockAuthorization:
    scope = "self_built_http_mock"
    def __init__(self, service):
        self.service = service
        self.used = False

    def authorize(self, port, problem):
        if self.used or problem != 4 or port != self.service.port or not self.service.thread.is_alive():
            raise ValueError("只能授权当前进程自己的本次Q4假服务")
        self.used = True


def unit_receipt(port=23456):
    # 纯结构测试夹具，绝不是官方UI证据，不连接真实服务。
    return dict(schema_version=1, observed_at_utc=datetime.now(timezone.utc).isoformat(),
        problem=4, port=port, mode_visible_text="演练测试", window_title="UNIT_FIXTURE_ONLY",
        case_code="UNIT_ONLY", review_note="格式夹具，不是实际UI核验",
        evidence=dict(kind="codex_tool_snapshot", reference="unit_fixture:never_an_official_observation"))


class PracticeTests(unittest.TestCase):
    def test_documented_http_cost_199_and_clear_keeps_channel(self):
        with MockService(Scenario("unit", 0, "unit", "zero", ())) as service:
            client = PracticeClient("MOCK_ONLY", port=service.port)
            client.action("/enter")
            client.action("/measure", (300, 400), 1)
            client.action("/measure", (300, 400), 2)
            client.action("/clear", (300, 0), 3)
            client.action("/measure", (300, 0), 2)
            client.action("/exit")
            self.assertEqual(client.virtual_time, 199)
            self.assertEqual(sum(client.ledger.values()), 199)
            self.assertEqual(client.measure_channel, 2)
            self.assertEqual(client.ledger["switch_s"], 1)
            self.assertEqual(client.ledger["failed_clear_s"], 3)
            self.assertTrue(client.exited)
            self.assertEqual(client.retries, 0)

    def test_accepted_then_dropped_request_is_not_retried(self):
        with MockService(Scenario("unit", 0, "unit", "zero", ()), drop_path="/measure") as service:
            client = PracticeClient("MOCK_ONLY", port=service.port)
            client.action("/enter")
            with self.assertRaises(Exception):
                client.action("/measure", (0, 0), 1)
            self.assertTrue(client.failed)
            self.assertEqual(service.environment.virtual_time_s, 5)
            self.assertEqual([r["path"] for r in service.calls], ["/enter", "/measure"])
            with self.assertRaises(ProbeError):
                client.action("/exit")
            self.assertEqual(len(service.calls), 2)

    def test_protocol_cost_error_stops_without_exit(self):
        with tempfile.TemporaryDirectory() as folder, MockService(Scenario("unit", 0, "unit", "zero", ()), corrupt_cost=True) as service:
            policy, state = policy_and_state()
            client = PracticeClient("MOCK_ONLY", port=service.port)
            result = run_session(client, policy, state, MockAuthorization(service), Path(folder) / "run")
            self.assertEqual(result["validation_issue"], "cost_mismatch")
            self.assertTrue(result["protocol_stopped"])
            self.assertFalse(result["exited"])
            self.assertEqual([r["path"] for r in service.calls], ["/enter", "/measure"])
            self.assertIsNotNone(result["uncertain_request"])

    def test_real_and_virtual_reserve_exit_without_action(self):
        for settings, expected in ((dict(remaining_real=1), "real_time_reserve"),
                                   (dict(max_virtual=5), "virtual_time_reserve")):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as folder, \
                 MockService(Scenario("unit", 0, "unit", "zero", ()), **settings) as service:
                policy, state = policy_and_state()
                result = run_session(PracticeClient("MOCK_ONLY", port=service.port), policy, state,
                                     MockAuthorization(service), Path(folder) / "run")
                self.assertEqual(result["stop_reason"], expected)
                self.assertTrue(result["exited"])
                self.assertEqual(result["actions"], 0)
                self.assertEqual([r["path"] for r in service.calls], ["/enter", "/exit"])

    def test_formal_wrong_question_stale_or_unreferenced_ui_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "receipt.json"
            mutations = [dict(mode_visible_text="正式测试"), dict(problem=3),
                dict(observed_at_utc=(datetime.now(timezone.utc) - timedelta(seconds=121)).isoformat()),
                dict(observed_at_utc=(datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()),
                dict(evidence={"kind": "confirmation", "confirmed": True}),
                dict(evidence={"kind": "codex_tool_snapshot", "reference": ""})]
            for mutation in mutations:
                with self.subTest(mutation=mutation):
                    path.write_text(json.dumps(dict(unit_receipt(), **mutation)), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        validate_receipt(path, 23456)

    def test_receipt_single_use_and_copy_reuse_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            first, second = folder / "first.json", folder / "copy.json"
            raw = json.dumps(unit_receipt())
            first.write_text(raw, encoding="utf-8")
            second.write_text(raw, encoding="utf-8")
            auth = ReviewedPracticeAuthorization(first, 23456, registry=folder / "uses")
            auth.authorize(23456, 4)
            with self.assertRaises(ValueError):
                auth.authorize(23456, 4)
            with self.assertRaises(FileExistsError):
                ReviewedPracticeAuthorization(second, 23456, registry=folder / "uses").authorize(23456, 4)

    def test_screenshot_hash_and_ui_time_checked_again_at_consume(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            image = folder / "fixture.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(128))
            data = unit_receipt()
            data["evidence"] = dict(kind="screenshot", path=str(image), sha256=hashlib.sha256(image.read_bytes()).hexdigest())
            path = folder / "receipt.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            validate_receipt(path, 23456)
            image.write_bytes(image.read_bytes() + b"changed")
            with self.assertRaises(ValueError):
                ReviewedPracticeAuthorization(path, 23456, registry=folder / "uses").authorize(23456, 4)

    def test_sensitive_response_never_written(self):
        with tempfile.TemporaryDirectory() as folder, MockService(Scenario("unit", 0, "unit", "zero", ()), remaining_real=1,
                                                                  robot_id="SECRET_TEST_TEAM") as service:
            policy, state = policy_and_state()
            result = run_session(PracticeClient("SECRET_TEST_TEAM", port=service.port), policy, state,
                                 MockAuthorization(service), Path(folder) / "run")
            text = "\n".join(path.read_text(encoding="utf-8") for path in (Path(folder) / "run").glob("*.json*"))
            self.assertNotIn("SECRET_TEST_TEAM", text)
            self.assertNotIn("SENSITIVE_RESPONSE_TEXT", text)
            self.assertNotIn("robot_id", text)
            self.assertEqual(result["official_true_count"], None)

    def test_full_candidate_http_session_with_true_state_audit(self):
        sources = tuple(Source(j, (1., 0.), 1500., None if j % 2 else 180.) for j in range(1, 11))
        scene = Scenario("q4_mock_near10", 944499, "unit_cluster", "zero", sources)
        with tempfile.TemporaryDirectory() as folder, MockService(scene) as service:
            policy, state = policy_and_state()
            client = PracticeClient("MOCK_ONLY", port=service.port)
            result = run_session(client, policy, state, MockAuthorization(service), Path(folder) / "run",
                                 audit_hook=lambda s: audit_state(s, service.environment))
            self.assertTrue(result["complete_by_public_evidence"], result)
            self.assertEqual(result["cleared_count"], 10)
            self.assertEqual(len(service.environment.cleared), 10)
            self.assertAlmostEqual(result["virtual_time_s"], result["independently_accounted_s"], places=5)
            self.assertAlmostEqual(result["average_localization_clear_s"], result["virtual_time_s"] / 10)
            self.assertTrue(result["exited"])
            self.assertFalse(result["ui_result_check_pending"])
            self.assertEqual(len(service.calls), result["actions"] + 2)
            self.assertEqual(result["source_changed"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
