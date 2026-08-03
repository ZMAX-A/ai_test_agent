"""多 Agent 测试编排器。"""

from __future__ import annotations

from dataclasses import dataclass
import time

from config.settings import settings


@dataclass
class CoordinationDecision:
    route: str
    reason: str
    stop: bool = False


class CoordinatorAgent:
    """负责路由、预算和停止条件，不直接操作浏览器。"""

    role = "coordinator"

    def choose_perception(self, reasoning, fail_count: int) -> CoordinationDecision:
        if fail_count > 0 or reasoning.should_use_visual():
            return CoordinationDecision("visual_sensor", "动作失败或页面连续无变化，升级视觉感知")
        return CoordinationDecision("aria_sensor", "优先使用低成本语义感知")

    def before_decision(self, blackboard, deadline: float,
                        api_call_count: int) -> CoordinationDecision:
        if time.monotonic() >= deadline:
            return CoordinationDecision("abort", "探索任务达到总时限", stop=True)
        if api_call_count >= settings.MAX_API_CALLS:
            return CoordinationDecision("abort", "模型调用预算耗尽", stop=True)
        return CoordinationDecision("executor", "需要 Executor 提出下一候选动作")

    def after_verification(self, verification) -> CoordinationDecision:
        if verification.passed:
            return CoordinationDecision("complete_step", "Verifier 已提供独立完成证据", stop=True)
        if verification.recoverable:
            return CoordinationDecision("executor", verification.next_action or "继续收集证据")
        return CoordinationDecision("abort_step", verification.reason, stop=True)
