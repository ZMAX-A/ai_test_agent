import unittest

import runner.multi_agent_runner as base_runner
from agents.tool_aware_executor_agent import ToolAwareExecutorAgent
from runner.runtime_collaborative_runner import RuntimeCollaborativeTestRunner
from runner.tool_runtime_integration import (
    RuntimeAriaSensor,
    RuntimeExecutorAgent,
    RuntimeTaskBlackboard,
    RuntimeVerifierAgent,
)


class ToolRuntimeIntegrationTests(unittest.TestCase):
    def test_existing_runner_dependencies_are_runtime_controlled(self):
        self.assertIs(base_runner.TaskBlackboard, RuntimeTaskBlackboard)
        self.assertIs(base_runner.ExecutorAgent, RuntimeExecutorAgent)
        self.assertIs(base_runner.AriaSensor, RuntimeAriaSensor)
        self.assertIs(base_runner.VerifierAgent, RuntimeVerifierAgent)

    def test_executor_uses_tool_aware_model_adapter(self):
        agent = base_runner.ExecutorAgent()
        self.assertIsInstance(agent, ToolAwareExecutorAgent)
        names = [tool["function"]["name"] for tool in agent.registry.openai_tools_for("executor")]
        self.assertIn("click", names)
        self.assertIn("assert_url", names)
        self.assertNotIn("verify_page", names)

    def test_capability_manifest_has_strict_role_boundaries(self):
        manifest = RuntimeCollaborativeTestRunner.capability_manifest()
        self.assertEqual(manifest["planner"], [])
        self.assertEqual(manifest["verifier"], ["verify_page"])
        self.assertEqual(set(manifest["coordinator"]), {"observe_aria", "observe_visual"})
        self.assertIn("fill", manifest["executor"])


if __name__ == "__main__":
    unittest.main()
