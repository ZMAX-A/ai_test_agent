"""带世界模型、Critic 和动态 Replanner 的执行决策 Agent。"""

from __future__ import annotations

import json

from agents.critic_agent import CriticAgent
from agents.replanner_agent import ReplannerAgent
from agents.tool_aware_executor_agent import ToolAwareExecutorAgent
from core.tool_registry import ToolRegistry


class DeliberativeExecutorAgent(ToolAwareExecutorAgent):
    role = "executor"

    def __init__(self, registry: ToolRegistry):
        super().__init__(registry)
        self.critic = CriticAgent()
        self.replanner = ReplannerAgent()

    @staticmethod
    def _runtime_and_world():
        from runner.tool_runtime_integration import current_runtime
        from runner.reasoning_runtime_activation import current_world_model
        return current_runtime(), current_world_model()

    @staticmethod
    def _audit(runtime, role: str, event: str, **payload) -> None:
        runtime.blackboard.publish(role, event, **payload)

    def ask(self, context: dict) -> dict:
        runtime, world = self._runtime_and_world()
        world.observe(context)
        working_context = dict(context)
        model_calls = 0

        if world.should_replan():
            snapshot = world.compact_snapshot()
            plan = self.replanner.replan(working_context, snapshot)
            model_calls += self.replanner.last_model_call_count
            world.record_replan(plan)
            directive = (
                f"动态重规划诊断: {plan['diagnosis']}\n"
                f"下一策略: {plan['next_strategy']}\n"
                f"禁止: {'；'.join(plan['avoid'])}\n"
                f"验收探针: {plan['success_probe']}"
            )
            working_context["tried_strategies"] = (
                str(working_context.get("tried_strategies", "")) + "\n" + directive
            )
            self._audit(runtime, "replanner", "plan_revised", plan=plan)

        snapshot = world.compact_snapshot()
        working_context["reasoning_state"] = (
            str(working_context.get("reasoning_state", ""))
            + "\n\n【任务世界模型】\n"
            + json.dumps(snapshot, ensure_ascii=False, indent=2)
        )

        proposal = super().ask(working_context)
        model_calls += self.last_model_call_count
        critique = self.critic.review(proposal, working_context, snapshot)
        model_calls += self.critic.last_model_call_count
        self._audit(
            runtime, "critic", "action_reviewed",
            approved=critique.approved,
            reason=critique.reason,
            confidence=critique.confidence,
            action=proposal,
        )

        final_action = proposal
        if not critique.approved and critique.replacement:
            final_action = critique.replacement
            self._audit(runtime, "critic", "action_replaced", action=final_action)
        elif not critique.approved:
            revision_context = dict(working_context)
            revision_context["tried_strategies"] = (
                str(revision_context.get("tried_strategies", ""))
                + f"\nCritic拒绝上一候选: {critique.reason}。提出不同且证据充分的动作。"
            )
            final_action = super().ask(revision_context)
            model_calls += self.last_model_call_count
            self._audit(runtime, "executor", "action_revised", action=final_action)

        world.record_proposal(final_action, critique.reason)
        self.last_model_call_count = model_calls

        # 旧 Runner 为每次 ask 预记一次调用；这里只补记 Critic/Replanner/修订调用。
        if model_calls > 1:
            runtime.blackboard.model_calls += model_calls - 1
        return final_action
