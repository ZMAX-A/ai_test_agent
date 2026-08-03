"""Production reasoning policies for deterministic high-risk actions."""

from __future__ import annotations

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
        contract = f"{self.goal} {self.success_criteria}"
        normalized = contract.replace(" ", "")
        is_input = any(token in normalized for token in ("输入", "填入", "填写"))
        if not is_input:
            return None

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

    def deterministic_action(self) -> dict | None:
        return self._credential_action() or super().deterministic_action()


__all__ = ["CredentialAwareReasoningState"]
