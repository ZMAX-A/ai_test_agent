import os
import unittest
from unittest.mock import patch

from agents.strict_verifier_agent import StrictVerifierAgent
from case.case_generator import generate_standard_case
from executor.action_validator import validate_action
from loader.excel_loader import load_excel_cases
from runner.generic_runner import AssertionExecutor, StepExecutor
from tests.test_web_agent_auth import _Locator, _Page, _policy
from web_agent.browser import PolicyAwareBrowserExecutor
from web_agent.commands import run_excel
from web_agent.reasoning import CredentialAwareReasoningState


class _RejectSubmitLocator(_Locator):
    def click(self, **_kwargs):
        self.page.errors = ["登录失败，请重试！"]


class _RejectPage(_Page):
    def locator(self, selector):
        if selector == "#submit":
            return _RejectSubmitLocator(self, "submit")
        return super().locator(selector)


class _ValueLocator:
    def __init__(self, value=""):
        self.value = value
        self.first = self

    def input_value(self, **_kwargs):
        return self.value

    def count(self):
        return 0

    def nth(self, _index):
        return self


class _EmptyLoginPage:
    url = "https://example.test/login"

    def title(self):
        return "登录"

    def locator(self, selector):
        if selector in ("input[type='text']", "input[type='password']"):
            return _ValueLocator("")
        return _ValueLocator("")


class _InputField:
    def __init__(self):
        self.first = self
        self.value = ""

    def wait_for(self, **_kwargs):
        return None

    def fill(self, value):
        self.value = value


class _InputPage:
    def __init__(self):
        self.field = _InputField()

    def locator(self, _selector):
        return self.field


class _BodyLocator:
    def __init__(self, text):
        self.text = text
        self.first = self

    def inner_text(self, **_kwargs):
        return self.text


class _AssertionPage:
    def __init__(self, url, body):
        self.url = url
        self.body = body

    def locator(self, selector):
        return _BodyLocator(self.body if selector == "body" else "")

    def wait_for_load_state(self, *_args, **_kwargs):
        return None


class _RecordingRunner:
    def __init__(self):
        self.calls = []

    def run_case(self, **kwargs):
        self.calls.append(kwargs)
        return {"success": True, "collaboration": {}}


