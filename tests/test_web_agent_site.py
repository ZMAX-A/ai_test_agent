import unittest

from web_agent.auth import AuthenticationPolicy
from web_agent.reasoning import CredentialAwareReasoningState
from web_agent.site import site_dependencies
from web_agent.stable_browser import StablePolicyBrowserExecutor


class _Keyboard:
    def __init__(self):
        self.keys = []

    def press(self, key):
        self.keys.append(key)


class _Page:
    def __init__(self):
        self.keyboard = _Keyboard()
        self.waits = []

    def wait_for_timeout(self, timeout):
        self.waits.append(timeout)


class _Base:
    def _submit_and_wait(self):
        return {"success": True}


class _Executor(StablePolicyBrowserExecutor, _Base):
    def __init__(self, page):
        self.page = page


class WebAgentSiteTests(unittest.TestCase):
    def test_site_dependencies_keep_reasoning_and_use_stable_browser(self):
        dependencies = site_dependencies(AuthenticationPolicy())
        self.assertIs(
            dependencies.reasoning_factory,
            CredentialAwareReasoningState,
        )

        class Page:
            url = "https://example.test/"

            def title(self):
                return "Home"

        browser = dependencies.browser_executor_factory(Page(), object())
        self.assertIsInstance(browser, StablePolicyBrowserExecutor)

    def test_submit_closes_transient_portal_first(self):
        page = _Page()
        executor = _Executor(page)
        result = executor._submit_and_wait()
        self.assertTrue(result["success"])
        self.assertEqual(page.keyboard.keys, ["Escape"])
        self.assertEqual(page.waits, [300])


if __name__ == "__main__":
    unittest.main()
