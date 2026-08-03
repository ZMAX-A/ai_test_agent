"""跨步骤任务世界模型与证据账本。

它只保存可审计事实、动作结果和待验证假设，不保存模型的隐藏思维链。模型看到
的是紧凑结构化摘要，从而能在失败后重规划，而不是只根据最后一句错误猜测。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _safe_parameters(parameters: dict) -> dict:
    safe = dict(parameters or {})
    for key in ("value", "password", "username", "token", "api_key"):
        if safe.get(key) not in (None, ""):
            safe[key] = f"<redacted:{len(str(safe[key]))}>"
    return safe


@dataclass
class Evidence:
    claim: str
    source: str
    confidence: float
    goal: str
    created_at: str = field(default_factory=_now)


@dataclass
class ActionOutcome:
    goal: str
    action: str
    parameters: dict
    success: bool
    error_type: str = ""
    message: str = ""
    url_before: str = ""
    url_after: str = ""


@dataclass
class FailureHypothesis:
    hypothesis: str
    evidence: str
    status: str = "open"
    attempts: int = 1


class TaskWorldModel:
    """单条用例范围内的显式事实模型。"""

    def __init__(self, task_id: str, global_goal: str):
        self.task_id = task_id
        self.global_goal = global_goal
        self.current_goal = ""
        self.current_url = ""
        self.current_title = ""
        self.observation_summary = ""
        self.visited_pages: dict[str, dict] = {}
        self.evidence: list[Evidence] = []
        self.actions: list[ActionOutcome] = []
        self.hypotheses: list[FailureHypothesis] = []
        self.replans: list[dict] = []
        self.proposals: list[dict] = []
        self.verification_failures = 0
        self._last_replan_action_count = -1

    def begin_goal(self, goal: str) -> None:
        if goal == self.current_goal:
            return
        self.current_goal = goal
        self.verification_failures = 0
        self._last_replan_action_count = -1

    def observe(self, context: dict) -> None:
        self.begin_goal(str(context.get("step_goal", "")))
        self.current_url = str(context.get("page_url", ""))
        self.current_title = str(context.get("page_title", ""))
        state = " ".join(str(context.get("page_state", "")).split())
        self.observation_summary = state[:1200]
        if self.current_url:
            self.visited_pages[self.current_url] = {
                "title": self.current_title,
                "last_goal": self.current_goal,
                "observation": self.observation_summary[:400],
            }

    def record_proposal(self, action: dict, critic: str = "") -> None:
        self.proposals.append({
            "goal": self.current_goal,
            "action": action.get("action", ""),
            "parameters": _safe_parameters(action.get("parameters", {})),
            "critic": critic[:300],
        })

    def record_action(self, action: dict, result: dict,
                      url_before: str = "", url_after: str = "") -> None:
        outcome = ActionOutcome(
            goal=self.current_goal,
            action=str(action.get("action", "")),
            parameters=_safe_parameters(action.get("parameters", {})),
            success=bool(result.get("success")),
            error_type=str(result.get("error_type", "")),
            message=str(result.get("message", ""))[:300],
            url_before=url_before,
            url_after=url_after,
        )
        self.actions.append(outcome)
        if not outcome.success:
            self._add_failure_hypothesis(outcome)

    def record_verification(self, verification, action: dict | None = None) -> None:
        if verification.passed:
            self.verification_failures = 0
            for claim in verification.evidence:
                self.evidence.append(Evidence(
                    claim=str(claim)[:300],
                    source="verifier",
                    confidence=float(verification.confidence),
                    goal=self.current_goal,
                ))
            for hypothesis in self.hypotheses:
                if hypothesis.status == "open":
                    hypothesis.status = "resolved"
            return
        if action:
            self.verification_failures += 1
            reason = str(verification.reason or "缺少完成证据")[:200]
            self._merge_hypothesis("动作成功但尚未证明目标完成", reason)

    def _add_failure_hypothesis(self, outcome: ActionOutcome) -> None:
        mapping = {
            "ELEMENT_NOT_FOUND": "定位证据与当前页面结构不一致",
            "NOT_VISIBLE": "元素存在但不可见或被遮挡",
            "TIMEOUT": "页面未就绪、定位错误或存在前置阻挡",
            "NOT_ENABLED": "目标控件尚未满足可操作条件",
            "TOOL_ARGUMENT_ERROR": "候选动作参数违反工具协议",
        }
        hypothesis = mapping.get(outcome.error_type, "当前操作假设未产生预期效果")
        self._merge_hypothesis(hypothesis, outcome.message)

    def _merge_hypothesis(self, hypothesis: str, evidence: str) -> None:
        for item in self.hypotheses:
            if item.hypothesis == hypothesis and item.status == "open":
                item.attempts += 1
                item.evidence = evidence[:300]
                return
        self.hypotheses.append(FailureHypothesis(hypothesis, evidence[:300]))

    def should_replan(self) -> bool:
        current_actions = [a for a in self.actions if a.goal == self.current_goal]
        if not current_actions:
            return False
        if self._last_replan_action_count == len(self.actions):
            return False
        return (not current_actions[-1].success) or self.verification_failures >= 2

    def record_replan(self, plan: dict) -> None:
        self.replans.append({
            "goal": self.current_goal,
            "diagnosis": str(plan.get("diagnosis", ""))[:300],
            "next_strategy": str(plan.get("next_strategy", ""))[:500],
            "avoid": list(plan.get("avoid", []))[:5],
            "success_probe": str(plan.get("success_probe", ""))[:300],
        })
        self._last_replan_action_count = len(self.actions)

    def recovery_hints(self) -> list[str]:
        hints = []
        for hypothesis in self.hypotheses[-3:]:
            if hypothesis.status != "open":
                continue
            hints.append(f"待验证假设: {hypothesis.hypothesis}；依据: {hypothesis.evidence}")
        return hints

    def compact_snapshot(self) -> dict[str, Any]:
        current_actions = [a for a in self.actions if a.goal == self.current_goal]
        return {
            "global_goal": self.global_goal,
            "current_goal": self.current_goal,
            "current_page": {"url": self.current_url, "title": self.current_title},
            "visited_page_count": len(self.visited_pages),
            "recent_actions": [asdict(item) for item in current_actions[-5:]],
            "verified_evidence": [asdict(item) for item in self.evidence[-5:]],
            "open_hypotheses": [
                asdict(item) for item in self.hypotheses[-5:] if item.status == "open"
            ],
            "recent_replans": self.replans[-2:],
            "needs_replan": self.should_replan(),
        }
