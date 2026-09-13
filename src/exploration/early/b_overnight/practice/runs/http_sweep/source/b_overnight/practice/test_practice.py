"""公开协议、幂等与停止边界检查；全部连接本进程随机端口或响应夹具。"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from adapter import PracticeClient, ProbeError, public_response, run_session, strategy
from evidence import load_verified_practice_ui, validate_receipt
from mock_service import MockAuthorization, MockService
from simulation import Scenario


def reply(virtual=0, **extra):
    return 200, dict(accepted=True, real_timestamp_ms=1, virtual_time_s=virtual, **extra)


class PracticeChecks(unittest.TestCase):
    def test_http_documented_199_seconds_clear_keeps_channel(self):
        scene = Scenario("empty", 1, "unit", "zero", ())
        with MockService(scene) as service:
            client = PracticeClient("MOCK_ONLY", port=service.port)
            client.action("/enter")
            client.action("/measure", (300, 400), 1)
            client.action("/measure", (300, 400), 2)
            client.action("/clear", (300, 0), 3)
            client.action("/measure", (300, 0), 2)
            client.action("/exit")
            self.assertEqual(client.virtual_time, 199)
            self.assertEqual(client.measure_channel, 2)
            self.assertEqual(sum(client.ledger.values()), 199)
            self.assertTrue(client.exited)

    def test_drop_after_accept_reuses_same_bytes_without_double_cost(self):
        with MockService(Scenario("empty", 1, "unit", "zero", ()), drop_once_path="/measure") as service:
            client = PracticeClient("MOCK_ONLY", port=service.port, sleep=lambda _: None)
            client.action("/enter")
            client.action("/measure", (0, 0), 1)
            self.assertEqual(client.virtual_time, 5)
            self.assertEqual(service.environment.virtual_time_s, 5)
            self.assertEqual(service.calls[-1], service.calls[-2])
            self.assertEqual(client.records[-1]["attempts"], 2)
            client.action("/exit")

    def test_changed_payload_same_id_is_conflict(self):
        with MockService(Scenario("empty", 1, "unit", "zero", ())) as service:
            data = {"arena_id": "default", "robot_id": "MOCK_ONLY", "request_id": "same"}
            self.assertEqual(service.handle("/enter", json.dumps(data).encode())[0], 200)
            self.assertEqual(service.handle("/exit", json.dumps(data).encode())[0], 409)

    def test_transport_uncertainty_latches_and_no_exit_new_request(self):
        responses = [reply(remaining_real_duration_s=1200, max_real_duration_s=1200, max_virtual_duration_s=360000), TimeoutError(), TimeoutError(), TimeoutError()]
        calls = []
        def transport(path, body, timeout):
            calls.append(path)
            result = responses.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        client = PracticeClient("MOCK_ONLY", transport=transport, sleep=lambda _: None)
        client.action("/enter")
        with self.assertRaises(TimeoutError):
            client.action("/measure", (0, 0), 1)
        self.assertTrue(client.failed)
        with self.assertRaises(ProbeError):
            client.action("/exit")
        self.assertEqual(calls, ["/enter", "/measure", "/measure", "/measure"])

    def test_real_time_reserve_exits_without_measurement(self):
        with tempfile.TemporaryDirectory() as temp, MockService(Scenario("empty", 1, "unit", "zero", ()), remaining_real=1) as service:
            policy, state = strategy(3, "completion")
            result = run_session(PracticeClient("MOCK_ONLY", port=service.port), policy, state, 3,
                                 MockAuthorization(service, 3), Path(temp) / "run", guard=lambda: None)
            self.assertEqual(result["stop_reason"], "real_time_reserve")
            self.assertTrue(result["exited"])
            self.assertEqual(result["actions"], 0)

    def test_virtual_limit_reserve_exits_before_costly_action(self):
        with tempfile.TemporaryDirectory() as temp, MockService(Scenario("empty", 1, "unit", "zero", ()), max_virtual=5) as service:
            policy, state = strategy(3, "completion")
            result = run_session(PracticeClient("MOCK_ONLY", port=service.port), policy, state, 3,
                                 MockAuthorization(service, 3), Path(temp) / "run", guard=lambda: None)
            self.assertEqual(result["stop_reason"], "virtual_time_reserve")
            self.assertTrue(result["exited"])
            self.assertEqual(result["actions"], 0)

    def test_bad_cost_response_stops(self):
        replies = [reply(remaining_real_duration_s=1200, max_real_duration_s=1200, max_virtual_duration_s=360000), reply(99, measure_result="no_signal")]
        client = PracticeClient("MOCK_ONLY", transport=lambda *args: replies.pop(0))
        client.action("/enter")
        with self.assertRaises(ProbeError):
            client.action("/measure", (0, 0), 1)
        self.assertTrue(client.failed)

    def test_ui_receipt_rejects_formal_stale_and_missing_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "receipt.json"
            path.write_text(json.dumps({"practice_confirmed": True}), encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_receipt(path, 3, 2026)
            data = dict(observed_at_utc=(datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat(),
                        problem=3, case_code="UNIT_ONLY", mode_visible_text="正式测试", window_title="unit fixture",
                        screenshot_path=str(Path(temp) / "missing.png"), screenshot_sha256="x", review_note="unit fixture", port=2026)
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_receipt(path, 3, 2026)
            data["mode_visible_text"] = "演练测试"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_receipt(path, 3, 2026)

    def test_strategy_problem_and_config_are_explicit(self):
        with self.assertRaises(ValueError):
            strategy(4, "completion")
        with self.assertRaises(ValueError):
            strategy(3, "configured")
        with self.assertRaises(ValueError):
            strategy(3, "configured", {"current_probe_ratio": float("nan")})
        with self.assertRaises(ValueError):
            strategy(3, "joint25")

    def test_defaults_match_frozen_completion_and_joint25_factories(self):
        from task_cost import CompletionCostPolicy
        from state import InformationState
        from q4_compare import factories
        policy3, state3 = strategy(3)
        self.assertIs(type(policy3), CompletionCostPolicy)
        self.assertIs(type(state3), InformationState)
        policy4, state4 = strategy(4)
        factory_policy, factory_state, config = factories("joint25")
        self.assertIs(type(policy4), factory_policy)
        self.assertIs(type(state4), factory_state)
        self.assertEqual(policy4.config, config)
        self.assertEqual(len(policy4.search_anchors), 25)

    def test_joint25_negative_keeps_directional_nearby_positions_possible(self):
        _, state = strategy(4, "joint25")
        c = state.channels[1]
        initial_mask = c.sample_mask
        state.update(dict(kind="measure", position=(0.0, 0.0), channel=1),
                     dict(accepted=True, measure_result="no_signal", virtual_time_s=5.0))
        self.assertEqual(c.status, "unknown")
        self.assertEqual(c.exclusions, [])
        self.assertEqual(c.sample_mask, initial_mask)
        self.assertTrue(c.compatible((100.0, 100.0)))

    def test_explicit_sweep_factory_and_problem_boundary(self):
        from sweep_policy import Q3SweepPolicy
        from state import InformationState
        policy, state = strategy(3, "sweep")
        self.assertIs(type(policy), Q3SweepPolicy)
        self.assertIs(type(state), InformationState)
        with self.assertRaises(ValueError):
            strategy(4, "sweep")

    def test_receipt_single_use_and_screenshot_hash_are_enforced(self):
        # 纯收据格式夹具，不宣称该字节是实际官方UI；不创建HTTP连接。
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / "unit_fixture.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(200))
            path = Path(temp) / "receipt.json"
            data = dict(observed_at_utc=datetime.now(timezone.utc).isoformat(), problem=3, case_code="UNIT_ONLY",
                        mode_visible_text="演练测试", window_title="unit fixture only", screenshot_path=str(image),
                        screenshot_sha256=hashlib.sha256(image.read_bytes()).hexdigest(), review_note="unit fixture only", port=2026)
            path.write_text(json.dumps(data), encoding="utf-8")
            authorization = load_verified_practice_ui(path, 3, 2026)
            authorization.authorize(2026, 3)
            with self.assertRaises(ValueError):
                authorization.authorize(2026, 3)
            second = Path(temp) / "bad_hash.json"
            data["screenshot_sha256"] = "wrong"
            second.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_receipt(second, 3, 2026)

    def test_invalid_response_text_is_not_persisted(self):
        clean = public_response({"accepted": True, "robot_id": "SENSITIVE_TEST", "measure_result": "SENSITIVE_TEST", "virtual_time_s": "SENSITIVE_TEST"})
        self.assertNotIn("SENSITIVE_TEST", json.dumps(clean))


if __name__ == "__main__":
    unittest.main(verbosity=2)
