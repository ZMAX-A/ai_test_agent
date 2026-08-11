"""Safe, resumable curriculum execution and evidence-gated experience learning."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Callable
from urllib.parse import urlparse
from uuid import uuid4

from config.settings import settings
from core.credential_vault import CredentialVault
from core.training_memory import (
    TrainingMemory,
    training_case_hash,
)
from loader.curriculum_loader import (
    CurriculumCatalog,
    CurriculumCase,
    PRIORITY_ORDER,
    load_curriculum,
)
from web_agent.evaluation import EvaluationRecord


@dataclass(frozen=True)
class TrainingOptions:
    headless: bool = False
    priorities: tuple[str, ...] = ()
    modules: tuple[str, ...] = ()
    case_ids: tuple[str, ...] = ()
    limit: int = 0
    resume: bool = False
    allow_mutations: bool = False
    allow_destructive: bool = False
    holdout_percent: int = 15
    include_holdout: bool = False
    repeat: int = 1
    fail_fast: bool = False
    retry_quarantined: bool = False


def _is_holdout(case_id: str, percent: int) -> bool:
    import hashlib

    bounded = min(50, max(0, int(percent)))
    bucket = int(hashlib.sha256(case_id.encode("utf-8")).hexdigest()[:8], 16) % 100
    return bucket < bounded


def select_curriculum(
    catalog: CurriculumCatalog,
    options: TrainingOptions,
) -> tuple[list[CurriculumCase], list[dict]]:
    errors = {}
    for issue in catalog.errors:
        if issue.case_id:
            errors.setdefault(issue.case_id, []).append(issue.message)
    selected, skipped = [], []
    priorities = {value.upper() for value in options.priorities}
    modules = set(options.modules)
    case_ids = set(options.case_ids)

    for case in sorted(
        catalog.cases,
        key=lambda item: (PRIORITY_ORDER.get(item.priority, 99), item.row),
    ):
        reason = ""
        if priorities and case.priority not in priorities:
            reason = "priority_filter"
        elif modules and case.module not in modules:
            reason = "module_filter"
        elif case_ids and case.case_id not in case_ids:
            reason = "case_filter"
        elif not case.enabled:
            reason = "source_disabled"
        elif case.case_id in errors:
            reason = "invalid_case"
        elif case.capability_gaps:
            reason = "capability_gap"
        elif case.risk == "negative_auth":
            reason = "negative_auth_blocked"
        elif case.risk == "destructive" and not options.allow_destructive:
            reason = "destructive_blocked"
        elif case.risk == "mutation" and not options.allow_mutations:
            reason = "mutation_blocked"
        elif (
            not options.include_holdout
            and _is_holdout(case.case_id, options.holdout_percent)
        ):
            reason = "holdout"
        if reason:
            skipped.append({
                "case_id": case.case_id,
                "module": case.module,
                "priority": case.priority,
                "risk": case.risk,
                "reason": reason,
                "details": list(case.capability_gaps or errors.get(case.case_id, [])),
            })
        else:
            selected.append(case)

    if options.limit > 0:
        overflow = selected[options.limit:]
        selected = selected[:options.limit]
        skipped.extend({
            "case_id": case.case_id,
            "module": case.module,
            "priority": case.priority,
            "risk": case.risk,
            "reason": "limit",
            "details": [],
        } for case in overflow)
    return selected, skipped


def _write_report(path: str | Path, report: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    safe_report = CredentialVault().sanitize(report)
    temporary.write_text(
        json.dumps(safe_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(target)


def _create_training_runner(headless: bool):
    from dataclasses import replace

    from web_agent.commands import production_dependencies
    from web_agent.runner import ProductionRunner

    dependencies = replace(
        production_dependencies(),
        case_writer=lambda **_kwargs: None,
    )
    return ProductionRunner(headless=headless, dependencies=dependencies)


def _initial_report(
    catalog: CurriculumCatalog,
    options: TrainingOptions,
    selected: list[CurriculumCase],
    skipped: list[dict],
    run_id: str,
) -> dict:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {
            **catalog.summary(),
            "errors_detail": [issue.to_dict() for issue in catalog.errors],
            "warnings_detail": [issue.to_dict() for issue in catalog.warnings],
        },
        "policy": asdict(options),
        "selection": {
            "selected": [case.case_id for case in selected],
            "selected_count": len(selected),
            "skipped_count": len(skipped),
            "skipped": skipped,
        },
        "results": [],
        "summary": {
            "executed": 0,
            "passed_verified": 0,
            "failed": 0,
            "unsupported_pass": 0,
            "unpromotable_pass": 0,
            "infra_error": 0,
        },
    }


def run_training(
    filepath: str,
    options: TrainingOptions,
    output: str = "report/training/latest.json",
    memory_db: str = "memory/web_agent_training.db",
    validate_only: bool = False,
    runner_factory: Callable[[bool], object] | None = None,
) -> dict:
    catalog = load_curriculum(filepath, settings.LOGIN_URL)
    selected, skipped = select_curriculum(catalog, options)
    initial_selected_count = len(selected)
    base_run_id = uuid4().hex
    report = _initial_report(catalog, options, selected, skipped, base_run_id)
    if validate_only:
        report["status"] = "validated" if selected else "no_runnable_cases"
        _write_report(output, report)
        return report

    memory = TrainingMemory(memory_db)
    case_hashes = {
        case.case_id: training_case_hash(case)
        for case in catalog.cases
    }
    active_case_hashes = tuple(case_hashes.values())
    if not options.retry_quarantined:
        quarantined = memory.quarantined_case_ids(
            catalog.source_hash, case_hashes
        )
        remaining = []
        for case in selected:
            if case.case_id in quarantined:
                report["selection"]["skipped"].append({
                    "case_id": case.case_id,
                    "module": case.module,
                    "priority": case.priority,
                    "risk": case.risk,
                    "reason": "quarantined",
                    "details": ["连续业务失败，等待修正课程或显式重试"],
                })
            else:
                remaining.append(case)
        selected = remaining
        report["selection"]["selected"] = [
            case.case_id for case in selected
        ]
        report["selection"]["selected_count"] = len(selected)
        report["selection"]["skipped_count"] = len(
            report["selection"]["skipped"]
        )
    if options.resume:
        completed = memory.promoted_case_ids(
            catalog.source_hash, case_hashes
        )
        remaining = []
        for case in selected:
            if case.case_id in completed:
                report["selection"]["skipped"].append({
                    "case_id": case.case_id,
                    "module": case.module,
                    "priority": case.priority,
                    "risk": case.risk,
                    "reason": "resume_promoted",
                    "details": [],
                })
            else:
                remaining.append(case)
        selected = remaining
        report["selection"]["selected"] = [case.case_id for case in selected]
        report["selection"]["selected_count"] = len(selected)
        report["selection"]["skipped_count"] = len(report["selection"]["skipped"])

    if not selected:
        resume_skips = sum(
            item.get("reason") == "resume_promoted"
            for item in report["selection"]["skipped"]
        )
        report["status"] = (
            "completed"
            if options.resume
            and initial_selected_count > 0
            and resume_skips == initial_selected_count
            else "no_runnable_cases"
        )
        report["memory"] = memory.stats(
            catalog.source_hash, active_case_hashes
        )
        _write_report(output, report)
        return report

    factory = runner_factory or _create_training_runner
    stop = False
    for replay_index in range(1, max(1, int(options.repeat)) + 1):
        run_id = f"{base_run_id}:{replay_index}"
        for case in selected:
            compiled_steps = case.runner_steps()
            started = time.monotonic()
            try:
                system = urlparse(case.start_url).netloc or "unknown"
                experience = memory.promoted_context(
                    system,
                    case.module,
                    source_hash=catalog.source_hash,
                    allowed_case_hashes=active_case_hashes,
                )
                result = factory(options.headless).run_case(
                    task_name=case.case_name,
                    steps=compiled_steps,
                    start_url=case.start_url,
                    module=case.module,
                    preconditions=case.preconditions,
                    experience_context=experience,
                )
            except Exception as exc:
                result = {
                    "success": False,
                    "results": [{
                        "success": False,
                        "msg": f"{type(exc).__name__}: {exc}",
                        "verification": {},
                    }],
                    "trace": [],
                    "collaboration": {},
                }
            duration = time.monotonic() - started
            evaluation_case = case.evaluation_case()
            evaluation_case["expected_step_count"] = len(compiled_steps)
            evaluation = EvaluationRecord.from_result(
                evaluation_case, result, duration, replay_index
            )
            memory_state = memory.record_attempt(
                run_id, catalog.source_hash, case, evaluation, result
            )
            item = {
                **asdict(evaluation),
                "risk": case.risk,
                "priority": case.priority,
                "replay_index": replay_index,
                **memory_state,
            }
            report["results"].append(item)
            report["summary"]["executed"] += 1
            report["summary"][memory_state["outcome"]] += 1
            report["memory"] = memory.stats(
                catalog.source_hash, active_case_hashes
            )
            _write_report(output, report)
            print(
                f"[TRAIN] {case.case_id} outcome={memory_state['outcome']} "
                f"memory={memory_state['experience_status']} "
                f"verified={memory_state['verified_successes']}"
            )
            if options.fail_fast and memory_state["outcome"] != "passed_verified":
                stop = True
                break
        if stop:
            break

    report["status"] = (
        "completed" if report["summary"]["failed"] == 0
        and report["summary"]["unsupported_pass"] == 0
        and report["summary"]["unpromotable_pass"] == 0
        and report["summary"]["infra_error"] == 0
        else "completed_with_failures"
    )
    report["memory"] = memory.stats(
        catalog.source_hash, active_case_hashes
    )
    _write_report(output, report)
    return report


def format_training_summary(report: dict) -> str:
    source, selection, summary = (
        report.get("source", {}),
        report.get("selection", {}),
        report.get("summary", {}),
    )
    return "\n".join([
        "=" * 58,
        f"  Curriculum rows: {source.get('total', 0)} "
        f"(enabled={source.get('enabled', 0)}, disabled={source.get('disabled', 0)})",
        f"  Selected/skipped: {selection.get('selected_count', 0)}/"
        f"{selection.get('skipped_count', 0)}",
        f"  Executed: {summary.get('executed', 0)}",
        f"  Verified/failed/unsupported/unpromotable/infra: "
        f"{summary.get('passed_verified', 0)}/"
        f"{summary.get('failed', 0)}/"
        f"{summary.get('unsupported_pass', 0)}/"
        f"{summary.get('unpromotable_pass', 0)}/"
        f"{summary.get('infra_error', 0)}",
        f"  Experience memory: {report.get('memory', {}).get('experiences', {})}",
        f"  Status: {report.get('status', '-')}",
        "=" * 58,
    ])


__all__ = [
    "TrainingOptions", "format_training_summary", "run_training",
    "select_curriculum",
]