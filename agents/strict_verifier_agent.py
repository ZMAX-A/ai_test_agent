"""支持类型化验收协议和强证据门禁的 Verifier。"""

from __future__ import annotations

import json
from typing import Any

from agents.verifier_agent import VerificationResult, VerifierAgent


class StrictVerifierAgent(VerifierAgent):
    @staticmethod
    def _has_selected_option_readback(
        page, expected_text: str = "",
    ) -> bool:
        selectors = (
            ".ant-select-selection-item:visible",
            "[role='option'][aria-selected='true']:visible",
        )
        for selector in selectors:
            try:
                selected = page.locator(selector)
                for index in range(selected.count()):
                    node = selected.nth(index)
                    value = (
                        node.inner_text(timeout=1000) or ""
                    ).strip()
                    if node.is_visible(timeout=1000) and value and (
                        not expected_text or expected_text in value
                    ):
                        return True
            except Exception:
                continue
        return False
    @classmethod
    def _verify_intentionally_unset(
        cls, page, goal: str,
    ) -> VerificationResult | None:
        normalized = str(goal or "").replace(" ", "")
        checks: list[tuple[str, bool]] = []
        try:
            if "不输入账号和密码" in normalized:
                username = page.locator("input[type='text']").first
                password = page.locator("input[type='password']").first
                checks.extend((
                    ("账号保持为空", not username.input_value(timeout=1000)),
                    ("密码保持为空", not password.input_value(timeout=1000)),
                ))
            elif "不输入账号" in normalized or "账号为空" in normalized:
                username = page.locator("input[type='text']").first
                checks.append((
                    "账号保持为空", not username.input_value(timeout=1000)
                ))
            elif "不输入密码" in normalized or "密码为空" in normalized:
                password = page.locator("input[type='password']").first
                checks.append((
                    "密码保持为空", not password.input_value(timeout=1000)
                ))
            if "不选择门店" in normalized:
                checks.append((
                    "门店保持未选择",
                    not cls._has_selected_option_readback(page),
                ))
        except Exception:
            return None
        if not checks:
            return None
        evidence = [label for label, passed in checks if passed]
        failures = [label for label, passed in checks if not passed]
        if failures:
            return VerificationResult(
                False, 0.99, evidence,
                "；".join(failures) + "条件不成立",
                True, "清空相应登录字段",
            )
        return VerificationResult(
            True, 0.99, evidence, "空值前置状态已独立回读",
            True, "完成当前步骤",
        )


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

    def _verify_typed_contract(
        self, page, contract: dict, action_result: dict | None = None,
    ) -> VerificationResult:
        evidence: list[str] = []
        failures: list[str] = []
        url, title = self._page_meta(page)
        try:
            body = page.locator("body").inner_text(timeout=1500) or ""
        except Exception:
            body = ""
        visible_feedback: list[str] = []
        try:
            visible_feedback = [
                str(text).strip()
                for text in page.locator(
                    ".ant-message-notice-content:visible, "
                    ".ant-form-item-explain-error:visible, "
                    "[role='alert']:visible"
                ).all_inner_texts()
                if str(text).strip()
            ]
        except Exception:
            pass
        semantic_text = "\n".join([body, *visible_feedback])


        def values(name: str) -> list[str]:
            value = contract.get(name, [])
            if isinstance(value, list):
                return [str(item) for item in value]
            if value in (None, ""):
                return []
            return [str(value)]

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
            (evidence if expected in semantic_text else failures).append(
                f"页面文本包含: {expected}" if expected in semantic_text else f"页面文本缺少: {expected}"
            )

        if contract.get("url_changed") is True:
            changed = bool(
                (action_result or {}).get("page_change", {}).get("url_changed")
            )
            (evidence if changed else failures).append(
                "动作后URL发生变化" if changed else "动作后URL未发生变化"
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
        intentionally_unset = self._verify_intentionally_unset(page, goal)
        if intentionally_unset is not None:
            return intentionally_unset
        typed = self._parse_contract(success_criteria)
        if typed is not None:
            return self._verify_typed_contract(page, typed, action_result)

        result = super().verify(
            page, goal, success_criteria, page_state,
            action=action, action_result=action_result,
        )
        expected_option = str(
            (action or {}).get("parameters", {}).get("option_text", "")
        ).strip()
        if (
            not success_criteria
            and action_result
            and action_result.get("success")
            and (action or {}).get("action") == "select_option"
            and self._has_selected_option_readback(page, expected_option)
        ):
            return VerificationResult(
                True, 0.97, ["回读下拉框存在非空选中值"],
                "选择结果已从页面独立回读", True, "完成当前步骤",
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
