import unittest

from core.collaborative_reasoning import CollaborativeStepReasoningState


class CollaborativeReasoningTests(unittest.TestCase):
    def test_login_redirect_routes_to_store_selection(self):
        state = CollaborativeStepReasoningState("进入顾客档案 /customer")
        state.observe("combobox 请选择门店", "https://example.test/login", "登录")
        goto = {"action": "goto", "parameters": {"url": "https://example.test/customer"}}
        state.record(
            1, goto,
            {"success": True, "message": "被重定向回登录页"},
            "https://example.test/login", "https://example.test/login",
        )
        self.assertEqual(state.deterministic_action()["action"], "select_option")

    def test_store_selection_routes_to_login_click(self):
        state = CollaborativeStepReasoningState("进入顾客档案 /customer")
        state.observe("combobox 请选择门店", "https://example.test/login", "登录")
        goto = {"action": "goto", "parameters": {"url": "https://example.test/customer"}}
        state.record(1, goto, {"success": True, "message": "redirect"},
                     state.current_url, state.current_url)
        select = {"action": "select_option", "parameters": {"role": "combobox"}}
        state.record(2, select, {"success": True, "message": "selected"},
                     state.current_url, state.current_url)
        self.assertEqual(state.deterministic_action()["action"], "click")


if __name__ == "__main__":
    unittest.main()
