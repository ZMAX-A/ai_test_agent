import unittest

from agents.coordinator_agent import CoordinatorAgent
from agents.verifier_agent import VerifierAgent
from core.blackboard import TaskBlackboard
from core.reasoning_engine import StepReasoningState


class _Locator:
    def __init__(self, value=""):
        self.value = value

    def nth(self, _index):
        return self

    def input_value(self, timeout=0):
        return self.value


class _Page:
    def __init__(self, url="https://example.test/login", title="登录", value=""):
        self.url = url
        self._title = title
        self._value = value

    def title(self):
        return self._title

    def get_by_role(self, **_kwargs):
        return _Locator(self._value)

    def locator(self, _selector):
        return _Locator(self._value)


class MultiAgentTests(unittest.TestCase):
    def test_blackboard_redacts_action_values(self):
        board = TaskBlackboard("1", "登录", "登录")
        board.start_step(1, "输入密码")
        board.publish("executor", "action_proposed", action={
            "action": "fill", "parameters": {"role": "textbox", "value": "secret"}
        })
        self.assertNotIn("secret", board.compact_context())
        self.assertIn("<redacted:6>", board.compact_context())

    def test_verifier_accepts_target_url(self):
        result = VerifierAgent().verify(
            _Page("https://example.test/customer", "顾客档案"),
            "进入顾客档案 /customer",
            page_state="heading 顾客档案",
        )
        self.assertTrue(result.passed)
        self.assertGreaterEqual(result.confidence, 0.9)

    def test_verifier_reads_input_value_independently(self):
        action = {"action": "fill", "parameters": {
            "role": "textbox", "index": 0, "value": "demo"
        }}
        result = VerifierAgent().verify(
            _Page(value="demo"),
            "在第1个输入框输入 demo",
            action=action,
            action_result={"success": True, "message": "fill ok"},
        )
        self.assertTrue(result.passed)
        self.assertIn("回读输入框值与目标一致", result.evidence)

    def test_coordinator_escalates_perception(self):
        reasoning = StepReasoningState("点击登录")
        decision = CoordinatorAgent().choose_perception(reasoning, fail_count=1)
        self.assertEqual(decision.route, "visual_sensor")


if __name__ == "__main__":
    unittest.main()
