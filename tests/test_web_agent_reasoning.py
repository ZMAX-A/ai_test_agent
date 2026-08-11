import unittest

from web_agent.commands import production_dependencies
from web_agent.reasoning import CredentialAwareReasoningState
from web_agent.runner import ProductionRunner


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

    def test_store_selection_is_deterministic(self):
        state = CredentialAwareReasoningState("选择门店")
        state.observe("combobox", "https://example.test/login", "登录")
        action = state.deterministic_action()
        self.assertEqual(action["action"], "select_option")
        self.assertEqual(action["parameters"]["role"], "combobox")

    def test_login_submit_is_deterministic(self):
        state = CredentialAwareReasoningState("点击登录")
        state.observe("button 登录", "https://example.test/login", "登录")
        action = state.deterministic_action()
        self.assertEqual(action["action"], "click")
        self.assertEqual(action["parameters"]["role"], "button")

    def test_login_submit_ignores_store_words_in_success_criteria(self):
        state = CredentialAwareReasoningState(
            "\u70b9\u51fb\u767b\u5f55",
            "\u5df2\u9009\u62e9\u95e8\u5e97\u5e76\u767b\u5f55\u6210\u529f",
        )
        state.observe(
            "button",
            "https://example.test/login",
            "\u767b\u5f55",
        )
        action = state.deterministic_action()
        self.assertEqual(action["action"], "click")
        self.assertEqual(action["parameters"]["role"], "button")

    def test_navigation_menu_click_is_deterministic(self):
        state = CredentialAwareReasoningState("点击顾客档案菜单")
        state.observe("link 顾客档案", "https://example.test/", "首页")
        action = state.deterministic_action()
        self.assertEqual(action["action"], "click")
        self.assertEqual(action["parameters"]["role"], "link")
        self.assertEqual(action["parameters"]["name"], "顾客档案")

    def test_detail_button_click_is_deterministic(self):
        state = CredentialAwareReasoningState("点击用户卡片或详情按钮")
        state.observe("button 详情", "https://example.test/customer", "顾客档案")
        action = state.deterministic_action()
        self.assertEqual(action["action"], "click")
        self.assertEqual(action["parameters"]["role"], "link")
        self.assertEqual(action["parameters"]["name"], "详情")

    def test_production_composition_uses_credential_reasoning(self):
        dependencies = production_dependencies()
        self.assertIs(
            dependencies.reasoning_factory,
            CredentialAwareReasoningState,
        )

    def test_runner_overwrites_untrusted_url_change_snapshot(self):
        execution = {
            "page_change": {
                "url_changed": True,
                "old_url": "stale",
                "new_url": "stale",
            }
        }
        ProductionRunner._merge_page_change(
            execution, "https://example.test", "https://example.test"
        )
        self.assertFalse(execution["page_change"]["url_changed"])
        self.assertNotIn("old_url", execution["page_change"])
        self.assertTrue(
            ProductionRunner._is_sensitive_url("https://example.test/customer/U")
        )
        self.assertFalse(ProductionRunner._is_sensitive_url("https://example.test/"))


if __name__ == "__main__":
    unittest.main()
