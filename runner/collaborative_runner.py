"""多 Agent v2 Runner。

复用稳定的 MultiAgentTestRunner，只替换步骤推理策略，保持浏览器、黑板和
Verifier 协议一致。
"""

import runner.multi_agent_runner as base_runner

from core.collaborative_reasoning import CollaborativeStepReasoningState


# MultiAgentTestRunner 在运行时从模块全局取该类；显式注入 v2 策略。
base_runner.StepReasoningState = CollaborativeStepReasoningState


class CollaborativeTestRunner(base_runner.MultiAgentTestRunner):
    pass
