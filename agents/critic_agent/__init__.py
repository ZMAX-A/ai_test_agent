"""带前置条件审查的独立 Critic Agent。"""

from __future__ import annotations

from dataclasses import dataclass
import json

from openai import OpenAI

from config.settings import settings
from executor.action_validator import validate_action
from utils.json_utils import safe_parse_json


HIGH_IMPACT_ACTIONS = {"click", "goto", "select_option", "close_popup", "go_back", "refresh"}


@dataclass
class CritiqueResult:
    approved: bool
    reason: str
    confidence: float
    replacement: dict | None = None
    model_used: bool = False


class CriticAgent:
    role = "critic"

    def __init__(self):
        self.client = OpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
            timeout=settings.LLM_TIMEOUT_SECONDS,
            max_retries=settings.LLM_MAX_RETRIES,
        )
        self.model_name = settings.LLM_MODEL
        self.last_model_call_count = 0

    @staticmethod
    def preflight(action: dict) -> CritiqueResult | None:
        valid, error = validate_action(action)
        if not valid:
            return CritiqueResult(False, f"工具协议拒绝: {error}", 1.0)
        if action.get("action") not in HIGH_IMPACT_ACTIONS:
            return CritiqueResult(True, "低影响动作已通过确定性协议审查", 0.98)
        return None

    @staticmethod
    def _safe_action(action: dict) -> dict:
        safe = json.loads(json.dumps(action, ensure_ascii=False))
        params = safe.get("parameters", {})
        if params.get("value") not in (None, ""):
            params["value"] = f"<redacted:{len(str(params['value']))}>"
        return safe

    @staticmethod
    def _login_precondition_review(action: dict, context: dict,
                                   world_snapshot: dict) -> CritiqueResult | None:
        if action.get("action") != "click":
            return None
        params = action.get("parameters", {})
        target = f"{params.get('name', '')} {context.get('step_goal', '')}".lower()
        if "登录" not in target and "login" not in target:
            return None
        page_state = str(context.get("page_state", "")).lower()
        if not any(key in page_state for key in ("combobox", "请选择门店", "请选择机构")):
            return None

        selected = any(
            item.get("action") == "select_option" and item.get("success")
            for item in world_snapshot.get("recent_actions", [])
        )
        if selected:
            return CritiqueResult(
                True, "世界模型已确认门店/机构选择成功，允许提交登录", 0.99
            )
        return CritiqueResult(
            False,
            "登录前存在未完成的门店/机构必填下拉，先满足前置条件",
            0.99,
            replacement={
                "thought": "Critic要求先完成登录必填门店/机构",
                "action": "select_option",
                "parameters": {"role": "combobox", "option_text": ""},
            },
        )

    def review(self, action: dict, context: dict, world_snapshot: dict) -> CritiqueResult:
        self.last_model_call_count = 0
        deterministic = self.preflight(action)
        if deterministic is not None:
            return deterministic
        login_review = self._login_precondition_review(action, context, world_snapshot)
        if login_review is not None:
            return login_review

        prompt = f"""
你是独立 Web 测试 Critic。Executor 提出了一个高影响动作，你只能审查，不能声称动作已经执行。

审查目标：
1. 动作是否由当前页面证据支持
2. 是否符合当前原子步骤边界
3. 是否跳过必填下拉、弹窗或认证等前置条件
4. 是否重复失败策略
5. 是否存在更小、更可验证的替代动作

当前目标：{context.get('step_goal', '')}
当前URL：{context.get('page_url', '')}
页面摘要：{str(context.get('page_state', ''))[:3000]}
候选动作：{json.dumps(self._safe_action(action), ensure_ascii=False)}
世界模型：{json.dumps(world_snapshot, ensure_ascii=False)[:5000]}

只输出JSON：
{{"approved":true或false,"reason":"简短证据说明","confidence":0到1,
 "replacement":null或{{"thought":"修正依据","action":"工具名","parameters":{{}}}}}}
"""
        try:
            self.last_model_call_count = 1
            response = self.client.chat.completions.create(
                model=self.model_name,
                temperature=0.0,
                messages=[{"role": "user", "content": prompt}],
            )
            data = safe_parse_json(response.choices[0].message.content)
            raw_approved = data.get("approved", False)
            approved = raw_approved if isinstance(raw_approved, bool) else str(raw_approved).lower() == "true"
            replacement = data.get("replacement")
            if replacement:
                valid, _ = validate_action(replacement)
                if not valid:
                    replacement = None
            return CritiqueResult(
                approved=approved,
                reason=str(data.get("reason", "Critic未给出理由"))[:300],
                confidence=float(data.get("confidence", 0.5)),
                replacement=replacement,
                model_used=True,
            )
        except Exception as exc:
            return CritiqueResult(
                True,
                f"Critic调用异常，候选动作已通过本地Schema，允许受控执行: {exc}",
                0.4,
                model_used=self.last_model_call_count > 0,
            )


__all__ = ["CriticAgent", "CritiqueResult", "HIGH_IMPACT_ACTIONS"]
