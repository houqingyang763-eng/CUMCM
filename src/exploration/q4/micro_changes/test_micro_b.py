"""B候选保护检查；既有C9公开反馈作阴性价值回归，不运行完整策略。"""
import copy
import json
import math
from pathlib import Path
import pickle
import random
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from micro_b import (FORMAL, PROJECT, MicroBPolicy, common,
                     hypothetical_channel, remaining_work)


def observed_state():
    state = common.Q4State()
    for j in (1, 2):
        state.update(dict(kind="measure", channel=j, position=(0., 0.)),
                     dict(accepted=True, virtual_time_s=5., measure_result="direction", svd_deg=0.))
    return state


class MicroBTests(unittest.TestCase):
    def test_work_units_and_certified_clear_boundary(self):
        self.assertEqual(remaining_work(20.), 5.)
        self.assertEqual(remaining_work(40.), 16.)
        self.assertGreater(remaining_work(40.001), remaining_work(40.))

    def test_primary_and_unknown_are_never_pruned(self):
        state, policy = observed_state(), MicroBPolicy()
        with patch.object(policy, "_keep_auxiliary", return_value=False) as gate:
            action = policy._station(state, (100., 100.), "test", priority=1, scan_unknown=True)
            self.assertEqual(action["channel"], 1)
            gate.assert_not_called()
            action = policy._station_action(state)
            self.assertEqual(action["channel"], 3)
            self.assertEqual(gate.call_count, 1)
            self.assertEqual(gate.call_args.args[1].channel, 2)

    def test_exact_net_value_gate_includes_current_switch_charge(self):
        state, policy = observed_state(), MicroBPolicy()
        state.measuring_channel = 1
        with patch.object(policy, "_auxiliary_value", return_value=dict(expected_gain_s=6., measure_switch_cost_s=6.)):
            self.assertFalse(policy._keep_auxiliary(state, state.channels[2], (100., 100.)))
        with patch.object(policy, "_auxiliary_value", return_value=dict(expected_gain_s=6.001, measure_switch_cost_s=6.)):
            self.assertTrue(policy._keep_auxiliary(state, state.channels[2], (100., 100.)))

    def test_empty_pool_retains_existing_measurement(self):
        state, policy = observed_state(), MicroBPolicy()
        with patch.object(policy, "_auxiliary_pool", side_effect=ValueError("test exhaustion")):
            action = policy._station(state, (100., 100.), "test", scan_unknown=False)
        self.assertEqual(action["kind"], "measure")
        self.assertFalse(policy.fallback_started)
        self.assertEqual(policy.metadata()["micro_b"]["estimation_fallbacks"], 1)

    def test_clearance_empty_auxiliary_queue_continues_to_primary(self):
        state, policy = observed_state(), MicroBPolicy()
        for c in state.channels.values():
            if c.status == "unknown":
                c.status = "absent"
        policy.initial_index = len(policy.config.initial_points)
        policy.after_clear_scan = True
        job = dict(kind="measure", position=(100., 100.), channel=1, scan_unknown=False)
        with patch.object(policy, "_keep_auxiliary", return_value=False), patch.object(policy, "_plan", return_value=[job]):
            action = policy.choose(state)
        self.assertEqual(action["channel"], 1)
        self.assertEqual(action["position"], (100., 100.))
        self.assertFalse(policy.fallback_started)

    def test_hypothetical_update_isolated_and_no_negative_disk_exclusion(self):
        state = observed_state()
        original = pickle.dumps(state)
        negative = hypothetical_channel(state, state.channels[1], (-100., 0.), "no_signal")
        self.assertEqual(pickle.dumps(state), original)
        self.assertEqual(negative.exclusions, state.channels[1].exclusions)
        self.assertEqual(negative.observations[-1], ((-100., 0.), "no_signal", None))
        self.assertIsNot(negative.measured, state.channels[1].measured)

    def test_conditional_estimate_deterministic_without_primary_pool_or_rng_changes(self):
        state, policy = observed_state(), MicroBPolicy()
        # 缓存本就由正式计划填充；检查本次估价不改物理状态和其余频道。
        state.channels[1].circle()
        state_before = pickle.dumps(state)
        rng_before = random.getstate()
        began = time.perf_counter()
        first = policy._auxiliary_value(state, state.channels[1], (100., 100.))
        elapsed = time.perf_counter() - began
        second = policy._auxiliary_value(state, state.channels[1], (100., 100.))
        self.assertEqual(first, second)
        self.assertEqual(pickle.dumps(state), state_before)
        self.assertEqual(random.getstate(), rng_before)
        self.assertEqual(policy.pools, {})
        self.assertEqual(policy.pool_stamps, {})
        self.assertEqual(first["pool_size"], 32)
        self.assertTrue(math.isfinite(first["expected_gain_s"]))
        self.assertEqual(first["measure_switch_cost_s"], 6)
        state.measuring_channel = 1
        self.assertEqual(policy._auxiliary_value(state, state.channels[1], (100., 100.))["measure_switch_cost_s"], 5)
        print(f"single auxiliary valuation wall_s={elapsed:.6f}")

    def test_actual_low_value_auxiliary_measurement_is_skipped(self):
        path = PROJECT / "outputs/q4/holdout01/cases/holdout_943004_uniform_outward_hashed/selected/actions.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        state, policy = common.Q4State(), MicroBPolicy()
        for row in rows[:43]:
            state.update(row, row["response"])
        target = rows[43]
        self.assertEqual((target["step"], target["channel"]), (44, 8))
        self.assertFalse(policy._keep_auxiliary(state, state.channels[8], tuple(target["position"])))
        record = policy.b_evaluations[-1]
        self.assertEqual(record["expected_gain_s"], 0.)
        self.assertEqual(record["negative_work_s"], record["before_work_s"])
        self.assertEqual(state.channels[8].status, "found")
        self.assertNotIn(tuple(target["position"]), state.channels[8].measured)

    def test_actual_c9_negative_branch_has_large_nonzero_value(self):
        path = PROJECT / "outputs/q4/pressure01/cases/pressure_944001_edge_tangent_hashed/selected/actions.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        state = common.Q4State()
        channel = state.channels[9]
        # 只读原公开反馈前缀：直接恢复旧阴性历史，阳性经正式update恢复几何。
        for row in rows[:332]:
            if row["channel"] != 9:
                continue
            q, response = tuple(row["position"]), row["response"]
            if response.get("measure_result") == "no_signal":
                channel.observations.append((q, "no_signal", None))
                channel.measured.add(q)
            else:
                state.update(row, response)
        before = channel.circle()[1]
        q = tuple(rows[333]["position"])
        negative = hypothetical_channel(state, channel, q, "no_signal")
        self.assertAlmostEqual(before, 389.3356709256726, places=6)
        self.assertAlmostEqual(negative.circle()[1], 134.28198796719758, places=6)
        policy = MicroBPolicy()
        value = policy._auxiliary_value(state, channel, q)
        self.assertGreater(value["before_work_s"] - value["negative_work_s"], 100.)
        self.assertGreater(value["expected_gain_s"], value["measure_switch_cost_s"])
        print("C9 negative information value", json.dumps(value, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main(verbosity=2)
