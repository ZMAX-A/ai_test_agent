import unittest

from agents.critic_agent import CriticAgent


class LoginCriticTests(unittest.TestCase):
    def setUp(self):
        self.critic = CriticAgent.__new__(CriticAgent)
        self.critic.last_model_call_count = 0
        self.action = {
            "action": "click",
            "parameters": {"role": "button", "name": "登 录"},
        }
        self.context = {
            "step_goal": "点击登录按钮",
            "page_state": "textbox 用户名; textbox 密码; combobox 请选择门店",
        }

    def test_login_click_is_replaced_when_store_not_selected(self):
        result = self.critic.review(self.action, self.context, {"recent_actions": []})
        self.assertFalse(result.approved)
        self.assertEqual(result.replacement["action"], "select_option")
        self.assertEqual(self.critic.last_model_call_count, 0)

    def test_login_click_is_allowed_after_verified_selection(self):
        world = {
            "recent_actions": [
                {"action": "select_option", "success": True, "parameters": {}}
            ]
        }
        result = self.critic.review(self.action, self.context, world)
        self.assertTrue(result.approved)
        self.assertIn("确认", result.reason)


if __name__ == "__main__":
    unittest.main()
