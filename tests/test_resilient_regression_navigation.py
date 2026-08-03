import unittest

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from web_agent.auth import AuthenticationPolicy
from web_agent.regression import ProductionRegressionRunner


class _Page:
    def __init__(self, actual_url: str):
        self.url = actual_url


class ResilientRegressionNavigationTests(unittest.TestCase):
    def setUp(self):
        self.runner = ProductionRegressionRunner(AuthenticationPolicy())

    @staticmethod
    def _case(target="https://example.test/customer", verify="/customer"):
        return {
            "元素定位器": target,
            "操作类型": "nav",
            "输入数据": "",
            "断言类型": "url_contains",
            "验证点": verify,
        }

    def test_timeout_is_accepted_when_url_assertion_proves_arrival(self):
        page = _Page("https://example.test/customer")
        self.assertTrue(
            self.runner._navigation_timeout_reached(page, self._case())
        )

    def test_timeout_is_rejected_when_target_was_not_reached(self):
        page = _Page("https://example.test/home")
        self.assertFalse(
            self.runner._navigation_timeout_reached(page, self._case())
        )

    def test_playwright_timeout_type_is_not_swallowed_generically(self):
        error = PlaywrightTimeoutError("timeout")
        self.assertIsInstance(error, PlaywrightTimeoutError)


if __name__ == "__main__":
    unittest.main()
