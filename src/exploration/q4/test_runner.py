"""验证影响整局正确性及可比性的接口契约、审计与旧对照等价性。"""
import ast
import copy
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import common
from common import PROJECT, Q4State, Q4_SYMMETRIC25_ANCHORS
from cases import build_cases, validate_scene
from run import IndependentAudit, public_response, run_case
from simulation import LocalEnvironment, Scenario, Source


class RunnerTests(unittest.TestCase):
    def test_legacy_definitions_ast_equal(self):
        old = ast.parse((PROJECT / "experiments/b_overnight/q4_anchor_design.py").read_text(encoding="utf-8"))
        new = ast.parse(Path(common.__file__).read_text(encoding="utf-8"))
        definitions = ("Q4ScaledAnchorConfig", "Q4ScaledAnchorPolicy", "Q4Symmetric25Policy")
        for name in definitions:
            first = next(n for n in old.body if isinstance(n, ast.ClassDef) and n.name == name)
            second = next(n for n in new.body if isinstance(n, ast.ClassDef) and n.name == name)
            self.assertEqual(ast.dump(first), ast.dump(second), name)
        for name in ("Q4_REDUCED_ANCHORS", "Q4_SYMMETRIC25_SPACING_M", "Q4_SYMMETRIC25_ANCHORS"):
            first = next(n for n in old.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id == name)
            second = next(n for n in new.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id == name)
            self.assertEqual(ast.dump(first), ast.dump(second), name)
        self.assertEqual(len(Q4_SYMMETRIC25_ANCHORS), 25)
        self.assertNotIn("q4run", sys.modules)
        self.assertNotIn("astra_guard", sys.modules)

    def test_official_timing_example(self):
        scene = Scenario("timing", 0, "unit", "zero", (Source(20, (1799, 0), 1000),))
        env, audit = LocalEnvironment(scene), IndependentAudit(scene)
        actions = [("measure", (300, 400), 1), ("measure", (300, 400), 2),
                   ("clear", (300, 0), 3), ("measure", (300, 0), 2)]
        for (kind, q, j), target_time in zip(actions, (105, 111, 194, 199)):
            action = dict(kind=kind, position=q, channel=j)
            response = env.act(action)
            audit.update(action, response)
            self.assertEqual(response["virtual_time_s"], target_time)
        self.assertEqual(audit.channel, 2)
        self.assertEqual(audit.ledger["switch_s"], 1)
        self.assertEqual(audit.ledger["failed_clear_s"], 3)

    def test_direction_boundary_and_backside_clear(self):
        scene = Scenario("direction", 0, "unit", "zero", (Source(2, (0, 0), 1000, 0),))
        env, audit = LocalEnvironment(scene), IndependentAudit(scene)
        actions = [("measure", (0, 1000), 2, "direction"),
                   ("measure", (-1, 100), 2, "no_signal"),
                   ("clear", (-20, 0), 2, "success"),
                   ("measure", (0, 1), 2, "no_signal")]
        for kind, q, j, expected in actions:
            action = dict(kind=kind, position=q, channel=j)
            response = env.act(action)
            audit.update(action, response)
            self.assertEqual(response["measure_result" if kind == "measure" else "clear_result"], expected)
        self.assertEqual(audit.cleared, {2})
        self.assertEqual(audit.ledger["switch_s"], 1)

    def test_tampered_feedback_rejected(self):
        scene = Scenario("tamper", 0, "unit", "zero", (Source(1, (100, 0), 1000),))
        action = dict(kind="measure", position=(0, 0), channel=1)
        response = LocalEnvironment(scene).act(action)
        response["svd_deg"] = 2.0
        with self.assertRaisesRegex(AssertionError, "误差"):
            IndependentAudit(scene).update(action, response)
        response = LocalEnvironment(scene).act(action)
        response["virtual_time_s"] += 1
        with self.assertRaisesRegex(AssertionError, "计费"):
            IndependentAudit(scene).update(action, response)

    def test_public_feedback_and_clear_history(self):
        state = Q4State()
        source = Source(1, (100, 0), 1000)
        env = LocalEnvironment(Scenario("history", 0, "unit", "zero", (source,)))
        for q in ((0, 0), (100, 0)):
            action = dict(kind="clear", position=q, channel=1)
            response = public_response(env.act(action))
            self.assertNotIn("costs", response)
            state.update(action, response)
        self.assertEqual(state.channels[1].clear_history, [((0, 0), "no_target_in_range"), ((100, 0), "success")])

    def test_scene_contract_and_seed_separation(self):
        seen = set()
        for split, count in (("smoke", 4), ("develop", 12), ("holdout", 24), ("pressure", 8)):
            scenes = build_cases(split)
            self.assertEqual(len(scenes), count)
            for scene in scenes:
                validate_scene(scene)
                self.assertNotIn(scene.seed, seen)
                seen.add(scene.seed)
                self.assertEqual(scene.to_dict(), build_cases(split)[scenes.index(scene)].to_dict())

    def test_failed_action_is_retained(self):
        class BrokenPolicy:
            config = None
            def choose(self, state):
                return dict(kind="measure", position=(0, 0), channel=21)
        with tempfile.TemporaryDirectory() as folder, patch("run.make_policy", return_value=BrokenPolicy()):
            result = run_case(build_cases("smoke", 1)[0], "broken", folder)
            self.assertFalse(result["success"])
            self.assertEqual(result["error_phase"], "environment")
            self.assertTrue((Path(folder) / "result.json").exists())
            self.assertEqual(json.loads((Path(folder) / "proposals.jsonl").read_text(encoding="utf-8"))["action"]["channel"], 21)
            self.assertIn("非法", result["error"])


if __name__ == "__main__":
    unittest.main()
