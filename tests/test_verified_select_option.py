import unittest

from executor.playwright_exec import PlaywrightExecutor


class _Node:
    def __init__(self, text="", visible=True, on_click=None):
        self.text = text
        self.visible = visible
        self.on_click = on_click

    def wait_for(self, **_kwargs):
        return None

    def click(self, **_kwargs):
        if self.on_click:
            self.on_click()

    def is_visible(self, **_kwargs):
        return self.visible

    def inner_text(self, **_kwargs):
        return self.text

    def count(self):
        return 1

    def nth(self, _index):
        return self


class _Collection:
    def __init__(self, nodes):
        self.nodes = nodes

    def count(self):
        return len(self.nodes)

    def nth(self, index):
        return self.nodes[index]


class _Page:
    def __init__(self):
        self.url = "https://example.test/login"
        self.selected = ""
        self.combo = _Node()
        self.option = _Node("测试门店", on_click=lambda: setattr(self, "selected", "测试门店"))

    def get_by_role(self, **_kwargs):
        return self.combo

    def locator(self, selector):
        if "item-option:not" in selector:
            return _Collection([self.option])
        if "selection-item" in selector:
            return _Collection([_Node(self.selected)] if self.selected else [])
        return _Collection([])

    def wait_for_timeout(self, _timeout):
        return None

    def title(self):
        return "登录"


class _Visual:
    pass


class VerifiedSelectOptionTests(unittest.TestCase):
    def test_select_option_clicks_and_reads_selected_label(self):
        page = _Page()
        executor = PlaywrightExecutor(page, visual_sensor=_Visual())
        result = executor.execute({
            "action": "select_option",
            "parameters": {"role": "combobox", "option_text": ""},
        })
        self.assertTrue(result["success"])
        self.assertEqual(page.selected, "测试门店")
        self.assertIn("回读确认", result["message"])


if __name__ == "__main__":
    unittest.main()
