import unittest

from agents.strict_verifier_agent import StrictVerifierAgent


class _Locator:
    def __init__(self, text="", visible=True):
        self.text = text
        self.visible = visible

    def inner_text(self, timeout=0):
        return self.text

    def is_visible(self, timeout=0):
        return self.visible

    def nth(self, _index):
        return self


class _Page:
    def __init__(self, url="https://example.test/customer", title="顾客档案", body="顾客档案"):
        self.url = url
        self._title = title
        self.body = body

    def title(self):
        return self._title

    def locator(self, selector):
        return _Locator(self.body, True)

    def get_by_role(self, **_kwargs):
        return _Locator("顾客档案", True)


class _Collection:
    def __init__(self, nodes):
        self.nodes = nodes

    def count(self):
        return len(self.nodes)

    def nth(self, index):
        return self.nodes[index]


class _SelectPage(_Page):
    def __init__(self, selected_text):
        super().__init__(url="https://example.test/login", title="登录")
        self.selected_text = selected_text

    def locator(self, selector):
        if "selection-item" in selector:
            nodes = [_Locator(self.selected_text, True)] if self.selected_text else []
            return _Collection(nodes)
        return _Collection([])


class StrictVerifierTests(unittest.TestCase):
    def test_typed_contract_requires_all_rules(self):
        criteria = '{"url_contains":"/customer","text_contains":"顾客档案"}'
        result = StrictVerifierAgent().verify(_Page(), "进入顾客档案", criteria)
        self.assertTrue(result.passed)
        self.assertEqual(len(result.evidence), 2)

    def test_typed_contract_reports_partial_failure(self):
        criteria = '{"url_contains":"/customer","text_contains":"订单中心"}'
        result = StrictVerifierAgent().verify(_Page(), "进入顾客档案", criteria)
        self.assertFalse(result.passed)
        self.assertIn("页面文本缺少", result.reason)

    def test_click_without_observable_change_is_not_success(self):
        result = StrictVerifierAgent().verify(
            _Page(),
            "点击保存按钮",
            action={"action": "click", "parameters": {"role": "button"}},
            action_result={"success": True, "page_change": {}},
        )
        self.assertFalse(result.passed)
        self.assertIn("没有观察到", result.reason)

    def test_click_with_url_change_is_accepted(self):
        result = StrictVerifierAgent().verify(
            _Page(),
            "点击登录按钮",
            action={"action": "click", "parameters": {"role": "button"}},
            action_result={"success": True, "page_change": {"url_changed": True}},
        )
        self.assertTrue(result.passed)
        self.assertIn("URL", result.evidence[0])

    def test_select_with_visible_nonempty_readback_is_accepted(self):
        result = StrictVerifierAgent().verify(
            _SelectPage("测试门店"),
            "选择门店",
            action={"action": "select_option", "parameters": {}},
            action_result={"success": True, "page_change": {}},
        )
        self.assertTrue(result.passed)
        self.assertIn("回读", result.evidence[0])

    def test_select_readback_must_match_requested_option(self):
        result = StrictVerifierAgent().verify(
            _SelectPage("other"),
            "\u9009\u62e9\u95e8\u5e97",
            action={
                "action": "select_option",
                "parameters": {"option_text": "requested"},
            },
            action_result={"success": True, "page_change": {}},
        )
        self.assertFalse(result.passed)

    def test_select_without_readback_remains_rejected(self):
        result = StrictVerifierAgent().verify(
            _SelectPage(""),
            "选择门店",
            action={"action": "select_option", "parameters": {}},
            action_result={"success": True, "page_change": {}},
        )
        self.assertFalse(result.passed)

    def test_typed_navigation_requires_observed_url_change(self):
        criteria = {"url_changed": True, "text_contains": ["顾客档案"]}
        before = StrictVerifierAgent().verify(
            _Page(), "跳转到顾客档案", criteria,
            action_result=None,
        )
        after = StrictVerifierAgent().verify(
            _Page(), "跳转到顾客档案", criteria,
            action_result={"success": True, "page_change": {"url_changed": True}},
        )
        self.assertFalse(before.passed)
        self.assertTrue(after.passed)
        self.assertTrue(any("URL发生变化" in item for item in after.evidence))


if __name__ == "__main__":
    unittest.main()
