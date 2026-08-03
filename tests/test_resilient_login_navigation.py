import unittest

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from web_agent.auth import AuthenticationPolicy
from web_agent.regression import ProductionRegressionRunner


class _Locator:
    def __init__(self, visible=True):
        self.first = self
        self.visible = visible

    def wait_for(self, **_kwargs):
        if not self.visible:
            raise PlaywrightTimeoutError("not visible")


class _Page:
    def __init__(self, url, visible=True, goto_timeout=True):
        self.url = url
        self.visible = visible
        self.goto_timeout = goto_timeout

    def goto(self, *_args, **_kwargs):
        if self.goto_timeout:
            raise PlaywrightTimeoutError("load event timeout")

    def locator(self, _selector):
        return _Locator(self.visible)


class ResilientLoginNavigationTests(unittest.TestCase):
    def setUp(self):
        policy = AuthenticationPolicy(
            login_path="/login",
            username_selector="#username",
            password_selector="#password",
        )
        self.runner = ProductionRegressionRunner(policy)

    def test_login_timeout_is_accepted_when_required_fields_are_visible(self):
        page = _Page("https://example.test/login", visible=True)
        self.runner._open_login_page(page, page.url)

    def test_login_timeout_is_rejected_on_another_page(self):
        page = _Page("https://example.test/home", visible=True)
        with self.assertRaises(PlaywrightTimeoutError):
            self.runner._open_login_page(page, "https://example.test/login")

    def test_login_timeout_is_rejected_when_fields_are_not_visible(self):
        page = _Page("https://example.test/login", visible=False)
        with self.assertRaises(PlaywrightTimeoutError):
            self.runner._open_login_page(page, page.url)

    def test_fields_are_required_even_when_navigation_succeeds(self):
        page = _Page(
            "https://example.test/login", visible=False, goto_timeout=False
        )
        with self.assertRaises(PlaywrightTimeoutError):
            self.runner._open_login_page(page, page.url)


if __name__ == "__main__":
    unittest.main()
