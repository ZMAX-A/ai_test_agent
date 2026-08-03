"""支持类型化验收协议和强证据门禁的 Verifier。"""

from __future__ import annotations

import json
from typing import Any

from agents.verifier_agent import VerificationResult, VerifierAgent


class StrictVerifierAgent(VerifierAgent):
    @staticmethod
    def _parse_contract(success_criteria: Any) -> dict | None:
        if isinstance(success_criteria, dict):
            return success_criteria
        text = str(success_criteria or "").strip()
        if not text.startswith("{"):
            return None
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    def _verify_typed_contract(self, page, contract: dict) -> VerificationResult:
        evidence: list[str] = []
        failures: list[str] = []
        url, title = self._page_meta(page)
        try:
            body = page.locator("body").inner_text(timeout=1500) or ""
        except Exception:
            body = ""

        def values(name: str) -> list[str]:
            value = contract.get(name, [])
            return [str(item) for item in value] if isinstance(value, list) else ([str(value)] if value not in (None, "") else [])

        for expected in values("url_contains"):
            (evidence if expected in url else failures).append(
                f"URL包含: {expected}" if expected in url else f"URL缺少: {expected}"
            )
        for expected in values("url_equals"):
            matched = url.rstrip("/") == expected.rstrip("/")
            (evidence if matched else failures).append(
                f"URL等于: {expected}" if matched else f"URL不等于: {expected}"
            )
        for expected in values("title_contains"):
            (evidence if expected in title else failures).append(
                f"标题包含: {expected}" if expected in title else f"标题缺少: {expected}"
            )
        for expected in values("text_contains"):
            (evidence if expected in body else failures).append(
                f"页面文本包含: {expected}" if expected in body else f"页面文本缺少: {expected}"
            )

        elements = contract.get("elements", [])
        if isinstance(elements, dict):
            elements = [elements]
        for spec in elements:
            try:
                locator = self._build_locator(page, spec)
                visible = locator.is_visible(timeout=1500)
            except Exception:
                visible = False
            label = f"{spec.get('role', '')}/{spec.get('name', '')}".strip("/")
            (evidence if visible else failures).append(
                f"元素可见: {label}" if visible else f"元素不可见: {label}"
            )

        if failures:
            return VerificationResult(
                False, 0.98, evidence, "；".join(failures), True, "满足所有类型化验收条件"
            )
        if evidence:
            return VerificationResult(True, 0.99, evidence, "类型化验收全部通过", True, "完成当前步骤")
        return VerificationResult(False, 0.9, [], "验收协议没有可执行规则", False, "补充验收条件")

    def verify(self, page, goal: str, success_criteria: str = "",
               page_state: str = "", action: dict | None = None,
               action_result: dict | None = None) -> VerificationResult:
        typed = self._parse_contract(success_criteria)
        if typed is not None:
            return self._verify_typed_contract(page, typed)

        result = super().verify(
            page, goal, success_criteria, page_state,
            action=action, action_result=action_result,
        )
        weak = {"目标点击动作执行成功", "目标选择动作执行成功"}
        if result.passed and result.evidence and set(result.evidence).issubset(weak):
            change = (action_result or {}).get("page_change", {})
            if change.get("url_changed"):
                return VerificationResult(
                    True, 0.92, ["动作后URL发生变化"], "观察到页面导航结果", True, "完成当前步骤"
                )
            if change.get("toast_text"):
                return VerificationResult(
                    True, 0.9, ["动作后出现反馈消息"], "观察到页面反馈", True, "完成当前步骤"
                )
            return VerificationResult(
                False, 0.75, [], "动作已执行，但没有观察到业务状态变化",
                True, "检查URL、页面内容或执行显式断言",
            )
        return result
