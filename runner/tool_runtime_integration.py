"""把 AgentRuntime 非侵入式接入现有 MultiAgentTestRunner。

旧 Runner 继续负责成熟的循环、预算与用例生成；本模块在构造依赖时注入受控
代理，使感知、浏览器执行和独立验证全部通过统一工具网关。
"""

from __future__ import annotations

from contextvars import ContextVar

import runner.multi_agent_runner as base_runner

from agents.tool_aware_executor_agent import ToolAwareExecutorAgent
from core.agent_runtime import AgentRuntime
from core.blackboard import TaskBlackboard as OriginalTaskBlackboard
from core.tool_registry import create_web_tool_registry
from perception.aria_sensor import AriaSensor as OriginalAriaSensor
from perception.visual_sensor import VisualSensor as OriginalVisualSensor
from agents.verifier_agent import VerifierAgent as OriginalVerifierAgent


TOOL_REGISTRY = create_web_tool_registry()
_CURRENT_RUNTIME: ContextVar[AgentRuntime | None] = ContextVar(
    "web_test_agent_runtime", default=None
)


def current_runtime() -> AgentRuntime:
    runtime = _CURRENT_RUNTIME.get()
    if runtime is None:
        raise RuntimeError("AgentRuntime 尚未绑定任务黑板")
    return runtime


class RuntimeTaskBlackboard(OriginalTaskBlackboard):
    def __post_init__(self):
        _CURRENT_RUNTIME.set(AgentRuntime(TOOL_REGISTRY, self))


class RuntimeExecutorAgent(ToolAwareExecutorAgent):
    def __init__(self):
        super().__init__(TOOL_REGISTRY)


class RuntimeAriaSensor:
    def __init__(self):
        self.delegate = OriginalAriaSensor()

    def capture(self, page) -> str:
        return current_runtime().invoke(
            "coordinator",
            "observe_aria",
            {},
            {"page": page, "aria_sensor": self.delegate},
        )

    def __getattr__(self, name):
        return getattr(self.delegate, name)


class RuntimeVisualSensor:
    def __init__(self):
        self.delegate = OriginalVisualSensor()

    def capture(self, page, step_goal: str = "") -> str:
        return current_runtime().invoke(
            "coordinator",
            "observe_visual",
            {"step_goal": step_goal},
            {"page": page, "visual_sensor": self.delegate},
        )

    def __getattr__(self, name):
        return getattr(self.delegate, name)


class RuntimeVerifierAgent:
    role = "verifier"

    def __init__(self):
        self.delegate = OriginalVerifierAgent()

    def verify(self, page, goal: str, success_criteria: str = "",
               page_state: str = "", action: dict | None = None,
               action_result: dict | None = None):
        return current_runtime().invoke(
            "verifier",
            "verify_page",
            {"goal": goal, "success_criteria": success_criteria},
            {
                "page": page,
                "verifier": self.delegate,
                "page_state": page_state,
                "action": action,
                "action_result": action_result,
            },
        )


def _runtime_playwright_executor_class(executor_class):
    class RuntimePlaywrightExecutor:
        def __init__(self, page, visual_sensor=None, screenshot_dir=None):
            self.delegate = executor_class(
                page,
                visual_sensor=visual_sensor,
                screenshot_dir=screenshot_dir,
            )

        def execute(self, action_info: dict) -> dict:
            return current_runtime().invoke_action(
                "executor",
                action_info,
                {"browser_executor": self.delegate},
            )

        def __getattr__(self, name):
            return getattr(self.delegate, name)

    RuntimePlaywrightExecutor.__name__ = f"Runtime{executor_class.__name__}"
    return RuntimePlaywrightExecutor


def install_tool_runtime() -> None:
    """为当前进程的协作 Runner 安装一次工具运行时。"""
    if getattr(base_runner, "_agent_tool_runtime_installed", False):
        return

    # 此时 v3 已经将安全日志执行器注入 PlaywrightExecutor；运行时包在它外层。
    runtime_executor = _runtime_playwright_executor_class(base_runner.PlaywrightExecutor)
    base_runner.TaskBlackboard = RuntimeTaskBlackboard
    base_runner.ExecutorAgent = RuntimeExecutorAgent
    base_runner.AriaSensor = RuntimeAriaSensor
    base_runner.VisualSensor = RuntimeVisualSensor
    base_runner.VerifierAgent = RuntimeVerifierAgent
    base_runner.PlaywrightExecutor = runtime_executor
    base_runner._agent_tool_runtime_installed = True
    base_runner._agent_tool_registry = TOOL_REGISTRY
