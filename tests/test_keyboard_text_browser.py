import unittest

from web_agent.auth import AuthenticationPolicy
from web_agent.keyboard_text_browser import KeyboardTextPolicyBrowserExecutor


class _Node:
    def __init__(self, page, kind):
        self.page = page
        self.kind = kind
        self.first = self

    def wait_for(self, **_kwargs):
        return None

    def click(self, **_kwargs):
        return None

    def inner_text(self, **_kwargs):
        if self.kind == "active":
            return self.page.options[self.page.active]
        if self.kind == "selected":
            return self.page.selected
        return ""

    def count(self):
        if self.kind == "options":
            return len(self.page.options)
        if self.kind == "selected":
            return 1 if self.page.selected else 0
        return 1

    def nth(self, _index):
        return self


class _Keyboard:
    def __init__(self, page):
        self.page = page
        self.keys = []

    def press(self, key):
        self.keys.append(key)
        if key == "ArrowDown":
            self.page.active = (self.page.active + 1) % len(self.page.options)
        elif key == "Enter":
            self.page.selected = self.page.options[self.page.active]


class _Page:
    url = "https://example.test/login"

    def __init__(self):
        self.options = ["门店1", "zwf1"]
        self.active = 0
        self.selected = ""
        self.keyboard = _Keyboard(self)

    def get_by_role(self, _role):
        return _Node(self, "combo")

    def locator(self, selector):
        if "item-option-active" in selector:
            return _Node(self, "active")
        if selector.endswith(".ant-select-item-option"):
            return _Node(self, "options")
        if "selection-item" in selector or "aria-selected" in selector:
            return _Node(self, "selected")
        return _Node(self, "other")

    def wait_for_timeout(self, _timeout):
        return None

    def title(self):
        return "Login"


class KeyboardTextBrowserTests(unittest.TestCase):
    def test_target_option_is_committed_with_enter(self):
        policy = AuthenticationPolicy(store_option_text="zwf1", store_selection_mode="text")
        page = _Page()
        executor = KeyboardTextPolicyBrowserExecutor(
            page, visual_sensor=object(), auth_policy=policy
        )
        result = executor.execute({
            "action": "select_option",
            "parameters": {"role": "combobox", "option_text": ""},
        })
        self.assertTrue(result["success"])
        self.assertEqual(page.selected, "zwf1")
        self.assertEqual(page.keyboard.keys, ["ArrowDown", "Enter"])


if __name__ == "__main__":
    unittest.main()
