import unittest

from executor.viewport_secure_playwright_exec import ViewportSecurePlaywrightExecutor
from runner.unified_smart_runner import UnifiedSmartRunner


class _Node:
    def __init__(self, text="", box=None, selected=None):
        self.text = text
        self.box = box
        self.selected = selected

    def wait_for(self, **_kwargs):
        return None

    def click(self, **_kwargs):
        if self.selected is not None:
            self.selected[0] = self.text

    def scroll_into_view_if_needed(self, **_kwargs):
        return None

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
        self.combo = _Node(box={"x": 10, "y": 10, "width": 50, "height": 20})
        self.offscreen = _Node(
            "stale-store",
            {"x": 20, "y": 900, "width": 100, "height": 30},
            self.selected,
        )
        self.active = _Node(
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
            return _Collection([self.offscreen, self.active])
        if "selection-item" in selector:
            return _Collection([_Node(self.selected[0])])
        return _Collection([])

    def wait_for_timeout(self, _timeout):
        return None

    def title(self):
        return "Login"


class ViewportSelectTests(unittest.TestCase):
    def test_offscreen_portal_is_skipped(self):
        page = _Page()
        executor = ViewportSecurePlaywrightExecutor(page, visual_sensor=object())
        result = executor.execute({
            "action": "select_option",
            "parameters": {"role": "combobox", "option_text": ""},
        })
        self.assertTrue(result["success"])
        self.assertEqual(page.selected[0], "active-store")

    def test_unified_runner_binds_viewport_executor(self):
        source_globals = UnifiedSmartRunner.run_case.__globals__
        self.assertIs(
            source_globals["SecurePlaywrightExecutor"],
            ViewportSecurePlaywrightExecutor,
        )


if __name__ == "__main__":
    unittest.main()
