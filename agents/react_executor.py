"""
ReAct 执行器 — 单步内思考-行动多轮闭环

每步执行流程:
  1. 获取页面状态快照
  2. LLM 思考 → 输出动作 JSON
  3. Pydantic 校验 → 不通过则回传错误要求重试（最多2次）
  4. Playwright 执行 → 拿到结构化结果
  5. 结果回传 LLM → 进入下一轮
  6. 满足终止条件退出

终止条件:
  - LLM 输出 finish（步骤目标达成或判定失败）
  - 达到最大轮次上限（默认5）
  - LLM 明确判定目标无法完成
"""
import re, json, time
from playwright.sync_api import Page
from config.settings import settings
from agents.executor_agent import ExecutorAgent
from executor.playwright_exec import PlaywrightExecutor
from utils.action_schema import clean_llm_output, validate_action, get_validation_error
from core.reasoning_engine import StepReasoningState


class ReactExecutor:
    """ReAct 闭环执行器：单步内多轮思考-行动"""

    def __init__(self, page: Page, executor: PlaywrightExecutor = None,
                 agent: ExecutorAgent = None,
                 max_rounds: int = 8, max_self_correct: int = 2):
        self.page = page
        self.executor = executor or PlaywrightExecutor(page)
        self.agent = agent or ExecutorAgent()
        self.max_rounds = max_rounds
        self.max_self_correct = max_self_correct

    def execute_step(self, step_goal: str, perception_capture) -> dict:
        """
        执行单步 ReAct 循环。

        Args:
            step_goal: 步骤目标（自然语言）
            perception_capture: callable(page) -> str  感知函数

        Returns:
            {"success": bool, "rounds": int, "actions": [...], "final_result": str}
        """
        all_actions = []
        round_num = 0
        last_result_desc = "无（首次尝试）"
        step_success = False
        final_msg = ""
        reasoning = StepReasoningState(step_goal, max_rounds=self.max_rounds)

        while round_num < self.max_rounds:
            round_num += 1
            print(f"\n  [REACT] 第{round_num}/{self.max_rounds}轮思考...")

            # 1) 感知
            try:
                page_state = perception_capture(self.page)
            except Exception:
                page_state = "(感知异常)"
            try:
                reasoning.observe(page_state, self.page.url, self.page.title() or "")
            except Exception:
                reasoning.observe(page_state)

            # 2) LLM 决策（含自校正）
            action = self._llm_decide_with_correction(
                step_goal=step_goal,
                page_state=page_state,
                last_result=last_result_desc,
                round_num=round_num,
                history=all_actions[-3:],
                reasoning_state=reasoning.prompt_context(round_num),
            )
            if action is None:
                final_msg = "LLM决策连续失败（自校正耗尽）"
                break

            # 3) 确定性控制器门禁
            if reasoning.repeated_on_same_observation(action):
                result = {
                    "success": False,
                    "error_type": "DUPLICATE_STRATEGY",
                    "message": "相同页面状态下已执行过完全相同的动作",
                }
                reasoning.record(round_num, action, result, self.page.url, self.page.url)
                all_actions.append({"action": action, "result": result})
                last_result_desc = self._format_result_for_llm(result)
                continue

            declared_result = action.get("parameters", {}).get("result", "success")
            if action.get("action") == "finish" and declared_result == "success":
                allowed, evidence = reasoning.can_finish_success()
                if not allowed:
                    result = {
                        "success": False,
                        "error_type": "UNGROUNDED_FINISH",
                        "message": f"拒绝无证据完成: {evidence}",
                    }
                    reasoning.record(round_num, action, result, self.page.url, self.page.url)
                    all_actions.append({"action": action, "result": result})
                    last_result_desc = self._format_result_for_llm(result)
                    continue

            # 4) 执行
            url_before = self.page.url
            result = self.executor.execute(action)
            url_after = self.page.url
            reasoning.record(round_num, action, result, url_before, url_after)
            all_actions.append({"action": action, "result": result})

            # 5) 构建下一轮上下文
            last_result_desc = self._format_result_for_llm(result)

            if action.get("action") == "finish":
                step_success = result.get("success", False) and declared_result == "success"
                final_msg = result.get("message", "")
                break

            if not result.get("success"):
                print(f"  [REACT] 动作失败: {result.get('error_type')} - {result.get('message')[:80]}")
            else:
                print(f"  [REACT] 动作成功: {result.get('message')[:80]}")

        # 摘要
        if round_num >= self.max_rounds and not step_success:
            final_msg = f"达到最大轮次{self.max_rounds}，步骤未完成"

        return {
            "success": step_success,
            "rounds": round_num,
            "actions": all_actions,
            "final_result": final_msg,
        }

    def _llm_decide_with_correction(self, step_goal: str, page_state: str,
                                     last_result: str, round_num: int,
                                     history: list,
                                     reasoning_state: str = "") -> dict | None:
        """LLM决策 + Pydantic自校正（最多2次）"""
        # 构建历史上下文
        history_text = ""
        if history:
            items = []
            for h in history:
                act = h.get("action", {})
                res = h.get("result", {})
                items.append(f"  动作={act.get('action')}, 结果={'成功' if res.get('success') else res.get('error_type','失败')}: {res.get('message','')[:60]}")
            history_text = "\n".join(items)

        # 获取当前页面元信息
        try:
            page_url = self.page.url
            page_title = self.page.title() or ""
        except Exception:
            page_url = ""; page_title = ""

        context = {
            "step_goal": step_goal,
            "page_state": page_state,
            "last_result": last_result,
            "tried_strategies": history_text or "无（首次尝试）",
            "round_num": round_num,
            "max_rounds": self.max_rounds,
            "page_url": page_url,
            "page_title": page_title,
            "reasoning_state": reasoning_state,
        }

        for correction in range(self.max_self_correct + 1):
            try:
                raw_action = self.agent.ask(context)
            except Exception as e:
                print(f"  [LLM] 调用异常: {e}")
                if correction < self.max_self_correct:
                    continue
                return None

            # 清洗
            if isinstance(raw_action, str):
                raw_action = self._parse_json(raw_action)
            if not isinstance(raw_action, dict):
                if correction < self.max_self_correct:
                    context["last_result"] = f"输出格式错误，请输出纯JSON: {str(raw_action)[:100]}"
                    continue
                return None

            # 校验
            validated = validate_action(raw_action)
            if validated:
                return validated

            # 自校正：把错误原因回传
            error_msg = get_validation_error(raw_action)
            print(f"  [VALIDATE] 校验失败: {error_msg[:100]}")
            if correction < self.max_self_correct:
                context["last_result"] = f"动作校验失败({error_msg[:150]})，请修正后重新输出正确JSON动作。"

        return None

    def _format_result_for_llm(self, result: dict) -> str:
        """把结构化执行结果格式化成 LLM 可理解的文本"""
        if result["success"]:
            msg = f"✅ 成功: {result['message']}"
            pc = result.get("page_change", {})
            if pc:
                parts = []
                if pc.get("url_changed"):
                    parts.append(f"URL已变为: {pc.get('new_url','')}")
                if pc.get("toast_text"):
                    parts.append(f"页面提示: {pc['toast_text']}")
                if pc.get("page_title"):
                    parts.append(f"页面标题: {pc['page_title']}")
                if parts:
                    msg += " | " + " | ".join(parts)
            return msg

        ctx = result.get("context", {})
        msg = f"❌ 失败 [{result['error_type']}]: {result['message']}"
        if ctx.get("current_url"):
            msg += f" | 当前URL: {ctx['current_url']}"
        if ctx.get("visible_error_text"):
            msg += f" | 页面可见错误: {ctx['visible_error_text']}"
        return msg

    @staticmethod
    def _parse_json(raw: str) -> dict | None:
        try:
            return json.loads(clean_llm_output(raw))
        except json.JSONDecodeError:
            return None


# ═══════════════════════════════════════════════
#  便捷函数：注入到 TestRunner 的 ReAct 提示
# ═══════════════════════════════════════════════

def build_react_context(step_goal: str, round_num: int, max_rounds: int,
                        last_result: str, page_state: str,
                        tried_strategies: str = "") -> dict:
    """构建 ExecutorAgent.ask() 所需的 context（增强 ReAct 信息）"""
    react_hint = f"""
【ReAct循环状态】
当前是第 {round_num}/{max_rounds} 轮。
上轮执行结果: {last_result}
{tried_strategies if tried_strategies else ''}

【重要提醒】
1. 先输出思考过程（thought字段），再输出动作
2. 如果目标已达成，立即输出 action="finish" result="success"
3. 如果上一轮动作成功且目标达成，不要继续探索
4. 如果多次尝试不同策略仍失败，输出 finish result="fail:原因"
"""
    full_state = react_hint + "\n" + page_state
    return {
        "step_goal": step_goal,
        "last_result": last_result,
        "page_state": full_state,
        "tried_strategies": tried_strategies or "无",
    }