class NegativeLoginFlowTests(unittest.TestCase):
    def test_curriculum_uses_named_invalid_credentials_without_literal_suffix(self):
        cases = {
            case["case_id"]: case
            for case in load_excel_cases("test_cases/webagent_test_case.xlsx")
        }
        first_steps = cases["TC-LOGIN-001"]["_runner_steps"]
        second_steps = cases["TC-LOGIN-002"]["_runner_steps"]
        first_goal = next(
            step["goal"] for step in first_steps if "invalid.username" in step["goal"]
        )
        second_goal = next(
            step["goal"] for step in second_steps if "invalid.password" in step["goal"]
        )
        self.assertEqual(
            first_goal, "在账号输入框输入 {{credential.invalid.username}}"
        )
        self.assertEqual(second_goal, "输入 {{credential.invalid.password}}")

        self.assertEqual(
            [step["goal"] for step in second_steps[:3]],
            ["输入 {{credential.username}}", "输入 {{credential.password}}", "选择门店"],
        )
    def test_explore_filters_curriculum_cases_and_preserves_source_ids(self):
        runner = _RecordingRunner()
        outputs = run_excel(
            "test_cases/webagent_test_case.xlsx",
            True,
            runner_factory=lambda _headless: runner,
            case_ids=("TC-LOGIN-001", "TC-LOGIN-007"),
        )
        self.assertEqual(len(outputs), 2)
        self.assertEqual(
            [call["source_case_id"] for call in runner.calls],
            ["TC-LOGIN-001", "TC-LOGIN-007"],
        )
        self.assertIsInstance(
            runner.calls[0]["steps"][-1]["success_criteria"], dict
        )

    def test_reasoning_selects_invalid_credential_and_negative_submit_contract(self):
        state = CredentialAwareReasoningState(
            "输入 {{credential.invalid.password}}"
        )
        state.observe("password", "https://example.test/login", "登录")
        action = state.deterministic_action()
        self.assertEqual(action["parameters"]["credential_key"], "invalid")
        self.assertEqual(
            action["parameters"]["value"], "{{credential.invalid.password}}"
        )

        submit = CredentialAwareReasoningState(
            "点击登录", {"text_contains": ["登录失败"]}
        )
        submit.observe("button", "https://example.test/login", "登录")
        self.assertTrue(
            submit.deterministic_action()["parameters"]["expect_failure"]
        )

    def test_validator_allows_only_explicit_negative_login_metadata(self):
        valid, _ = validate_action({
            "action": "fill",
            "parameters": {
                "role": "textbox",
                "value": "{{credential.invalid.username}}",
                "credential_key": "invalid",
            },
        })
        self.assertTrue(valid)
        invalid, _ = validate_action({
            "action": "fill",
            "parameters": {
                "role": "textbox",
                "value": "x",
                "credential_key": "production",
            },
        })
        self.assertFalse(invalid)

    def test_executor_uses_named_invalid_credential_and_accepts_visible_rejection(self):
        page = _RejectPage()
        executor = PolicyAwareBrowserExecutor(
            page, visual_sensor=object(), auth_policy=_policy()
        )
        with patch.dict(os.environ, {
            "CRED_INVALID_USERNAME": "invalid-user",
            "CRED_INVALID_PASSWORD": "invalid-pass",
        }, clear=False):
            filled = executor.execute({
                "action": "fill",
                "parameters": {
                    "role": "textbox",
                    "index": 0,
                    "value": "invalid-user",
                    "credential_key": "invalid",
                },
            })
            rejected = executor.execute({
                "action": "click",
                "parameters": {
                    "role": "button",
                    "name": "登录",
                    "expect_failure": True,
                },
            })
        self.assertTrue(filled["success"])
        self.assertEqual(page.values["username"], "invalid-user")
        self.assertTrue(rejected["success"])
        self.assertIn("登录失败", rejected["page_change"]["toast_text"])

    def test_empty_login_state_is_independently_verified(self):
        result = StrictVerifierAgent().verify(
            _EmptyLoginPage(), "不输入账号和密码"
        )
        self.assertTrue(result.passed)
        self.assertEqual(len(result.evidence), 2)

    def test_generated_negative_case_has_password_locator_and_strict_assertion(self):
        trace = [
            {
                "goal": "输入 {{credential.invalid.password}}",
                "all_actions": [{
                    "action": "fill",
                    "parameters": {
                        "role": "textbox",
                        "index": 1,
                        "value": "{{credential.invalid.password}}",
                    },
                }],
                "css_selector": "input[type='text']:nth-of-type(2)",
                "page_url": "https://example.test/login",
            },
            {
                "goal": "点击登录",
                "all_actions": [{
                    "action": "click",
                    "parameters": {"role": "button", "name": "登录"},
                }],
                "page_url": "https://example.test/login",
            },
        ]
        case = generate_standard_case(
            trace,
            "TC-LOGIN-002",
            "登录失败-错误密码",
            module="账号登录",
            preconditions="打开登录页面",
            expected={"text_contains": ["登录失败", "请重试！"]},
        )
        self.assertIn("input[type='password']", case["元素定位器"])
        self.assertEqual(case["断言类型"], "text_contains_all")
        self.assertEqual(case["验证点"], "登录失败 | 请重试！")
        self.assertIn("{{credential.invalid.password}}", case["输入数据"])

    def test_regression_resolves_credential_references_and_strict_assertions(self):
        page = _InputPage()
        with patch.dict(
            os.environ, {"CRED_INVALID_PASSWORD": "invalid-pass"}, clear=False
        ):
            StepExecutor(page).execute(
                "input[type='password']",
                "input",
                "{{credential.invalid.password}}",
            )
        self.assertEqual(page.field.value, "invalid-pass")

        assertion_page = _AssertionPage(
            "https://example.test/", "登录失败，请重试！"
        )
        AssertionExecutor(assertion_page).assert_by_type(
            "text_contains_all", "登录失败 | 请重试！"
        )
        AssertionExecutor(assertion_page).assert_by_type(
            "url_not_contains", "/login"
        )


if __name__ == "__main__":
    unittest.main()
