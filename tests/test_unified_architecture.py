import inspect
import unittest

from runner.unified_smart_runner import FORMAL_AGENTS, UnifiedSmartRunner


class UnifiedArchitectureTests(unittest.TestCase):
    def test_unified_runner_has_no_global_patch_dependency(self):
        source = inspect.getsource(inspect.getmodule(UnifiedSmartRunner))
        self.assertNotIn("base_runner", source)
        self.assertNotIn("install_tool_runtime", source)
        self.assertNotIn("install_reasoning_runtime", source)

    def test_manifest_matches_six_formal_agents(self):
        runner = UnifiedSmartRunner(headless=True)
        self.assertEqual(set(runner.capability_manifest()), set(FORMAL_AGENTS))

    def test_critic_and_replanner_have_no_browser_tools(self):
        manifest = UnifiedSmartRunner(headless=True).capability_manifest()
        self.assertEqual(manifest["critic"], [])
        self.assertEqual(manifest["replanner"], [])


if __name__ == "__main__":
    unittest.main()
