import unittest

from executor.keyboard_verified_secure_playwright_exec import (
    KeyboardVerifiedSecurePlaywrightExecutor,
)
from runner.verified_unified_runner import VerifiedUnifiedSmartRunner


class _Keyboard:
    def __init__(self, page):
        self.page = page
        self.pressed = []

    def press(self, key):
        self.pressed.append(key)
        if key == "Enter":
            self.page.selected = "verified-store"


class _Node:
    def __init__(self, page, text=""):
        self.page = page
        self.text = text

    def wait_for(self, **_kwargs):
        return None

    def click(self, **_kwargs):
        return None

    def inner_text(self, **_kwargs):
        return self.text or self.page.selected


class _Collection:
    def __init__(self, nodes):
        self.nodes = nodes
        self.first = nodes[0] if nodes else self

    def count(self):
        return len(self.nodes)

    def nth(self, index):
        return self.nodes[index]


class _Page:
    url = "https://example.test/login"

    def __init__(self):
        self.selected = ""
        self.keyboard = _Keyboard(self)
        self.combo = _Node(self)

    def get_by_role(self, **_kwargs):
        return self.combo

    def locator(self, selector):
        if "selection-item" in selector and self.selected:
            return _Collection([_Node(self, self.selected)])
        return _Collection([])

    def wait_for_timeout(self, _timeout):
        return None

    def title(self):
        return "Login"


class KeyboardVerifiedExecutorTests(unittest.TestCase):
    def test_keyboard_selection_requires_visible_readback(self):
        page = _Page()
        executor = KeyboardVerifiedSecurePlaywrightExecutor(page, visual_sensor=object())
        result = executor.execute({
            "action": "select_option",
            "parameters": {"role": "combobox", "option_text": ""},
        })
        self.assertTrue(result["success"])
        self.assertEqual(page.keyboard.pressed, ["ArrowDown", "Enter"])
        self.assertIn("verified-store", result["message"])

    def test_production_runner_binds_verified_executor(self):
        self.assertIs(
            VerifiedUnifiedSmartRunner.run_case.__globals__["SecurePlaywrightExecutor"],
            KeyboardVerifiedSecurePlaywrightExecutor,
        )


if __name__ == "__main__":
    unittest.main()
