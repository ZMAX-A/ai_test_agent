import unittest

import runner.multi_agent_runner as base_runner
from agents.deliberative_executor_agent import DeliberativeExecutorAgent
from runner.reasoning_runtime_activation import (
    ReasoningAgentRunner,
    current_world_model,
)


class ReasoningActivationTests(unittest.TestCase):
    def test_new_task_binds_fresh_world_model(self):
        board = base_runner.TaskBlackboard("reason-1", "任务", "目标")
        self.assertEqual(current_world_model().task_id, board.task_id)

    def test_runner_uses_deliberative_executor(self):
        agent = base_runner.ExecutorAgent()
        self.assertIsInstance(agent, DeliberativeExecutorAgent)

    def test_manifest_contains_six_formal_agents(self):
        manifest = ReasoningAgentRunner.capability_manifest()
        self.assertEqual(
            set(manifest),
            {"planner", "coordinator", "executor", "verifier", "critic", "replanner"},
        )


if __name__ == "__main__":
    unittest.main()
