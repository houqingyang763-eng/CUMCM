"""正式入口配置和依赖封闭性检查；不访问研究代码或真实接口。"""
from pathlib import Path
import sys
import unittest

import common
from selected import SelectedPolicy, selected_parameters
from run import make_policy, source_paths
from practice import policy_and_state


class SelectedTests(unittest.TestCase):
    def test_selected_is_explicit_shared25(self):
        config = selected_parameters()
        self.assertTrue(config["prune_planned_stops"])
        self.assertTrue(config["use_belief"])
        self.assertTrue(config["use_multiclear"])
        self.assertEqual(config["opportunistic_scan_from_known"], 17)
        self.assertEqual(config["rollout_samples"], 0)
        self.assertEqual(len(SelectedPolicy().anchors), 25)

    def test_selected_cannot_be_overridden_at_entry(self):
        with self.assertRaises(ValueError):
            make_policy("selected", {"use_belief": False})
        with self.assertRaises(ValueError):
            policy_and_state("selected", {"use_belief": False})

    def test_only_local_runtime_dependencies(self):
        policy_and_state()
        common.require_local_dependencies()
        files = source_paths()
        self.assertTrue(all(common.ROOT in p.parents for p in files))
        self.assertIn(common.ROOT / "planner.py", files)
        self.assertIn(common.ROOT / "selected_config.json", files)
        self.assertNotIn("astra_guard", sys.modules)
        self.assertNotIn("q4run", sys.modules)


if __name__ == "__main__":
    unittest.main()
