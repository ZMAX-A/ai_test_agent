import unittest

from web_agent.commands import production_dependencies
from web_agent.reasoning import CredentialAwareReasoningState


class WebAgentReasoningTests(unittest.TestCase):
    def test_username_goal_is_deterministic_and_uses_reference(self):
        state = CredentialAwareReasoningState(
            "在用户名输入框输入 {{credential.username}}"
        )
        state.observe("textbox textbox combobox", "https://example.test/login", "登录")
        action = state.deterministic_action()
        self.assertEqual(action["action"], "fill")
        self.assertEqual(action["parameters"]["index"], 0)
        self.assertEqual(
            action["parameters"]["value"], "{{credential.username}}"
        )

    def test_password_goal_is_deterministic_and_uses_reference(self):
        state = CredentialAwareReasoningState(
            "在密码输入框输入 {{credential.password}}"
        )
        state.observe("textbox textbox combobox", "https://example.test/login", "登录")
        action = state.deterministic_action()
        self.assertEqual(action["parameters"]["index"], 1)
        self.assertEqual(
            action["parameters"]["value"], "{{credential.password}}"
        )

    def test_production_composition_uses_credential_reasoning(self):
        dependencies = production_dependencies()
        self.assertIs(
            dependencies.reasoning_factory,
            CredentialAwareReasoningState,
        )


if __name__ == "__main__":
    unittest.main()
