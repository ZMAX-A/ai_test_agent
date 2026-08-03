"""多 Agent v2 的协作恢复策略。"""

from core.reasoning_engine import StepReasoningState


class CollaborativeStepReasoningState(StepReasoningState):
    """在基础推理上增加跨动作的登录阻挡恢复。"""

    def _login_recovery_action(self) -> dict | None:
        if "/login" not in self.current_url:
            return None
        goto_attempts = [attempt for attempt in self.attempts if attempt.action == "goto"]
        if not goto_attempts:
            return None

        last_goto_round = goto_attempts[-1].round_num
        later_successes = [
            attempt for attempt in self.attempts
            if attempt.round_num > last_goto_round and attempt.success
        ]
        selected = any(attempt.action == "select_option" for attempt in later_successes)
        clicked_login = any(attempt.action == "click" for attempt in later_successes)

        if not selected and any(
            keyword in self.current_observation.lower()
            for keyword in ("combobox", "请选择门店", "请选择机构")
        ):
            return {
                "thought": "Coordinator识别到目标导航被登录页拦截，先选择门店/机构",
                "action": "select_option",
                "parameters": {"role": "combobox", "option_text": ""},
            }
        if selected and not clicked_login:
            return {
                "thought": "Coordinator已完成门店选择，重新提交登录以解除导航阻挡",
                "action": "click",
                "parameters": {"role": "button", "name": "登 录"},
            }
        return None

    def deterministic_action(self) -> dict | None:
        return self._login_recovery_action() or super().deterministic_action()
