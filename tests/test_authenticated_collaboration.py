import unittest

from config.settings import settings
from core.authenticated_collaborative_reasoning import AuthenticatedCollaborativeStepReasoningState


class AuthenticatedCollaborationTests(unittest.TestCase):
    def setUp(self):
        self.username = settings.LOGIN_USERNAME
        self.password = settings.LOGIN_PASSWORD
        settings.LOGIN_USERNAME = "demo-user"
        settings.LOGIN_PASSWORD = "demo-pass"

    def tearDown(self):
        settings.LOGIN_USERNAME = self.username
        settings.LOGIN_PASSWORD = self.password

    def _redirected_state(self):
        state = AuthenticatedCollaborativeStepReasoningState("进入顾客档案 /customer")
        state.observe("textbox textbox combobox", "https://example.test/login", "登录")
        goto = {"action": "goto", "parameters": {"url": "https://example.test/customer"}}
        state.record(1, goto, {"success": True, "message": "redirect"},
                     state.current_url, state.current_url)
        return state

    def test_recovery_refills_username_first(self):
        action = self._redirected_state().deterministic_action()
        self.assertEqual(action["action"], "fill")
        self.assertEqual(action["parameters"]["index"], 0)

    def test_recovery_sequence_reaches_password(self):
        state = self._redirected_state()
        username = state.deterministic_action()
        state.record(2, username, {"success": True, "message": "ok"},
                     state.current_url, state.current_url)
        password = state.deterministic_action()
        self.assertEqual(password["action"], "fill")
        self.assertEqual(password["parameters"]["index"], 1)


if __name__ == "__main__":
    unittest.main()
