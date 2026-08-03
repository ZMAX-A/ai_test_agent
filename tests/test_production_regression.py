import unittest

from web_agent.auth import AuthenticationPolicy
from web_agent.regression import ProductionRegressionRunner


class _ResultExecutor:
    instances = []

    def __init__(self, page, **_kwargs):
        self.page = page
        self.actions = []
        self.instances.append(self)

    def execute(self, action):
        self.actions.append(action)
        return {"success": True, "error_type": "", "message": "ok"}


class _Notice:
    first = None

    def __init__(self):
        self.first = self

    def is_visible(self, **_kwargs):
        return False

class _ReadyLocator:
    first = None

    def __init__(self):
        self.first = self

    def wait_for(self, **_kwargs):
        return None


class _Page:
    def __init__(self):
        self.gotos = []
        self.waits = []

    def goto(self, url, **_kwargs):
        self.gotos.append(url)

    def wait_for_timeout(self, timeout):
        self.waits.append(timeout)

    def locator(self, _selector):
        return _ReadyLocator()

    def get_by_text(self, _text):
        return _Notice()


class ProductionRegressionTests(unittest.TestCase):
    def test_auto_login_uses_production_executor_actions(self):
        _ResultExecutor.instances.clear()
        runner = ProductionRegressionRunner(
            AuthenticationPolicy(), executor_factory=_ResultExecutor
        )
        page = _Page()
        runner._handle_preconditions(
            page, "已登录", "https://example.test/login"
        )
        actions = _ResultExecutor.instances[-1].actions
        self.assertEqual(
            [action["action"] for action in actions],
            ["fill", "fill", "select_option", "click"],
        )
        self.assertEqual(page.gotos, ["https://example.test/login"])


if __name__ == "__main__":
    unittest.main()
