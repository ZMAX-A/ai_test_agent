import io
import unittest
from contextlib import redirect_stdout

from config.settings import settings
from tests.test_web_agent_auth import _Page, _policy
from web_agent.browser import PolicyAwareBrowserExecutor


class WebAgentLoginSecurityTests(unittest.TestCase):
    def test_model_supplied_login_value_is_ignored_and_never_logged(self):
        page = _Page()
        executor = PolicyAwareBrowserExecutor(
            page, visual_sensor=object(), auth_policy=_policy()
        )
        untrusted_value = "model-supplied-not-a-credential"
        output = io.StringIO()
        with redirect_stdout(output):
            result = executor.execute({
                "action": "fill",
                "parameters": {
                    "role": "textbox",
                    "index": 0,
                    "value": untrusted_value,
                },
            })
        self.assertTrue(result["success"])
        self.assertEqual(page.values["username"], settings.LOGIN_USERNAME)
        self.assertNotIn(untrusted_value, output.getvalue())
        self.assertNotIn(settings.LOGIN_USERNAME, output.getvalue())

    def test_ambiguous_login_fill_fails_closed_without_echoing_value(self):
        page = _Page()
        executor = PolicyAwareBrowserExecutor(
            page, visual_sensor=object(), auth_policy=_policy()
        )
        untrusted_value = "must-not-appear"
        output = io.StringIO()
        with redirect_stdout(output):
            result = executor.execute({
                "action": "fill",
                "parameters": {"role": "textbox", "value": untrusted_value},
            })
        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "AMBIGUOUS_LOGIN_FIELD")
        self.assertNotIn(untrusted_value, output.getvalue())


if __name__ == "__main__":
    unittest.main()
