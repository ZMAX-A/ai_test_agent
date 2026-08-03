"""Strict verifier with navigation-aware login completion evidence."""

from __future__ import annotations

import importlib.util
from pathlib import Path


_SOURCE_PATH = Path(__file__).resolve().parent.parent / "strict_verifier_agent.py"
_SPEC = importlib.util.spec_from_file_location(
    "agents._strict_verifier_agent_source", _SOURCE_PATH
)
_SOURCE = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_SOURCE)

VerificationResult = _SOURCE.VerificationResult


class StrictVerifierAgent(_SOURCE.StrictVerifierAgent):
    def verify(self, page, goal: str, success_criteria: str = "",
               page_state: str = "", action: dict | None = None,
               action_result: dict | None = None):
        action = action or {}
        result_ok = bool((action_result or {}).get("success"))
        is_login_click = (
            action.get("action") == "click"
            and "登录" in str(goal).replace(" ", "")
        )
        current_url = str(getattr(page, "url", ""))
        if is_login_click and result_ok and "/login" not in current_url:
            return VerificationResult(
                True,
                0.99,
                [f"登录提交后已离开登录页: {current_url}"],
                "观察到登录导航完成",
                True,
                "完成当前步骤",
            )
        return super().verify(
            page,
            goal,
            success_criteria,
            page_state,
            action=action,
            action_result=action_result,
        )


__all__ = ["StrictVerifierAgent", "VerificationResult"]
