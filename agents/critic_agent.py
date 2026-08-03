"""独立动作审查 Agent。"""

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
    """与 Executor 使用独立调用上下文，只审查动作，不操作浏览器。"""

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

    def review(self, action: dict, context: dict, world_snapshot: dict) -> CritiqueResult:
        self.last_model_call_count = 0
        deterministic = self.preflight(action)
        if deterministic is not None:
            return deterministic

        prompt = f"""
你是独立 Web 测试 Critic。Executor 提出了一个高影响动作，你只能审查，不能声称动作已经执行。

审查目标：
1. 动作是否由当前页面证据支持，而不是猜测页面外元素
2. 是否符合当前原子步骤边界
3. 是否会重复失败策略或跳过必要前置条件
4. 是否存在更小、更可验证的替代动作

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
