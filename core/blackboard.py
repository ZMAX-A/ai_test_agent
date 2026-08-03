"""多 Agent 协作共享黑板。

Agent 不直接互相传递自由文本，而是通过事件和结构化状态协作。黑板只保留
紧凑摘要，并对输入值做脱敏，避免账号、密码进入后续模型上下文。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
from typing import Any


SENSITIVE_KEYS = {"value", "password", "username", "token", "api_key"}


def _redact(value: Any, key: str = "") -> Any:
    if key.lower() in SENSITIVE_KEYS and value not in (None, ""):
        return f"<redacted:{len(str(value))}>"
    if isinstance(value, dict):
        return {k: _redact(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    text = str(value)
    return text[:300] if len(text) > 300 else value


@dataclass
class AgentEvent:
    sequence: int
    role: str
    event: str
    step: int
    payload: dict = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


@dataclass
class TaskBlackboard:
    task_id: str
    task_name: str
    global_goal: str
    status: str = "running"
    current_step: int = 0
    current_goal: str = ""
    success_criteria: str = ""
    model_calls: int = 0
    events: list[AgentEvent] = field(default_factory=list)
    latest_verification: dict = field(default_factory=dict)

    def publish(self, role: str, event: str, **payload) -> AgentEvent:
        item = AgentEvent(
            sequence=len(self.events) + 1,
            role=role,
            event=event,
            step=self.current_step,
            payload=_redact(payload),
        )
        self.events.append(item)
        return item

    def start_step(self, step: int, goal: str, success_criteria: str = "") -> None:
        self.current_step = step
        self.current_goal = goal
        self.success_criteria = success_criteria
        self.latest_verification = {}
        self.publish(
            "coordinator", "step_assigned",
            goal=goal, success_criteria=success_criteria or "未显式提供",
        )

    def record_verification(self, result: dict) -> None:
        self.latest_verification = _redact(result)
        self.publish("verifier", "verification", **result)

    def events_for_step(self, step: int) -> list[dict]:
        return [asdict(event) for event in self.events if event.step == step]

    def compact_context(self, limit: int = 8) -> str:
        recent = [
            {
                "role": event.role,
                "event": event.event,
                "payload": event.payload,
            }
            for event in self.events[-limit:]
        ]
        return json.dumps({
            "task": self.task_name,
            "step": self.current_step,
            "goal": self.current_goal,
            "success_criteria": self.success_criteria,
            "model_calls": self.model_calls,
            "latest_verification": self.latest_verification,
            "recent_events": recent,
        }, ensure_ascii=False, indent=2)

    def summary(self) -> dict:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "model_calls": self.model_calls,
            "event_count": len(self.events),
            "agents": sorted({event.role for event in self.events}),
        }
