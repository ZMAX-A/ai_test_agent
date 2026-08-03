"""统一 Runner 的任务级上下文，不修改任何模块全局类。"""

from __future__ import annotations

from contextvars import ContextVar, Token

from core.agent_runtime import AgentRuntime
from core.task_world_model import TaskWorldModel


_RUNTIME: ContextVar[AgentRuntime | None] = ContextVar("unified_agent_runtime", default=None)
_WORLD: ContextVar[TaskWorldModel | None] = ContextVar("unified_world_model", default=None)


def bind_task_context(runtime: AgentRuntime, world: TaskWorldModel) -> tuple[Token, Token]:
    return _RUNTIME.set(runtime), _WORLD.set(world)


def reset_task_context(tokens: tuple[Token, Token]) -> None:
    runtime_token, world_token = tokens
    _RUNTIME.reset(runtime_token)
    _WORLD.reset(world_token)


def current_runtime() -> AgentRuntime:
    runtime = _RUNTIME.get()
    if runtime is None:
        raise RuntimeError("统一 AgentRuntime 尚未绑定当前任务")
    return runtime


def current_world_model() -> TaskWorldModel:
    world = _WORLD.get()
    if world is None:
        raise RuntimeError("统一任务世界模型尚未绑定当前任务")
    return world
