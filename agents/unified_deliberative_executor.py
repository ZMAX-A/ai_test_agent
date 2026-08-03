"""显式依赖版 Deliberative Executor，不依赖 activation 模块。"""

from agents.deliberative_executor_agent import DeliberativeExecutorAgent
from core.tool_registry import ToolRegistry
from core.unified_context import current_runtime, current_world_model


class UnifiedDeliberativeExecutorAgent(DeliberativeExecutorAgent):
    def __init__(self, registry: ToolRegistry):
        super().__init__(registry)

    @staticmethod
    def _runtime_and_world():
        return current_runtime(), current_world_model()
