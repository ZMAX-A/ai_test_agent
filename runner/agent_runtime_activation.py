"""Tool Runtime 的最终启动激活层。

TaskBlackboard 是 dataclass，基础类生成的 __init__ 不会调用后来添加的
__post_init__。这里在 Runner 创建任何任务前，为同一个代理类安装显式构造器，
确保每条用例都有独立 AgentRuntime 和审计黑板。
"""

import runner.multi_agent_runner as base_runner

from core.agent_runtime import AgentRuntime
from core.blackboard import TaskBlackboard as OriginalTaskBlackboard
from runner.runtime_collaborative_runner import RuntimeCollaborativeTestRunner
from runner.tool_runtime_integration import (
    TOOL_REGISTRY,
    RuntimeTaskBlackboard,
    _CURRENT_RUNTIME,
)


def _runtime_blackboard_init(self, *args, **kwargs):
    OriginalTaskBlackboard.__init__(self, *args, **kwargs)
    _CURRENT_RUNTIME.set(AgentRuntime(TOOL_REGISTRY, self))


RuntimeTaskBlackboard.__init__ = _runtime_blackboard_init
base_runner.TaskBlackboard = RuntimeTaskBlackboard


class AgentRuntimeTestRunner(RuntimeCollaborativeTestRunner):
    """推荐使用的下一代协作 Runner。"""

    pass
