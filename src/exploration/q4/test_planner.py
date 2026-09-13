"""共享发现计划的连续证书、状态隔离和扫描承诺检查。"""
import copy
import unittest

from common import Q4State, Q4_SYMMETRIC25_ANCHORS
from planner import build_plan, _can_promise_scan
from q4_coverage import q4_coverage_certificate


def semantic_snapshot(state):
    return copy.deepcopy(dict(position=state.position, channel=state.measuring_channel,
                              time=state.virtual_time_s, actions=state.actions,
                              ever_seen=state.ever_seen, proofs=state.absence_proofs,
                              channels={j: dict(status=c.status, observations=c.observations,
                                                exclusions=c.exclusions, polygon=c.polygon,
                                                measured=c.measured, anchors_missed=c.anchors_missed)
                                        for j, c in state.channels.items()}))


class PlannerTests(unittest.TestCase):
    def test_no_service_contribution_does_not_add_unknown_scans(self):
        state = Q4State()
        state.channels[1].status = "found"
        jobs = [dict(kind="measure", position=(0.0, 0.0), channel=1)]
        original = copy.deepcopy(jobs)
        route, info = build_plan(state, jobs, Q4_SYMMETRIC25_ANCHORS, prune_limit=0)
        self.assertFalse(next(j for j in route if j["kind"] == "measure")["scan_unknown"])
        self.assertEqual(jobs, original)
        self.assertEqual(info["scan_stops"], 25)

    def test_safe_substitute_requires_full_continuous_certificate(self):
        state = Q4State()
        state.channels[1].status = "found"
        state.channels[2].status = "found"
        jobs = [dict(kind="measure", position=(1898.0, 0.0), channel=1),
                dict(kind="measure", position=(3500.0, 0.0), channel=2)]
        before = semantic_snapshot(state)
        route, info = build_plan(state, jobs, Q4_SYMMETRIC25_ANCHORS)
        self.assertEqual(semantic_snapshot(state), before)
        self.assertTrue(info["adopted_substitution"])
        self.assertIn((1888.0, 0.0), info["removed_anchors"])
        self.assertEqual(sum(j["kind"] == "measure" for j in route), 2)
        service = {j["channel"]: j for j in route if j["kind"] == "measure"}
        self.assertTrue(service[1]["scan_unknown"])
        self.assertFalse(service[2]["scan_unknown"])
        points = [j["position"] for j in route if j["scan_unknown"]]
        certificate = q4_coverage_certificate(points)
        self.assertTrue(certificate.complete and certificate.rational_verified)
        self.assertLess(info["estimated_cost_s"], info["base_estimated_cost_s"])
        self.assertLessEqual(info["certificate_checks"], 12)
        self.assertLessEqual(info["anchor_candidates_checked"], 6)

    def test_risky_clearance_jobs_cannot_replace_discovery(self):
        state = Q4State()
        state.channels[1].status = "found"
        for kind in ("multi", "try", "cell"):
            jobs = [dict(kind=kind, position=(1898.0, 0.0), channel=1)]
            route, _ = build_plan(state, jobs, Q4_SYMMETRIC25_ANCHORS)
            self.assertFalse(next(j for j in route if j["kind"] == kind)["scan_unknown"])

    def test_negative_history_cannot_be_borrowed_across_channels(self):
        state = Q4State()
        for j, c in state.channels.items():
            if j not in (1, 2):
                c.status = "absent"
        state.channels[1].observations = [(q, "no_signal", None) for q in Q4_SYMMETRIC25_ANCHORS]
        state.channels[1].measured = set(Q4_SYMMETRIC25_ANCHORS)
        route, info = build_plan(state, [], Q4_SYMMETRIC25_ANCHORS, prune_limit=0)
        self.assertEqual(len(route), 25)
        self.assertEqual(info["unknown_count"], 2)
        self.assertEqual(info["scan_stops"], 25)
        self.assertEqual(state.channels[2].observations, [])

    def test_certified_clear_promises_only_its_safe_location(self):
        state = Q4State()
        c = state.channels[1]
        c.status, c.near_position = "found", (944.0, 0.0)
        self.assertTrue(_can_promise_scan(state, dict(kind="clear", channel=1, position=(944.0, 0.0))))
        self.assertFalse(_can_promise_scan(state, dict(kind="clear", channel=1, position=(1100.0, 0.0))))

    def test_no_unknown_only_routes_service_jobs(self):
        state = Q4State()
        for c in state.channels.values():
            c.status = "absent"
        state.channels[1].status = "found"
        jobs = [dict(kind="measure", channel=1, position=(100.0, 0.0))]
        route, info = build_plan(state, jobs, Q4_SYMMETRIC25_ANCHORS)
        self.assertEqual(len(route), 1)
        self.assertFalse(route[0]["scan_unknown"])
        self.assertEqual(info["scan_stops"], 0)


if __name__ == "__main__":
    unittest.main()
