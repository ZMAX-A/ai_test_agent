"""独立测试验收 Agent。

Verifier 不相信 Executor 的 ``finish`` 声明，而是重新读取 URL、标题、页面语义
和元素实际值，生成独立证据。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any


ASSERT_ACTIONS = {"assert_text", "assert_url", "assert_title", "assert_visual"}


@dataclass
class VerificationResult:
    passed: bool
    confidence: float
    evidence: list[str] = field(default_factory=list)
    reason: str = ""
    recoverable: bool = True
    next_action: str = "收集更多页面证据"

    def to_dict(self) -> dict:
        return asdict(self)


class VerifierAgent:
    role = "verifier"

    @staticmethod
    def _page_meta(page) -> tuple[str, str]:
        try:
            url = page.url
        except Exception:
            url = ""
        try:
            title = page.title() or ""
        except Exception:
            title = ""
        return url, title

    @staticmethod
    def _build_locator(page, params: dict):
        if params.get("som_index") is not None:
            return page.locator(f'[data-som-index="{int(params["som_index"])}"]')
        kwargs = {"role": params.get("role", "")}
        if params.get("name"):
            kwargs["name"] = params["name"]
        locator = page.get_by_role(**kwargs)
        if params.get("index") is not None:
            locator = locator.nth(int(params["index"]))
        return locator

    @staticmethod
    def _expected_texts(contract: str) -> list[str]:
        patterns = [
            r"(?:包含|显示|出现|可见)[：: ]*[‘'\"“]?([^，。；;'\"”]{1,30})",
            r"进入[：: ]*([^，。；]{2,20}?)(?:页面|页)",
        ]
        values = []
        for pattern in patterns:
            values.extend(m.strip() for m in re.findall(pattern, contract) if m.strip())
        return values

    def verify(self, page, goal: str, success_criteria: str = "",
               page_state: str = "", action: dict | None = None,
               action_result: dict | None = None) -> VerificationResult:
        contract = success_criteria or goal
        url, title = self._page_meta(page)
        haystack = f"{title}\n{page_state}\n{url}"
        evidence: list[str] = []

        # URL 是最强、最便宜的页面状态证据。
        for absolute in re.findall(r"https?://[^\s，。)）]+", f"{goal} {success_criteria}"):
            if url.rstrip("/") == absolute.rstrip("/"):
                evidence.append(f"URL等于目标: {absolute}")
        path_text = re.sub(r"https?://[^\s，。)）]+", "", f"{goal} {success_criteria}")
        for path in re.findall(r"/[A-Za-z0-9_./-]+", path_text):
            if path in url:
                evidence.append(f"URL包含目标路径: {path}")

        for expected in self._expected_texts(contract):
            if expected in haystack:
                evidence.append(f"页面语义包含: {expected}")

        result_ok = bool(action_result and action_result.get("success"))
        action_name = (action or {}).get("action", "")
        params = (action or {}).get("parameters", {})

        if result_ok and action_name in ASSERT_ACTIONS:
            evidence.append("独立执行的显式断言成功")

        # 输入目标必须回读元素真实值，不能只信 fill 返回值。
        if result_ok and action_name == "fill" and any(k in contract for k in ("输入", "填入", "填写", "值为")):
            expected_value = str(params.get("value", ""))
            try:
                actual_value = self._build_locator(page, params).input_value(timeout=1500)
                if actual_value == expected_value:
                    evidence.append("回读输入框值与目标一致")
            except Exception:
                pass

        # 纯点击/选择目标验收操作发生；一旦有更严格 criteria，就不使用弱证据。
        if not success_criteria and result_ok and action_name == "click" and "点击" in goal:
            evidence.append("目标点击动作执行成功")
        if not success_criteria and result_ok and action_name == "select_option" and any(k in goal for k in ("选择", "下拉")):
            evidence.append("目标选择动作执行成功")
        if result_ok and action_name == "goto":
            target = str(params.get("url", ""))
            if target and url.rstrip("/") == target.rstrip("/"):
                evidence.append("导航后URL与动作目标一致")

        if evidence:
            confidence = 0.98 if any(e.startswith("URL") or "回读" in e or "断言" in e for e in evidence) else 0.82
            return VerificationResult(True, confidence, evidence, "完成条件已被独立验证", True, "完成当前步骤")

        if action_result and not result_ok:
            reason = str(action_result.get("message", "动作失败"))[:200]
            return VerificationResult(False, 0.95, [], reason, True, "根据失败类型更换策略")
        return VerificationResult(False, 0.35, [], "尚无独立完成证据", True, "执行目标动作或显式断言")
