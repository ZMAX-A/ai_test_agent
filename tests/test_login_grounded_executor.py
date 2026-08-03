import unittest
from unittest.mock import patch

from executor.login_grounded_secure_exec import LoginGroundedSecureExecutor
from runner.verified_unified_runner import VerifiedUnifiedSmartRunner


class _Locator:
    def __init__(self):
        self.first = self
        self.filled = None
        self.clicked = False

    def wait_for(self, **_kwargs):
        return None

    def fill(self, value, **_kwargs):
        self.filled = value

    def click(self, **_kwargs):
        self.clicked = True


class _Page:
    url = "https://example.test/login"

    def __init__(self):
        self.password = _Locator()
        self.submit = _Locator()

    def locator(self, selector):
        if selector == "input[type='password']":
            return self.password
        if selector == "button[type='submit']":
            return self.submit
        return _Locator()

    def title(self):
        return "Login"


class LoginGroundedExecutorTests(unittest.TestCase):
    def test_password_uses_semantic_password_locator(self):
        page = _Page()
        executor = LoginGroundedSecureExecutor(page, visual_sensor=object())
        with patch("executor.login_grounded_secure_exec.settings.LOGIN_PASSWORD", "secret"):
            result = executor.execute({
                "action": "fill",
                "parameters": {"som_index": 99, "value": "secret"},
            })
        self.assertTrue(result["success"])
        self.assertEqual(page.password.filled, "secret")

    def test_login_click_uses_submit_button(self):
        page = _Page()
        executor = LoginGroundedSecureExecutor(page, visual_sensor=object())
        result = executor.execute({
            "action": "click",
            "parameters": {"role": "button", "name": "登 录"},
        })
        self.assertTrue(result["success"])
        self.assertTrue(page.submit.clicked)

    def test_production_runner_binds_login_grounded_executor(self):
        self.assertIs(
            VerifiedUnifiedSmartRunner.run_case.__globals__["SecurePlaywrightExecutor"],
            LoginGroundedSecureExecutor,
        )


if __name__ == "__main__":
    unittest.main()
