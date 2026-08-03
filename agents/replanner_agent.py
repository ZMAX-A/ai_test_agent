"""失败触发的动态 Replanner Agent。"""

from __future__ import annotations

import json

from openai import OpenAI

from config.settings import settings
from utils.json_utils import safe_parse_json


class ReplannerAgent:
    role = "replanner"

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
    def fallback_plan(world_snapshot: dict) -> dict:
        hypotheses = world_snapshot.get("open_hypotheses", [])
        diagnosis = hypotheses[-1].get("hypothesis", "当前策略缺少完成证据") if hypotheses else "当前策略缺少完成证据"
        return {
            "diagnosis": diagnosis,
            "next_strategy": "重新读取页面状态，选择不同定位证据，并用URL、元素值或显式断言验证结果",
            "avoid": ["重复最近一次完全相同的动作", "仅凭动作返回值宣布完成"],
            "success_probe": "优先取得URL变化、元素真实值或显式断言证据",
        }

    def replan(self, context: dict, world_snapshot: dict) -> dict:
        self.last_model_call_count = 0
        prompt = f"""
你是 Web 测试 Replanner。当前策略失败或没有产生完成证据。请依据事实重新制定下一轮策略，
不要直接输出浏览器动作，不要重复最近失败动作，也不要假设页面上存在未观察到的元素。

步骤目标：{context.get('step_goal', '')}
最近结果：{str(context.get('last_result', ''))[:500]}
世界模型：{json.dumps(world_snapshot, ensure_ascii=False)[:7000]}

只输出JSON：
{{"diagnosis":"最可能根因","next_strategy":"下一轮策略",
  "avoid":["禁止重复的策略"],"success_probe":"如何获得完成证据"}}
"""
        try:
            self.last_model_call_count = 1
            response = self.client.chat.completions.create(
                model=self.model_name,
                temperature=0.1,
                messages=[{"role": "user", "content": prompt}],
            )
            data = safe_parse_json(response.choices[0].message.content)
            if not isinstance(data, dict) or not data.get("next_strategy"):
                raise ValueError("Replanner返回缺少next_strategy")
            return {
                "diagnosis": str(data.get("diagnosis", ""))[:300],
                "next_strategy": str(data.get("next_strategy", ""))[:500],
                "avoid": [str(item)[:200] for item in data.get("avoid", [])[:5]],
                "success_probe": str(data.get("success_probe", ""))[:300],
            }
        except Exception:
            return self.fallback_plan(world_snapshot)
