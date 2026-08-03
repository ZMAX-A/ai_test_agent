import unittest

from case.case_generator import generate_standard_case
from runner.generic_runner import (
    AssertionExecutor,
    StepExecutor,
    _precondition_mode,
    _split_steps,
)
from core.reasoning_engine import StepReasoningState, normalize_plan
from agents.react_executor import ReactExecutor


class _TitlePage:
    def __init__(self, title):
        self._title = title

    def title(self):
        return self._title


class _ReactPage(_TitlePage):
    url = "https://example.test"


class _SequenceAgent:
    def __init__(self, actions):
        self.actions = iter(actions)

    def ask(self, _context):
        return next(self.actions)


class _FakeExecutor:
    def execute(self, action):
        return {
            "success": True,
            "error_type": "",
            "message": f"{action['action']} ok",
            "page_change": {},
            "context": {},
        }


class CaseContractTests(unittest.TestCase):
    def test_plan_normalization_keeps_success_criteria_and_deduplicates(self):
        plan = normalize_plan({"steps": [
            {"goal": "点击登录", "assert": "进入首页"},
            {"goal": "点击登录", "success_criteria": "重复项"},
            "验证首页",
        ]})
        self.assertEqual(len(plan), 2)
        self.assertEqual(plan[0]["success_criteria"], "进入首页")
        self.assertEqual(plan[1]["step"], 2)

    def test_reasoning_finish_requires_evidence(self):
        state = StepReasoningState("在搜索框输入 Codex")
        state.observe("textbox 搜索框", "https://example.test", "首页")
        allowed, _ = state.can_finish_success()
        self.assertFalse(allowed)

        action = {"action": "fill", "parameters": {"role": "textbox", "value": "Codex"}}
        state.record(1, action, {"success": True, "message": "输入成功"},
                     "https://example.test", "https://example.test")
        allowed, evidence = state.can_finish_success()
        self.assertTrue(allowed)
        self.assertIn("输入动作", evidence)

    def test_reasoning_accepts_direct_url_evidence(self):
        state = StepReasoningState("进入顾客档案页面 /customer")
        state.observe("heading 顾客档案", "https://example.test/customer", "顾客档案")
        self.assertTrue(state.can_finish_success()[0])

    def test_successful_navigation_updates_completion_url(self):
        state = StepReasoningState("进入顾客档案页面 /customer")
        state.observe("link 顾客档案", "https://example.test/home", "首页")
        action = {"action": "goto", "parameters": {"url": "https://example.test/customer"}}
        state.record(1, action, {"success": True, "message": "导航成功"},
                     "https://example.test/home", "https://example.test/customer")
        self.assertTrue(state.can_finish_success()[0])

    def test_mixed_locator_strategies_are_rejected(self):
        from executor.action_validator import validate_action
        valid, message = validate_action({
            "action": "fill",
            "parameters": {"role": "textbox", "som_index": 2, "value": "x"},
        })
        self.assertFalse(valid)
        self.assertIn("二选一", message)

    def test_explicit_path_produces_deterministic_navigation(self):
        state = StepReasoningState("进入顾客档案页面，可直接访问 /customer")
        state.observe("heading 首页", "https://example.test/home", "首页")
        action = state.deterministic_action()
        self.assertEqual(action["action"], "goto")
        self.assertEqual(action["parameters"]["url"], "https://example.test/customer")

    def test_goal_ordinal_repairs_ambiguous_role_locator(self):
        state = StepReasoningState("在用户名输入框(第1个)输入 demo")
        action, notes = state.repair_action({
            "action": "fill",
            "parameters": {"role": "textbox", "value": "demo"},
        })
        self.assertEqual(action["parameters"]["index"], 0)
        self.assertTrue(notes)

    def test_success_criteria_is_stricter_than_action_success(self):
        state = StepReasoningState("点击登录", success_criteria="页面显示用户首页")
        state.observe("button 登录", "https://example.test/login", "登录")
        action = {"action": "click", "parameters": {"role": "button", "name": "登录"}}
        state.record(1, action, {"success": True, "message": "点击成功"},
                     "https://example.test/login", "https://example.test/login")
        self.assertFalse(state.can_finish_success()[0])

        state.observe("heading 用户首页", "https://example.test/home", "用户首页")
        self.assertTrue(state.can_finish_success()[0])

    def test_reasoning_blocks_duplicate_only_on_same_observation(self):
        state = StepReasoningState("点击登录")
        action = {"action": "click", "parameters": {"role": "button", "name": "登录"}}
        state.observe("button 登录", "https://example.test/login", "登录")
        state.record(1, action, {"success": False, "error_type": "NOT_VISIBLE", "message": "失败"})
        self.assertTrue(state.repeated_on_same_observation(action))

        state.observe("dialog 提示\nbutton 登录", "https://example.test/login", "登录")
        self.assertFalse(state.repeated_on_same_observation(action))

    def test_react_executor_rejects_ungrounded_finish(self):
        agent = _SequenceAgent([
            {"action": "finish", "parameters": {"result": "success"}},
            {"action": "fill", "parameters": {"role": "textbox", "value": "Codex"}},
            {"action": "finish", "parameters": {"result": "success"}},
        ])
        react = ReactExecutor(
            _ReactPage("首页"),
            executor=_FakeExecutor(),
            agent=agent,
            max_rounds=3,
        )
        result = react.execute_step("在搜索框输入 Codex", lambda _page: "textbox 搜索框")
        self.assertTrue(result["success"])
        self.assertEqual(result["rounds"], 3)
        self.assertEqual(result["actions"][0]["result"]["error_type"], "UNGROUNDED_FINISH")

    def test_generator_uses_store_header_names(self):
        trace = [
            {
                "goal": "输入关键词",
                "all_actions": [{
                    "action": "fill",
                    "parameters": {"role": "textbox", "value": "Codex"},
                }],
                "css_selector": "input, textarea",
            },
            {
                "goal": "点击搜索",
                "all_actions": [{
                    "action": "click",
                    "parameters": {"role": "button", "name": "搜索"},
                }],
                "css_selector": "button:has-text('搜索')",
            },
        ]

        case = generate_standard_case(trace, "TC001", "搜索", module="搜索功能")

        self.assertEqual(case["测试场景"], "搜索")
        self.assertIn("输入关键词", case["操作步骤"])
        self.assertEqual(case["期望结果"], "成功")
        self.assertEqual(case["操作类型"], "input | click")
        self.assertEqual(
            _split_steps(case["元素定位器"]),
            ["input, textarea", "button:has-text('搜索')"],
        )
        self.assertNotIn("测试名称", case)
        self.assertNotIn("步骤描述", case)
        self.assertNotIn("预期结果", case)

    def test_step_parser_supports_new_and_legacy_formats(self):
        self.assertEqual(_split_steps("#a | input, textarea"), ["#a", "input, textarea"])
        self.assertEqual(_split_steps("input,click"), ["input", "click"])

    def test_precondition_classification_is_unambiguous(self):
        self.assertEqual(_precondition_mode("打开登录页面"), "open_login")
        self.assertEqual(_precondition_mode("未登录"), "open_login")
        self.assertEqual(_precondition_mode("已登录"), "auto_login")
        self.assertEqual(_precondition_mode("需配置 .env 登录凭证"), "auto_login")

    def test_unknown_action_and_assertion_fail_fast(self):
        with self.assertRaisesRegex(ValueError, "不支持的操作类型"):
            StepExecutor(object()).execute("", "unknown", "")
        with self.assertRaisesRegex(ValueError, "不支持的断言类型"):
            AssertionExecutor(object()).assert_by_type("unknown", "value")

    def test_title_contains(self):
        executor = AssertionExecutor(_TitlePage("AI 测试平台"))
        self.assertTrue(executor._title_contains("测试平台"))
        with self.assertRaises(AssertionError):
            executor._title_contains("不存在")


if __name__ == "__main__":
    unittest.main()
