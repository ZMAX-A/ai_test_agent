"""统一认证恢复策略。

兼容原有“导航被登录页拦截”恢复，并增加显式登录提交后的表单阻挡恢复。
"""

import json

from config.settings import settings
from core.collaborative_reasoning import CollaborativeStepReasoningState


class AuthenticatedCollaborativeStepReasoningState(CollaborativeStepReasoningState):
    def _explicit_login_submit_recovery(self) -> dict | None:
        goal_text = f"{self.goal} {self.success_criteria}"
        if "/login" not in self.current_url or not all(k in goal_text for k in ("点击", "登录")):
            return None

        successful = [attempt for attempt in self.attempts if attempt.success]
        clicks = [attempt for attempt in successful if attempt.action == "click"]
        if len(clicks) != 1:
            return None
        later = [attempt for attempt in successful if attempt.round_num > clicks[0].round_num]
        selected = any(attempt.action == "select_option" for attempt in later)

        if not selected and any(
            keyword in self.current_observation.lower()
            for keyword in ("combobox", "请选择门店", "请选择机构")
        ):
            return {
                "thought": "登录提交后出现门店/机构前置条件，先完成必填选择",
                "action": "select_option",
                "parameters": {"role": "combobox", "option_text": ""},
            }
        if selected:
            return {
                "thought": "门店/机构前置条件已满足，重新提交登录并观察URL变化",
                "action": "click",
                "parameters": {"role": "button", "name": "登 录"},
            }
        return None

    def _navigation_login_recovery(self) -> dict | None:
        if "/login" not in self.current_url:
            return None
        goto_attempts = [attempt for attempt in self.attempts if attempt.action == "goto"]
        if not goto_attempts:
            return None
        if not settings.LOGIN_USERNAME or not settings.LOGIN_PASSWORD:
            return super()._login_recovery_action()

        last_goto_round = goto_attempts[-1].round_num
        later = [
            attempt for attempt in self.attempts
            if attempt.round_num > last_goto_round and attempt.success
        ]
        filled_indexes = set()
        for attempt in later:
            if attempt.action != "fill":
                continue
            try:
                payload = json.loads(attempt.signature)
                filled_indexes.add(payload.get("parameters", {}).get("index"))
            except Exception:
                continue

        if 0 not in filled_indexes:
            return {
                "thought": "重建被登录重定向清空的账号",
                "action": "fill",
                "parameters": {"role": "textbox", "index": 0, "value": settings.LOGIN_USERNAME},
            }
        if 1 not in filled_indexes:
            return {
                "thought": "重建被登录重定向清空的密码",
                "action": "fill",
                "parameters": {"role": "textbox", "index": 1, "value": settings.LOGIN_PASSWORD},
            }
        if not any(attempt.action == "select_option" for attempt in later):
            return {
                "thought": "选择登录所需的门店/机构",
                "action": "select_option",
                "parameters": {"role": "combobox", "option_text": ""},
            }
        if not any(attempt.action == "click" for attempt in later):
            return {
                "thought": "提交完整登录信息以解除导航阻挡",
                "action": "click",
                "parameters": {"role": "button", "name": "登 录"},
            }
        return None

    def _login_recovery_action(self) -> dict | None:
        return self._explicit_login_submit_recovery() or self._navigation_login_recovery()
