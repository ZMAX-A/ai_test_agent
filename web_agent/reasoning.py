"""Production reasoning policies for deterministic high-risk actions."""

from __future__ import annotations

import re

from core.authenticated_collaborative_reasoning import (
    AuthenticatedCollaborativeStepReasoningState,
)


class CredentialAwareReasoningState(
    AuthenticatedCollaborativeStepReasoningState
):
    """Keep credential values entirely outside model decision-making."""

    def _credential_action(self) -> dict | None:
        if "/login" not in str(self.current_url):
            return None
        contract = str(self.goal or "")
        normalized = contract.replace(" ", "")
        is_input = any(token in normalized for token in ("输入", "填入", "填写"))
        if not is_input:
            return None

        if (
            "{{credential.invalid.username}}" in contract
            or (
                "错误" in normalized
                and any(token in normalized for token in ("用户名", "账号", "账户名"))
            )
        ):
            return {
                "thought": "Coordinator使用命名测试凭据填写无效用户名",
                "action": "fill",
                "parameters": {
                    "role": "textbox",
                    "index": 0,
                    "value": "{{credential.invalid.username}}",
                    "credential_key": "invalid",
                },
            }
        if (
            "{{credential.invalid.password}}" in contract
            or ("错误" in normalized and "密码" in normalized)
        ):
            return {
                "thought": "Coordinator使用命名测试凭据填写无效密码",
                "action": "fill",
                "parameters": {
                    "role": "textbox",
                    "index": 1,
                    "value": "{{credential.invalid.password}}",
                    "credential_key": "invalid",
                },
            }
        if (
            "{{credential.username}}" in contract
            or any(token in normalized for token in ("用户名", "账号", "账户名"))
        ):
            return {
                "thought": "Coordinator使用凭据引用填写登录用户名",
                "action": "fill",
                "parameters": {
                    "role": "textbox",
                    "index": 0,
                    "value": "{{credential.username}}",
                },
            }
        if (
            "{{credential.password}}" in contract
            or "密码" in normalized
        ):
            return {
                "thought": "Coordinator使用凭据引用填写登录密码",
                "action": "fill",
                "parameters": {
                    "role": "textbox",
                    "index": 1,
                    "value": "{{credential.password}}",
                },
            }
        return None

    def _login_form_action(self) -> dict | None:
        if "/login" not in str(self.current_url):
            return None
        normalized = str(self.goal or "").replace(" ", "")
        if "点击" in normalized and "用户协议" in normalized:
            return {
                "thought": "Coordinator确定性打开用户协议",
                "action": "click",
                "parameters": {"role": "link", "name": "用户协议"},
            }
        if "选择" in normalized and any(
            token in normalized for token in ("门店", "机构", "组织")
        ):
            return {
                "thought": "Coordinator按认证策略确定性选择门店",
                "action": "select_option",
                "parameters": {"role": "combobox", "option_text": ""},
            }
        if "点击" in normalized and "登录" in normalized:
            criteria = str(self.success_criteria or "")
            expect_failure = any(
                marker in criteria
                for marker in ("登录失败", "请输入", "请选择门店")
            )
            return {
                "thought": "Coordinator按认证策略确定性提交登录表单",
                "action": "click",
                "parameters": {
                    "role": "button",
                    "name": "登 录",
                    **({"expect_failure": True} if expect_failure else {}),
                },
            }
        return None

    def _menu_action(self) -> dict | None:
        if "/login" in str(self.current_url):
            return None
        match = re.match(
            r"^(?:点击|打开|进入)(.+?)(?:菜单|入口|链接)$",
            str(self.goal or "").strip(),
        )
        if not match:
            return None
        return {
            "thought": "Coordinator按步骤语义确定性点击导航菜单",
            "action": "click",
            "parameters": {"role": "link", "name": match.group(1).strip()},
        }

    def _detail_action(self) -> dict | None:
        if "/login" in str(self.current_url):
            return None
        goal = str(self.goal or "").replace(" ", "")
        if "点击" in goal and "详情按钮" in goal:
            return {
                "thought": "Coordinator按步骤语义点击首个详情按钮",
                "action": "click",
                "parameters": {
                    "role": "link", "name": "详情", "index": 0,
                },
            }
        return None

    def deterministic_action(self) -> dict | None:
        return (
            self._credential_action()
            or self._login_form_action()
            or self._menu_action()
            or self._detail_action()
            or super().deterministic_action()
        )


__all__ = ["CredentialAwareReasoningState"]
