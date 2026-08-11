import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

from config.settings import settings
from executor.playwright_exec import PlaywrightExecutor
from web_agent.auth import AuthenticationPolicy
from web_agent.browser import PolicyAwareBrowserExecutor


class _Locator:
    def __init__(self, page, kind, text=""):
        self.page = page
        self.kind = kind
        self.text = text
        self.first = self

    def wait_for(self, **_kwargs):
        return None

    def fill(self, value, **_kwargs):
        self.page.values[self.kind] = value

    def input_value(self, **_kwargs):
        return self.page.values.get(self.kind, "")

    def click(self, **_kwargs):
        if self.kind == "submit":
            self.page.url = "https://example.test/"
        elif self.kind == "text_option":
            self.page.values["store"] = self.text

    def all_inner_texts(self):
        if self.kind == "selected":
            value = self.page.values.get("store", "")
            return [value] if value else []
        if self.kind == "errors":
            return list(self.page.errors)
        return [self.text] if self.text else []


class _Keyboard:
    def __init__(self, page):
        self.page = page
        self.keys = []

    def press(self, key):
        self.keys.append(key)
        if key == "Enter":
            self.page.values["store"] = "configured-store"


class _Page:
    def __init__(self):
        self.url = "https://example.test/login"
        self.values = {"username": "", "password": "", "store": ""}
        self.errors = []
        self.keyboard = _Keyboard(self)

    def locator(self, selector):
        if selector == "#username":
            return _Locator(self, "username")
        if selector == "#password":
            return _Locator(self, "password")
        if selector == "#store":
            return _Locator(self, "store")
        if selector == "#selected-store":
            return _Locator(self, "selected")
        if selector == "#submit":
            return _Locator(self, "submit")
        if "item-option:has-text" in selector:
            return _Locator(self, "text_option", "named-store")
        if "ant-message" in selector:
            return _Locator(self, "errors")
        return _Locator(self, "other")

    def wait_for_timeout(self, _timeout):
        return None

    def wait_for_function(self, _expression, _arg=None, **_kwargs):
        return None

    def title(self):
        return "Login"


def _policy(**overrides):
    values = {
        "login_path": "/login",
        "username_selector": "#username",
        "password_selector": "#password",
        "store_selector": "#store",
        "selected_store_selector": "#selected-store",
        "submit_selector": "#submit",
        "settle_ms": 2000,
    }
    values.update(overrides)
    return AuthenticationPolicy(**values)


class AuthenticationPolicyTests(unittest.TestCase):
    def test_environment_can_select_store_by_text(self):
        with patch.dict(os.environ, {
            "LOGIN_STORE_SELECTION_MODE": "text",
            "LOGIN_STORE_OPTION_TEXT": "named-store",
        }, clear=False):
            policy = AuthenticationPolicy.from_environment()
        policy.validate()
        self.assertEqual(policy.store_selection_mode, "text")
        self.assertEqual(policy.store_option_text, "named-store")

    def test_text_mode_requires_option(self):
        policy = _policy(store_selection_mode="text", store_option_text="")
        with self.assertRaises(ValueError):
            policy.validate()


class PlaywrightExecutorTests(unittest.TestCase):
    def test_named_option_mismatch_fails_closed(self):
        page = MagicMock()
        page.url = "https://example.test/form"
        page.title.return_value = "Form"

        combo = MagicMock()
        focus = MagicMock()
        focus.first = focus
        focus.text_content.return_value = "different option"
        missing = MagicMock()
        missing.first = missing
        missing.click.side_effect = RuntimeError("not found")
        body = MagicMock()
        body.inner_text.return_value = ""

        page.get_by_role.return_value = combo
        page.get_by_text.return_value = missing

        def locate(selector):
            if selector == ":focus":
                return focus
            if selector == "body":
                return body
            return missing

        page.locator.side_effect = locate
        with tempfile.TemporaryDirectory() as screenshot_dir:
            executor = PlaywrightExecutor(
                page,
                visual_sensor=object(),
                screenshot_dir=screenshot_dir,
            )
            result = executor.execute({
                "action": "select_option",
                "parameters": {
                    "role": "combobox",
                    "option_text": "requested option",
                },
            })
        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "ELEMENT_NOT_FOUND")


class PolicyAwareBrowserExecutorTests(unittest.TestCase):
    def test_login_flow_has_verified_postconditions_and_redacted_logs(self):
        page = _Page()
        executor = PolicyAwareBrowserExecutor(
            page, visual_sensor=object(), auth_policy=_policy()
        )
        output = io.StringIO()
        with redirect_stdout(output):
            username = executor.execute({
                "action": "fill",
                "parameters": {"som_index": 99, "value": settings.LOGIN_USERNAME},
            })
            password = executor.execute({
                "action": "fill",
                "parameters": {"som_index": 98, "value": settings.LOGIN_PASSWORD},
            })
            store = executor.execute({
                "action": "select_option",
                "parameters": {"role": "combobox", "option_text": ""},
            })
            submit = executor.execute({
                "action": "click",
                "parameters": {"role": "button", "name": "登 录"},
            })

        self.assertTrue(username["success"])
        self.assertTrue(password["success"])
        self.assertTrue(store["success"])
        self.assertTrue(submit["success"])
        self.assertTrue(submit["page_change"]["url_changed"])
        self.assertNotIn(settings.LOGIN_USERNAME, output.getvalue())
        self.assertNotIn(settings.LOGIN_PASSWORD, output.getvalue())

    def test_submit_fails_closed_when_form_is_incomplete(self):
        page = _Page()
        executor = PolicyAwareBrowserExecutor(
            page, visual_sensor=object(), auth_policy=_policy()
        )
        result = executor.execute({
            "action": "click",
            "parameters": {"role": "button", "name": "登录"},
        })
        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "PRECONDITION_FAILED")

    def test_sensitive_context_suppresses_executor_screenshots(self):
        executor = PolicyAwareBrowserExecutor(
            _Page(), visual_sensor=object(), auth_policy=_policy()
        )
        executor.suppress_screenshots = True
        self.assertEqual(
            executor._capture_fail_screenshot("sensitive"), ""
        )

if __name__ == "__main__":
    unittest.main()
