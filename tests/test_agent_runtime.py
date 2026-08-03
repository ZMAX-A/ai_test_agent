import unittest
from types import SimpleNamespace

from agents.tool_aware_executor_agent import ToolAwareExecutorAgent
from core.agent_runtime import AgentRuntime
from core.blackboard import TaskBlackboard
from core.tool_registry import ToolPermissionError, create_web_tool_registry


class _BrowserExecutor:
    def __init__(self):
        self.actions = []

    def execute(self, action):
        self.actions.append(action)
        return {"success": True, "message": "ok"}


class AgentRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.registry = create_web_tool_registry()
        self.board = TaskBlackboard("runtime-1", "工具测试", "工具测试")
        self.runtime = AgentRuntime(self.registry, self.board)

    def test_each_agent_has_isolated_capabilities(self):
        self.assertEqual(self.runtime.capabilities("planner"), [])
        self.assertIn("click", self.runtime.capabilities("executor"))
        self.assertIn("observe_aria", self.runtime.capabilities("coordinator"))
        self.assertEqual(self.runtime.capabilities("verifier"), ["verify_page"])

    def test_runtime_blocks_cross_role_tool_use(self):
        with self.assertRaises(ToolPermissionError):
            self.runtime.invoke("verifier", "click", {"role": "button"})
        self.assertEqual(self.board.events[-1].event, "tool_denied")

    def test_executor_action_is_dispatched_and_audited(self):
        browser = _BrowserExecutor()
        result = self.runtime.invoke(
            "executor",
            "fill",
            {"role": "textbox", "value": "secret"},
            {"browser_executor": browser, "thought": "填写输入框"},
        )
        self.assertTrue(result["success"])
        self.assertEqual(browser.actions[0]["action"], "fill")
        self.assertNotIn("secret", self.board.compact_context(limit=10))

    def test_openai_schema_is_generated_from_action_contract(self):
        tools = self.runtime.openai_tools("executor")
        fill = next(tool for tool in tools if tool["function"]["name"] == "fill")
        parameters = fill["function"]["parameters"]
        self.assertIn("value", parameters["required"])
        self.assertFalse(parameters["additionalProperties"])

    def test_native_tool_call_decodes_to_existing_action_protocol(self):
        function = SimpleNamespace(name="click", arguments='{"role":"button","name":"登录"}')
        message = SimpleNamespace(
            content="点击登录按钮",
            tool_calls=[SimpleNamespace(function=function)],
        )
        action = ToolAwareExecutorAgent._decode_message(message)
        self.assertEqual(action["action"], "click")
        self.assertEqual(action["parameters"]["name"], "登录")


if __name__ == "__main__":
    unittest.main()
