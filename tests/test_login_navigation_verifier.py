import unittest

from agents.strict_verifier_agent import StrictVerifierAgent


class _Page:
    url = "https://example.test/"

    def title(self):
        return "Home"


class LoginNavigationVerifierTests(unittest.TestCase):
    def test_current_url_proves_login_navigation(self):
        result = StrictVerifierAgent().verify(
            _Page(),
            "点击登录按钮",
            action={"action": "click", "parameters": {"role": "button"}},
            action_result={"success": True, "page_change": {}},
        )
        self.assertTrue(result.passed)
        self.assertIn("离开登录页", result.evidence[0])


if __name__ == "__main__":
    unittest.main()
