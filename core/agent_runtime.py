"""Agent 能力运行时：角色隔离、工具授权、审计和结构化调用。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.tool_registry import ToolPermissionError, ToolRegistry


@dataclass(frozen=True)
class AgentProfile:
    role: str
    allowed_tools: frozenset[str]


def default_agent_profiles(registry: ToolRegistry) -> dict[str, AgentProfile]:
    return {
        "planner": AgentProfile("planner", frozenset()),
        "coordinator": AgentProfile(
            "coordinator", frozenset(registry.names_for("coordinator"))
        ),
        "executor": AgentProfile(
            "executor", frozenset(registry.names_for("executor"))
        ),
        "verifier": AgentProfile(
            "verifier", frozenset(registry.names_for("verifier"))
        ),
    }


class AgentRuntime:
    """一次任务内的工具网关。

    角色先通过 AgentProfile 授权，再通过 ToolSpec 的 allowed_roles 授权；所有
    调用与结果都会写入共享黑板，形成可回放审计轨迹。
    """

    def __init__(self, registry: ToolRegistry, blackboard=None,
                 profiles: dict[str, AgentProfile] | None = None):
        self.registry = registry
        self.blackboard = blackboard
        self.profiles = profiles or default_agent_profiles(registry)

    def capabilities(self, role: str) -> list[str]:
        profile = self.profiles.get(role)
        return sorted(profile.allowed_tools) if profile else []

    def openai_tools(self, role: str) -> list[dict]:
        allowed = set(self.capabilities(role))
        return [
            tool for tool in self.registry.openai_tools_for(role)
            if tool["function"]["name"] in allowed
        ]

    def invoke(self, role: str, tool_name: str, arguments: dict | None = None,
               context: dict | None = None) -> Any:
        arguments = arguments or {}
        profile = self.profiles.get(role)
        if profile is None or tool_name not in profile.allowed_tools:
            self._publish(role, "tool_denied", tool=tool_name, arguments=arguments)
            raise ToolPermissionError(f"角色 {role} 未获准调用工具 {tool_name}")

        self._publish(role, "tool_called", tool=tool_name, arguments=arguments)
        try:
            result = self.registry.invoke(role, tool_name, arguments, context)
        except Exception as exc:
            self._publish(role, "tool_failed", tool=tool_name, error=str(exc)[:300])
            raise

        success = self._result_success(result)
        self._publish(role, "tool_completed", tool=tool_name, success=success)
        return result

    def invoke_action(self, role: str, action: dict, context: dict | None = None) -> Any:
        return self.invoke(
            role,
            str(action.get("action", "")),
            action.get("parameters", {}),
            {**(context or {}), "thought": action.get("thought", "")},
        )

    @staticmethod
    def _result_success(result: Any) -> bool:
        if isinstance(result, dict):
            return bool(result.get("success", True))
        if hasattr(result, "passed"):
            return bool(result.passed)
        return True

    def _publish(self, role: str, event: str, **payload) -> None:
        if self.blackboard is not None:
            self.blackboard.publish(role, event, **payload)
