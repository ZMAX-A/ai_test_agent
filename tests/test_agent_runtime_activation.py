import unittest

import runner.multi_agent_runner as base_runner
from runner.agent_runtime_activation import AgentRuntimeTestRunner
from runner.tool_runtime_integration import RuntimeTaskBlackboard, current_runtime


class AgentRuntimeActivationTests(unittest.TestCase):
    def test_blackboard_constructor_binds_runtime(self):
        board = RuntimeTaskBlackboard("task-1", "测试", "目标")
        self.assertIs(current_runtime().blackboard, board)

    def test_base_runner_uses_bound_blackboard(self):
        self.assertIs(base_runner.TaskBlackboard, RuntimeTaskBlackboard)

    def test_recommended_runner_exposes_capabilities(self):
        manifest = AgentRuntimeTestRunner.capability_manifest()
        self.assertEqual(manifest["planner"], [])
        self.assertIn("click", manifest["executor"])


if __name__ == "__main__":
    unittest.main()
