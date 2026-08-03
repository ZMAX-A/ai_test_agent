import unittest

from core.authenticated_collaborative_reasoning import AuthenticatedCollaborativeStepReasoningState


class ExplicitLoginRecoveryTests(unittest.TestCase):
    def test_first_login_click_routes_to_required_store(self):
        state = AuthenticatedCollaborativeStepReasoningState("点击登录按钮")
        state.observe("textbox textbox combobox 请选择门店", "https://example.test/login", "登录")
        click = {"action": "click", "parameters": {"role": "button", "name": "登 录"}}
        state.record(1, click, {"success": True, "message": "clicked"}, state.current_url, state.current_url)
        action = state.deterministic_action()
        self.assertEqual(action["action"], "select_option")

    def test_store_selection_routes_to_second_login_click(self):
        state = AuthenticatedCollaborativeStepReasoningState("点击登录按钮")
        state.observe("textbox textbox combobox", "https://example.test/login", "登录")
        click = {"action": "click", "parameters": {"role": "button", "name": "登 录"}}
        state.record(1, click, {"success": True}, state.current_url, state.current_url)
        select = state.deterministic_action()
        state.record(2, select, {"success": True}, state.current_url, state.current_url)
        action = state.deterministic_action()
        self.assertEqual(action["action"], "click")
        self.assertEqual(action["parameters"]["name"], "登 录")


if __name__ == "__main__":
    unittest.main()
