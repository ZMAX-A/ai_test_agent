"""具备标准 Tool Calling 与 JSON 协议降级能力的 Executor Agent。"""

from __future__ import annotations

import json
import os

from agents.executor_agent import ExecutorAgent
from core.tool_registry import ToolRegistry
from utils.json_utils import safe_parse_json


class ToolAwareExecutorAgent(ExecutorAgent):
    """让模型从动态工具目录中选择一个原子动作。

    auto 模式优先尝试 OpenAI 兼容 function calling；若模型服务不支持，会在
    当前任务内自动降级到已有 JSON 动作协议，避免影响真实测试稳定性。
    """

    role = "executor"

    def __init__(self, registry: ToolRegistry):
        super().__init__()
        self.registry = registry
        self.tool_calling_mode = os.getenv("LLM_TOOL_CALLING_MODE", "auto").lower()
        self._native_tools_disabled = self.tool_calling_mode in {"off", "legacy", "json"}
        self.last_model_call_count = 0

    def _build_prompt(self, context: dict) -> str:
        step_goal = context.get("step_goal", "")
        page_state = context.get("page_state", "")
        last_result = context.get("last_result", "无")
        tried_strategies = context.get("tried_strategies", "无（首次）")
        reasoning_state = context.get("reasoning_state", "未提供控制器状态")
        page_url = context.get("page_url", "")
        page_title = context.get("page_title", "")
        meta = ""
        if page_url:
            meta += f"\n【当前页面】URL={page_url}"
        if page_title:
            meta += f" 标题={page_title}"

        prompt = self.prompt_template.replace("{step_goal}", step_goal)
        prompt = prompt.replace("{last_result}", last_result)
        prompt = prompt.replace("{tried_strategies}", tried_strategies)
        prompt = prompt.replace("{page_state}", meta + "\n" + page_state)
        prompt = prompt.replace("{reasoning_state}", reasoning_state)
        return prompt

    @staticmethod
    def _decode_message(message) -> dict:
        tool_calls = getattr(message, "tool_calls", None) or []
        if tool_calls:
            call = tool_calls[0]
            function = getattr(call, "function", None)
            name = getattr(function, "name", "")
            raw_arguments = getattr(function, "arguments", "{}") or "{}"
            arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
            if not name or not isinstance(arguments, dict):
                raise ValueError("模型返回了无效的结构化工具调用")
            return {
                "thought": getattr(message, "content", "") or "模型选择结构化工具",
                "action": name,
                "parameters": arguments,
            }

        parsed = safe_parse_json(getattr(message, "content", "") or "")
        if not isinstance(parsed, dict) or not parsed.get("action"):
            raise ValueError("模型既未调用工具，也未返回合法动作 JSON")
        return parsed

    def _ask_with_native_tools(self, context: dict) -> dict:
        prompt = self._build_prompt(context)
        prompt += (
            "\n\n【结构化工具协议】从提供的工具中只调用一个最小原子工具。"
            "不要虚构工具，不要一次调用多个工具；是否完成仍由 Verifier 裁决。"
        )
        response = self.client.chat.completions.create(
            model=self.model_name,
            temperature=0.1,
            messages=[{"role": "user", "content": prompt}],
            tools=self.registry.openai_tools_for(self.role),
            tool_choice="auto",
        )
        return self._decode_message(response.choices[0].message)

    def ask(self, context: dict) -> dict:
        self.last_model_call_count = 0
        if not self._native_tools_disabled:
            try:
                self.last_model_call_count += 1
                return self._ask_with_native_tools(context)
            except Exception as exc:
                if self.tool_calling_mode in {"required", "native"}:
                    return {
                        "action": "finish",
                        "parameters": {"result": f"fail: 结构化工具调用失败 - {exc}"},
                    }
                self._native_tools_disabled = True
                print(f"[TOOL-RUNTIME] 原生 Tool Calling 不可用，切换 JSON 协议: {exc}")

        self.last_model_call_count += 1
        return super().ask(context)
