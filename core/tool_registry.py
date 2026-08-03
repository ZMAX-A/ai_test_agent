"""统一的 Web 测试工具注册表。

模型只负责选择工具和生成参数；注册表负责能力发现、角色授权、参数约束与
真实处理器分发。这样浏览器对象不会直接暴露给 LLM，也不会执行白名单之外
的任意代码。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from executor.action_validator import ACTION_SCHEMA, validate_action


ToolHandler = Callable[[dict, dict], Any]


class ToolRegistryError(RuntimeError):
    """工具注册或调用失败。"""


class UnknownToolError(ToolRegistryError):
    """请求了未注册的工具。"""


class ToolPermissionError(ToolRegistryError):
    """Agent 尝试使用未授权工具。"""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict
    allowed_roles: frozenset[str]
    handler: ToolHandler
    expose_to_model: bool = False

    def as_openai_tool(self) -> dict:
        """转换为 OpenAI 兼容的 function tool schema。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ToolRegistryError(f"工具重复注册: {spec.name}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise UnknownToolError(f"未知工具: {name}") from exc

    def names_for(self, role: str, model_visible_only: bool = False) -> list[str]:
        return sorted(
            spec.name
            for spec in self._tools.values()
            if role in spec.allowed_roles
            and (not model_visible_only or spec.expose_to_model)
        )

    def openai_tools_for(self, role: str) -> list[dict]:
        return [
            self._tools[name].as_openai_tool()
            for name in self.names_for(role, model_visible_only=True)
        ]

    def invoke(self, role: str, name: str, arguments: dict | None = None,
               context: dict | None = None) -> Any:
        spec = self.get(name)
        if role not in spec.allowed_roles:
            raise ToolPermissionError(f"角色 {role} 无权调用工具 {name}")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            raise ToolRegistryError(f"工具参数必须是对象: {name}")
        return spec.handler(dict(arguments), context or {})


def _property_schema(field: str) -> dict:
    if field in {"index", "som_index"}:
        return {"type": "integer", "minimum": 0}
    if field == "direction":
        return {"type": "string", "enum": ["down", "up"]}
    return {"type": "string"}


def _action_parameters_schema(action: str) -> dict:
    action_schema = ACTION_SCHEMA[action]
    fields = set(action_schema.get("required", []))
    fields.update(action_schema.get("optional", []))
    for group in action_schema.get("any_of", []):
        fields.update(group)
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            field: _property_schema(field)
            for field in sorted(fields)
        },
        "additionalProperties": False,
    }
    required = list(action_schema.get("required", []))
    if required:
        schema["required"] = required
    any_of = action_schema.get("any_of", [])
    if any_of:
        schema["anyOf"] = [
            {"required": list(group)}
            for group in any_of
        ]
    return schema


def _browser_action_handler(action_name: str) -> ToolHandler:
    def handler(arguments: dict, context: dict) -> dict:
        action = {
            "thought": context.get("thought", "通过受控工具运行时执行"),
            "action": action_name,
            "parameters": arguments,
        }
        valid, error = validate_action(action)
        if not valid:
            return {
                "success": False,
                "error_type": "TOOL_ARGUMENT_ERROR",
                "message": error,
            }
        browser_executor = context.get("browser_executor")
        if browser_executor is None:
            raise ToolRegistryError(f"工具 {action_name} 缺少 browser_executor 上下文")
        return browser_executor.execute(action)

    return handler


def _observe_aria(arguments: dict, context: dict) -> str:
    sensor = context.get("aria_sensor")
    page = context.get("page")
    if sensor is None or page is None:
        raise ToolRegistryError("observe_aria 缺少页面或传感器上下文")
    return sensor.capture(page)


def _observe_visual(arguments: dict, context: dict) -> str:
    sensor = context.get("visual_sensor")
    page = context.get("page")
    if sensor is None or page is None:
        raise ToolRegistryError("observe_visual 缺少页面或传感器上下文")
    return sensor.capture(page, step_goal=str(arguments.get("step_goal", "")))


def _verify_page(arguments: dict, context: dict):
    verifier = context.get("verifier")
    page = context.get("page")
    if verifier is None or page is None:
        raise ToolRegistryError("verify_page 缺少页面或 Verifier 上下文")
    return verifier.verify(
        page,
        str(arguments.get("goal", "")),
        str(arguments.get("success_criteria", "")),
        str(context.get("page_state", "")),
        action=context.get("action"),
        action_result=context.get("action_result"),
    )


def create_web_tool_registry() -> ToolRegistry:
    """创建项目默认工具集；每个工具同时声明可调用角色。"""
    registry = ToolRegistry()
    for action_name, schema in ACTION_SCHEMA.items():
        registry.register(ToolSpec(
            name=action_name,
            description=schema.get("description", action_name),
            parameters=_action_parameters_schema(action_name),
            allowed_roles=frozenset({"executor"}),
            handler=_browser_action_handler(action_name),
            expose_to_model=True,
        ))

    registry.register(ToolSpec(
        name="observe_aria",
        description="读取当前页面的 ARIA 语义快照",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        allowed_roles=frozenset({"coordinator"}),
        handler=_observe_aria,
    ))
    registry.register(ToolSpec(
        name="observe_visual",
        description="截图并使用视觉模型识别当前页面",
        parameters={
            "type": "object",
            "properties": {"step_goal": {"type": "string"}},
            "additionalProperties": False,
        },
        allowed_roles=frozenset({"coordinator"}),
        handler=_observe_visual,
    ))
    registry.register(ToolSpec(
        name="verify_page",
        description="独立回读页面并判断步骤完成条件",
        parameters={
            "type": "object",
            "properties": {
                "goal": {"type": "string"},
                "success_criteria": {"type": "string"},
            },
            "required": ["goal"],
            "additionalProperties": False,
        },
        allowed_roles=frozenset({"verifier"}),
        handler=_verify_page,
    ))
    return registry
