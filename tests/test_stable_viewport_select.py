import unittest

from executor.viewport_secure_playwright_exec import ViewportSecurePlaywrightExecutor


class _Node:
    def __init__(self, text="", box=None, selected=None):
        self.text = text
        self.box = box
        self.selected = selected
        self.forced = False

    def wait_for(self, **_kwargs):
        return None

    def click(self, **kwargs):
        self.forced = bool(kwargs.get("force", False))
        if self.selected is not None:
            self.selected[0] = self.text

    def is_visible(self, **_kwargs):
        return True

    def bounding_box(self, **_kwargs):
        return self.box

    def inner_text(self, **_kwargs):
        return self.text


class _Collection:
    def __init__(self, nodes):
        self.nodes = nodes

    def count(self):
        return len(self.nodes)

    def nth(self, index):
        return self.nodes[index]


class _Page:
    url = "https://example.test/login"

    def __init__(self):
        self.selected = [""]
        self.combo = _Node()
        self.option = _Node(
            "active-store",
            {"x": 20, "y": 100, "width": 100, "height": 30},
            self.selected,
        )

    def get_by_role(self, **_kwargs):
        return self.combo

    def evaluate(self, _script):
        return {"width": 800, "height": 600}

    def locator(self, selector):
        if "dropdown:not" in selector:
            return _Collection([self.option])
        if "selection-item" in selector:
            return _Collection([_Node(self.selected[0])])
        return _Collection([])

    def wait_for_timeout(self, _timeout):
        return None

    def title(self):
        return "Login"


class StableViewportSelectTests(unittest.TestCase):
    def test_active_option_uses_force_after_viewport_validation(self):
        page = _Page()
        executor = ViewportSecurePlaywrightExecutor(page, visual_sensor=object())
        result = executor.execute({
            "action": "select_option",
            "parameters": {"role": "combobox", "option_text": ""},
        })
        self.assertTrue(result["success"])
        self.assertTrue(page.option.forced)
        self.assertEqual(page.selected[0], "active-store")


if __name__ == "__main__":
    unittest.main()
