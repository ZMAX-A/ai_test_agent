"""Evidence-aware evaluation metrics for production Web-agent runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import mean
from typing import Any

from core.credential_vault import CredentialVault


SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _average(values: list[float | int]) -> float:
    return round(float(mean(values)), 3) if values else 0.0


def _trace_events(result: dict) -> list[dict]:
    events: list[dict] = []
    for trace in result.get("trace", []) or []:
        events.extend(trace.get("agent_events", []) or [])
    return events


def _verifications(result: dict) -> list[dict]:
    verifications = []
    for step in result.get("results", []) or []:
        verification = step.get("verification")
        if isinstance(verification, dict) and verification:
            verifications.append(verification)
    return verifications


def _expected_step_count(case: dict, result_steps: list[dict]) -> int:
    declared = case.get("expected_step_count")
    if declared is None:
        parsed = case.get("_steps_parsed")
        if isinstance(parsed, (list, tuple)):
            return len(parsed)
        return len(result_steps)
    try:
        return max(0, int(declared))
    except (TypeError, ValueError):
        return 0


@dataclass(frozen=True)
class EvaluationRecord:
    case_id: str
    task_name: str
    module: str
    run_index: int
    success: bool
    evidence_backed: bool
    unsupported_pass: bool
    recovered: bool
    action_count: int
    failed_action_count: int
    recovery_count: int
    critic_revision_count: int
    verification_count: int
    evidence_count: int
    model_calls: int
    event_count: int
    duration_seconds: float
    error: str
    created_at: str

    @classmethod
    def from_result(
        cls,
        case: dict,
        result: dict,
        duration_seconds: float,
        run_index: int = 1,
    ) -> "EvaluationRecord":
        vault = CredentialVault()
        success = bool(result.get("success"))
        result_steps = result.get("results", []) or []
        verifications = _verifications(result)
        evidence_count = sum(
            len(item.get("evidence", []) or []) for item in verifications
        )
        expected_step_count = _expected_step_count(case, result_steps)
        all_steps_verified = (
            expected_step_count > 0
            and len(result_steps) == expected_step_count
            and len(verifications) == expected_step_count
            and len(result.get("trace", []) or []) == expected_step_count
            and all(
                bool(item.get("passed"))
                and bool(item.get("evidence", []) or [])
                for item in verifications
            )
        )
        evidence_backed = success and all_steps_verified
        events = _trace_events(result)
        failed_action_count = sum(
            1
            for event in events
            if event.get("event") == "action_executed"
            and not bool((event.get("payload") or {}).get("success"))
        )
        recovery_count = sum(
            1
            for event in events
            if event.get("event") == "plan_revised"
        )
        critic_revision_count = sum(
            1
            for event in events
            if event.get("event") in {"action_revised", "action_replaced"}
        )
        attempted_recovery = failed_action_count > 0 or recovery_count > 0
        failed_steps = [
            step for step in result.get("results", []) or []
            if not bool(step.get("success"))
        ]
        error = ""
        if failed_steps:
            error = vault.sanitize_text(str(failed_steps[0].get("msg", "")))[:500]

        collaboration = result.get("collaboration", {}) or {}
        action_count = sum(
            len(trace.get("all_actions", []) or [])
            for trace in result.get("trace", []) or []
        )
        return cls(
            case_id=vault.sanitize_text(
                str(case.get("case_id", "unnamed"))
            ),
            task_name=vault.sanitize_text(
                str(case.get("case_name", case.get("case_id", "unnamed")))
            ),
            module=vault.sanitize_text(str(case.get("module", ""))),
            run_index=max(1, int(run_index)),
            success=success,
            evidence_backed=evidence_backed,
            unsupported_pass=success and not evidence_backed,
            recovered=success and attempted_recovery,
            action_count=action_count,
            failed_action_count=failed_action_count,
            recovery_count=recovery_count,
            critic_revision_count=critic_revision_count,
            verification_count=len(verifications),
            evidence_count=evidence_count,
            model_calls=int(collaboration.get("model_calls", 0) or 0),
            event_count=int(collaboration.get("event_count", len(events)) or 0),
            duration_seconds=round(max(0.0, float(duration_seconds)), 3),
            error=error,
            created_at=_now(),
        )

    @property
    def recovery_attempted(self) -> bool:
        return self.failed_action_count > 0 or self.recovery_count > 0


def summarize(records: list[EvaluationRecord]) -> dict[str, Any]:
    total = len(records)
    successes = sum(record.success for record in records)
    evidence_backed = sum(record.evidence_backed for record in records)
    unsupported = sum(record.unsupported_pass for record in records)
    recovery_attempts = sum(record.recovery_attempted for record in records)
    recovered = sum(record.recovered for record in records)

    grouped: dict[tuple[str, str], dict[int, list[bool]]] = {}
    for record in records:
        key = (record.module, record.case_id)
        runs = grouped.setdefault(key, {})
        runs.setdefault(record.run_index, []).append(record.success)
    repeated = [
        [
            outcome for outcomes in runs.values() for outcome in outcomes
        ]
        for runs in grouped.values()
        if len(runs) > 1
    ]

    reproducible = sum(len(set(outcomes)) == 1 for outcomes in repeated)

    return {
        "total_runs": total,
        "unique_cases": len(grouped),
        "successful_runs": successes,
        "failed_runs": total - successes,
        "pass_rate": _rate(successes, total),
        "evidence_backed_pass_rate": _rate(evidence_backed, total),
        "unsupported_pass_count": unsupported,
        "unsupported_pass_rate": _rate(unsupported, total),
        "recovery_attempt_count": recovery_attempts,
        "recovered_run_count": recovered,
        "recovery_success_rate": _rate(recovered, recovery_attempts),
        "repeated_case_count": len(repeated),
        "reproducibility_rate": _rate(reproducible, len(repeated)),
        "average_actions": _average([record.action_count for record in records]),
        "average_model_calls": _average([record.model_calls for record in records]),
        "average_critic_revisions": _average(
            [record.critic_revision_count for record in records]
        ),
        "average_duration_seconds": _average(
            [record.duration_seconds for record in records]
        ),
    }


class EvaluationSuite:
    def __init__(self, name: str):
        self.name = CredentialVault().sanitize_text(
            str(name or "web-agent-benchmark")
        )
        self.records: list[EvaluationRecord] = []

    def record(
        self,
        case: dict,
        result: dict,
        duration_seconds: float,
        run_index: int = 1,
    ) -> EvaluationRecord:
        item = EvaluationRecord.from_result(
            case,
            result,
            duration_seconds,
            run_index,
        )
        self.records.append(item)
        return item

    def report(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "suite": self.name,
            "generated_at": _now(),
            "summary": summarize(self.records),
            "records": [asdict(record) for record in self.records],
        }

    def write(self, path: str | Path) -> dict[str, Any]:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        report = self.report()
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(target)
        return report


def format_summary(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})

    def percent(value: float | None) -> str:
        return "n/a" if value is None else f"{value * 100:.1f}%"

    return "\n".join(
        [
            "=" * 54,
            f"  Benchmark: {report.get('suite', '-')}",
            f"  Runs: {summary.get('successful_runs', 0)}/{summary.get('total_runs', 0)} passed",
            f"  Evidence-backed pass rate: {percent(summary.get('evidence_backed_pass_rate'))}",
            f"  Unsupported passes: {summary.get('unsupported_pass_count', 0)}",
            f"  Recovery success rate: {percent(summary.get('recovery_success_rate'))}",
            f"  Reproducibility: {percent(summary.get('reproducibility_rate'))}",
            f"  Avg actions/model calls/critic revisions: "
            f"{summary.get('average_actions', 0)}/"
            f"{summary.get('average_model_calls', 0)}/"
            f"{summary.get('average_critic_revisions', 0)}",
            f"  Avg duration: {summary.get('average_duration_seconds', 0)}s",
            "=" * 54,
        ]
    )


def report_passed(report: dict[str, Any]) -> bool:
    summary = report.get("summary", {})
    return (
        int(summary.get("total_runs", 0)) > 0
        and int(summary.get("failed_runs", 0)) == 0
        and int(summary.get("unsupported_pass_count", 0)) == 0
    )


__all__ = [
    "EvaluationRecord",
    "EvaluationSuite",
    "SCHEMA_VERSION",
    "format_summary",
    "report_passed",
    "summarize",
]
