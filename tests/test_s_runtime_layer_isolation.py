"""在验证基础 ToolRuntime 前恢复它自己的依赖层。

生产入口各自在独立进程激活；unittest discover 则把所有入口加载到同一进程，
因此需要显式选择即将验证的层。
"""

import unittest

import runner.multi_agent_runner as base_runner
from runner.tool_runtime_integration import RuntimeExecutorAgent, RuntimeVerifierAgent


class RuntimeLayerIsolationTests(unittest.TestCase):
    def test_select_base_tool_runtime_layer(self):
        base_runner.ExecutorAgent = RuntimeExecutorAgent
        base_runner.VerifierAgent = RuntimeVerifierAgent
        self.assertIs(base_runner.ExecutorAgent, RuntimeExecutorAgent)


if __name__ == "__main__":
    unittest.main()
