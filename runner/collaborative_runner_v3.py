"""多 Agent v3 Runner：认证恢复 + 安全日志。"""

import runner.multi_agent_runner as base_runner

from core.authenticated_collaborative_reasoning import AuthenticatedCollaborativeStepReasoningState
from executor.secure_playwright_exec import SecurePlaywrightExecutor


base_runner.StepReasoningState = AuthenticatedCollaborativeStepReasoningState
base_runner.PlaywrightExecutor = SecurePlaywrightExecutor


class CollaborativeTestRunnerV3(base_runner.MultiAgentTestRunner):
    pass
