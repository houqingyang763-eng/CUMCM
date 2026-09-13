"""用人工响应夹具检查客户端边界，不模拟官方性能或目标环境。"""
import json
import unittest
from client import RobotClient, ProbeError


def accepted(virtual=0, **fields):
    return 200, dict(accepted=True, virtual_time_s=virtual, **fields)


class Fixture:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, path, body, timeout):
        self.calls.append((path, body, timeout))
        result = self.replies.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class ClientTests(unittest.TestCase):
    def client(self, replies, **kwargs):
        fixture = Fixture([accepted(remaining_real_duration_s=1200)] + replies)
        client = RobotClient('TEST_ONLY', transport=fixture, sleep=lambda _: None, **kwargs)
        client.action('/enter')
        return client, fixture

    def test_retry_uses_identical_request(self):
        client, fixture = self.client([TimeoutError(), accepted(5, measure_result='no_signal')])
        client.action('/measure', (0, 0), 1)
        self.assertEqual(fixture.calls[-1][1], fixture.calls[-2][1])
        self.assertEqual(client.virtual_time, 5)

    def test_rejected_response_does_not_zero_clock(self):
        client, _ = self.client([accepted(5, measure_result='near'),
                                (200, {'accepted': False, 'virtual_time_s': 0})])
        client.action('/measure', (0, 0), 1)
        with self.assertRaises(ProbeError):
            client.action('/clear', (0, 0), 1)
        self.assertEqual(client.virtual_time, 5)

    def test_non_200_stops_even_if_accepted(self):
        client, _ = self.client([(500, {'accepted': True, 'virtual_time_s': 999})])
        with self.assertRaises(ProbeError):
            client.action('/measure', (0, 0), 1)
        self.assertEqual(client.virtual_time, 0)

    def test_near_and_no_signal_need_no_angle(self):
        client, _ = self.client([accepted(5, measure_result='near'), accepted(11, measure_result='no_signal')])
        client.action('/measure', (0, 0), 1)
        client.action('/measure', (0, 0), 2)
        self.assertEqual(client.virtual_time, 11)

    def test_timeout_exhaustion_latches_stop(self):
        client, fixture = self.client([TimeoutError(), TimeoutError(), TimeoutError()])
        with self.assertRaises(TimeoutError):
            client.action('/measure', (0, 0), 1)
        count = len(fixture.calls)
        with self.assertRaises(ProbeError):
            client.action('/exit')
        self.assertEqual(len(fixture.calls), count)

    def test_deadline_uses_returned_remaining(self):
        now = [100.0]
        fixture = Fixture([accepted(remaining_real_duration_s=3)])
        client = RobotClient('TEST_ONLY', transport=fixture, clock=lambda: now[0])
        client.action('/enter')
        self.assertEqual(client.deadline, 103)
        now[0] = 104
        with self.assertRaises(ProbeError):
            client.action('/measure', (0, 0), 1)
        self.assertEqual(len(fixture.calls), 1)

    def test_fractional_time_and_four_action_cycle(self):
        client, fixture = self.client([accepted(5.25, measure_result='direction', svd_deg=359.99),
                                      accepted(10.25, clear_result='success'), accepted(10.25, exit_reason='user_exit')])
        client.action('/measure', (1.25, 0), 1)
        client.action('/clear', (1.25, 0), 1)
        client.action('/exit')
        self.assertEqual(client.virtual_time, 10.25)
        ids = [json.loads(call[1])['request_id'] for call in fixture.calls]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertNotIn('TEST_ONLY', json.dumps(client.records))

    def test_invalid_coordinate_rejected_before_transport(self):
        client, fixture = self.client([])
        with self.assertRaises(ValueError):
            client.action('/measure', (float('nan'), 0), 1)
        self.assertEqual(len(fixture.calls), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
