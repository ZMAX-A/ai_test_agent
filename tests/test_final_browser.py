import unittest

from config.settings import settings
from tests.test_web_agent_auth import _Page, _policy
from web_agent.final_browser import FinalPolicyBrowserExecutor


class _KeywordOnlyPage(_Page):
    def __init__(self):
        super().__init__()
        self.wait_arg = None

    def wait_for_function(self, _expression, *, arg=None, **_kwargs):
        self.wait_arg = arg
        return None


class FinalBrowserTests(unittest.TestCase):
    def test_navigation_wait_uses_keyword_only_arg(self):
        page = _KeywordOnlyPage()
        page.values.update({
            "username": settings.LOGIN_USERNAME,
            "password": settings.LOGIN_PASSWORD,
            "store": "zwf1",
        })
        executor = FinalPolicyBrowserExecutor(
            page, visual_sensor=object(), auth_policy=_policy()
        )
        result = executor.execute({
            "action": "click",
            "parameters": {"role": "button", "name": "登录"},
        })
        self.assertTrue(result["success"])
        self.assertEqual(page.wait_arg, "/login")
        self.assertTrue(result["page_change"]["url_changed"])


if __name__ == "__main__":
    unittest.main()
