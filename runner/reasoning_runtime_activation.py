"""将世界模型、Critic 和 Replanner 接入现有 AgentRuntime。"""

from __future__ import annotations

from contextvars import ContextVar

import runner.multi_agent_runner as base_runner

from agents.deliberative_executor_agent import DeliberativeExecutorAgent
from core.task_world_model import TaskWorldModel
from runner.agent_runtime_activation import AgentRuntimeTestRunner
from runner.tool_runtime_integration import TOOL_REGISTRY


_CURRENT_WORLD_MODEL: ContextVar[TaskWorldModel | None] = ContextVar(
    "web_test_task_world_model", default=None
)


def current_world_model() -> TaskWorldModel:
    model = _CURRENT_WORLD_MODEL.get()
    if model is None:
        raise RuntimeError("任务世界模型尚未绑定")
    return model


class ReasoningExecutorAgent(DeliberativeExecutorAgent):
    def __init__(self):
        super().__init__(TOOL_REGISTRY)


def _world_model_executor_class(executor_class):
    class WorldModelExecutor:
        def __init__(self, page, visual_sensor=None, screenshot_dir=None):
            self.delegate = executor_class(
                page,
                visual_sensor=visual_sensor,
                screenshot_dir=screenshot_dir,
            )

        def execute(self, action_info: dict) -> dict:
            try:
                url_before = self.delegate.page.url
            except Exception:
                url_before = ""
            result = self.delegate.execute(action_info)
            try:
                url_after = self.delegate.page.url
            except Exception:
                url_after = ""
            current_world_model().record_action(
                action_info, result, url_before=url_before, url_after=url_after
            )
            return result

        def __getattr__(self, name):
            return getattr(self.delegate, name)

    WorldModelExecutor.__name__ = f"WorldModel{executor_class.__name__}"
    return WorldModelExecutor


def _world_model_verifier_class(verifier_class):
    class WorldModelVerifier:
        role = "verifier"

        def __init__(self):
            self.delegate = verifier_class()

        def verify(self, page, goal: str, success_criteria: str = "",
                   page_state: str = "", action: dict | None = None,
                   action_result: dict | None = None):
            model = current_world_model()
            model.begin_goal(goal)
            result = self.delegate.verify(
                page, goal, success_criteria, page_state,
                action=action, action_result=action_result,
            )
            model.record_verification(result, action=action)
            return result

        def __getattr__(self, name):
            return getattr(self.delegate, name)

    WorldModelVerifier.__name__ = f"WorldModel{verifier_class.__name__}"
    return WorldModelVerifier


def install_reasoning_runtime() -> None:
    if getattr(base_runner, "_deliberative_reasoning_installed", False):
        return

    previous_blackboard_init = base_runner.TaskBlackboard.__init__

    def reasoning_blackboard_init(self, *args, **kwargs):
        previous_blackboard_init(self, *args, **kwargs)
        model = TaskWorldModel(self.task_id, self.global_goal)
        _CURRENT_WORLD_MODEL.set(model)
        self.publish("coordinator", "world_model_initialized", task_id=self.task_id)

    base_runner.TaskBlackboard.__init__ = reasoning_blackboard_init
    base_runner.ExecutorAgent = ReasoningExecutorAgent
    base_runner.PlaywrightExecutor = _world_model_executor_class(base_runner.PlaywrightExecutor)
    base_runner.VerifierAgent = _world_model_verifier_class(base_runner.VerifierAgent)
    base_runner._deliberative_reasoning_installed = True


install_reasoning_runtime()


class ReasoningAgentRunner(AgentRuntimeTestRunner):
    @staticmethod
    def capability_manifest() -> dict[str, list[str]]:
        manifest = AgentRuntimeTestRunner.capability_manifest()
        manifest["critic"] = []
        manifest["replanner"] = []
        return manifest
