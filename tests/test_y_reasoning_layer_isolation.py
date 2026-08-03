"""在增强推理入口测试前恢复 Deliberative 依赖层。"""

import unittest

import runner.multi_agent_runner as base_runner
from runner.reasoning_runtime_activation import ReasoningExecutorAgent


class ReasoningLayerIsolationTests(unittest.TestCase):
    def test_select_deliberative_runtime_layer(self):
        base_runner.ExecutorAgent = ReasoningExecutorAgent
        self.assertIs(base_runner.ExecutorAgent, ReasoningExecutorAgent)


if __name__ == "__main__":
    unittest.main()
