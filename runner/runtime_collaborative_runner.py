"""带 ToolRegistry 与 Agent 权限隔离的协作测试 Runner。"""

from runner.collaborative_runner_v4 import CollaborativeTestRunnerV4
from runner.tool_runtime_integration import TOOL_REGISTRY, install_tool_runtime


install_tool_runtime()


class RuntimeCollaborativeTestRunner(CollaborativeTestRunnerV4):
    @staticmethod
    def capability_manifest() -> dict[str, list[str]]:
        return {
            role: TOOL_REGISTRY.names_for(role)
            for role in ("planner", "coordinator", "executor", "verifier")
        }
