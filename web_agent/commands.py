"""Single production CLI and dependency composition."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
import time
from typing import Callable, Sequence

from agents.planner_agent import PlannerAgent
from core.credential_vault import CredentialVault
from loader.excel_loader import load_excel_cases
from web_agent.auth import AuthenticationPolicy
from web_agent.browser import PolicyAwareBrowserExecutor
from web_agent.evaluation import EvaluationSuite, format_summary, report_passed
from web_agent.reasoning import CredentialAwareReasoningState
from web_agent.runner import ProductionRunner, default_dependencies


COMMANDS = {
    "explore", "regression", "benchmark", "train", "capabilities", "doctor"
}


def production_dependencies(policy: AuthenticationPolicy | None = None):
    """Build the only supported production dependency graph."""

    selected = policy or AuthenticationPolicy.from_environment()
    base = default_dependencies(selected)

    def browser_factory(page, visual_sensor):
        return PolicyAwareBrowserExecutor(
            page,
            visual_sensor=visual_sensor,
            auth_policy=selected,
        )

    return replace(
        base,
        reasoning_factory=CredentialAwareReasoningState,
        browser_executor_factory=browser_factory,
    )


def create_runner(headless: bool) -> ProductionRunner:
    return ProductionRunner(
        headless=headless,
        dependencies=production_dependencies(),
    )


def create_benchmark_runner(headless: bool) -> ProductionRunner:
    dependencies = replace(
        production_dependencies(),
        case_writer=lambda **_kwargs: None,
    )
    return ProductionRunner(
        headless=headless,
        dependencies=dependencies,
    )


def _failure_result(exc: Exception) -> dict:
    message = CredentialVault().sanitize_text(
        f"{type(exc).__name__}: {exc}"
    )[:500]
    return {
        "success": False,
        "results": [{"success": False, "msg": message, "verification": {}}],
        "trace": [],
        "collaboration": {},
    }


def run_excel(
    filepath: str,
    headless: bool,
    result_observer: Callable[[dict, dict, float, int], None] | None = None,
    run_index: int = 1,
    runner_factory: Callable[[bool], object] | None = None,
    case_ids: Sequence[str] = (),
) -> list[dict]:
    cases = load_excel_cases(filepath)
    selected_ids = {str(case_id) for case_id in case_ids if case_id}
    if selected_ids:
        cases = [case for case in cases if case.get("case_id") in selected_ids]

    print(f"[WEB-AGENT] data={filepath}, cases={len(cases)}")
    outputs = []
    for case in cases:
        started_at = time.monotonic()
        steps = case.get("_runner_steps") or [
            {"goal": goal} for goal in case.get("_steps_parsed", [])
        ]
        if steps and case.get("expected") and not steps[-1].get("success_criteria"):
            steps[-1]["success_criteria"] = case["expected"]
        try:
            result = (runner_factory or create_runner)(headless).run_case(
                task_name=case.get("case_name", case.get("case_id", "unnamed")),
                steps=steps,
                start_url=case.get("start_url", ""),
                module=case.get("module", ""),
                preconditions=case.get("preconditions", ""),
                source_case_id=case.get("case_id", ""),
            )
        except Exception as exc:
            result = _failure_result(exc)
        outputs.append(result)
        duration_seconds = time.monotonic() - started_at
        if result_observer is not None:
            result_observer(case, result, duration_seconds, run_index)
        collaboration = result.get("collaboration", {})
        print(
            f"[{'PASS' if result['success'] else 'FAIL'}] "
            f"{case.get('case_id')} | "
            f"runner={collaboration.get('runner', '-')} | "
            f"events={collaboration.get('event_count', 0)} | "
            f"model_calls={collaboration.get('model_calls', 0)}"
        )
    return outputs


def run_benchmark(
    filepath: str,
    headless: bool,
    repeat: int,
    output: str,
    suite_name: str,
) -> dict:
    suite = EvaluationSuite(suite_name)
    total_repeats = max(1, int(repeat))
    current_run = 1
    try:
        for run_index in range(1, total_repeats + 1):
            current_run = run_index
            print(f"[BENCHMARK] run={run_index}/{total_repeats}")
            run_excel(
                filepath,
                headless,
                result_observer=suite.record,
                run_index=run_index,
                runner_factory=create_benchmark_runner,
            )
    except Exception as exc:
        suite.record(
            {
                "case_id": "__benchmark_infrastructure__",
                "case_name": "Benchmark infrastructure",
                "module": "infrastructure",
                "expected_step_count": 1,
            },
            _failure_result(exc),
            0.0,
            current_run,
        )
    report = suite.write(output)
    print(format_summary(report))
    print(f"[BENCHMARK] report={output}")
    return report


def run_planned_task(
    task: str,
    start_url: str,
    headless: bool,
    module: str,
    preconditions: str,
) -> dict:
    vault = CredentialVault()
    safe_task = vault.sanitize_text(task)
    plan = PlannerAgent().ask({"user_task": safe_task})
    steps = plan.get("steps", [])
    if not steps:
        raise RuntimeError("Planner returned no executable steps")
    result = ProductionRunner(
        headless=headless,
        dependencies=production_dependencies(),
        vault=vault,
    ).run_case(
        task_name=safe_task,
        steps=steps,
        start_url=start_url,
        module=module,
        preconditions=vault.sanitize_text(preconditions),
    )
    collaboration = result.setdefault("collaboration", {})
    collaboration["model_calls"] = int(
        collaboration.get("model_calls", 0)
    ) + 1
    collaboration["planning_steps"] = len(steps)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Production multi-agent Web testing system"
    )
    subparsers = parser.add_subparsers(dest="command")

    explore = subparsers.add_parser("explore", help="Explore and generate cases")
    explore.add_argument("--file", default="test_cases/explore_cases.xlsx")
    explore.add_argument("--headless", action="store_true")
    explore.add_argument("--task")
    explore.add_argument("--url")
    explore.add_argument("--module", default="自然语言探索")
    explore.add_argument("--preconditions", default="")

    explore.add_argument("--case", action="append", default=[])
    regression = subparsers.add_parser(
        "regression",
        help="Run deterministic regression with the production browser executor",
    )
    regression.add_argument("--headless", action="store_true")
    regression.add_argument("--case", default="")
    regression.add_argument("--module", default="")

    benchmark = subparsers.add_parser(
        "benchmark",
        help="Measure evidence, recovery, cost, latency, and reproducibility",
    )
    benchmark.add_argument("--file", default="test_cases/explore_cases.xlsx")
    benchmark.add_argument("--headless", action="store_true")
    benchmark.add_argument("--repeat", type=int, default=2)
    benchmark.add_argument("--output", default="report/benchmarks/latest.json")
    benchmark.add_argument("--suite", default="web-agent-baseline")

    train = subparsers.add_parser(
        "train",
        help="Validate and learn from an evidence-gated XLSX curriculum",
    )
    train.add_argument("--file", default="test_cases/webagent_test_case.xlsx")
    train.add_argument("--headless", action="store_true")
    train.add_argument("--validate-only", action="store_true")
    train.add_argument("--priority", action="append", default=[])
    train.add_argument("--module", action="append", default=[])
    train.add_argument("--case", action="append", default=[])
    train.add_argument("--limit", type=int, default=0)
    train.add_argument("--resume", action="store_true")
    train.add_argument("--allow-mutations", action="store_true")
    train.add_argument("--allow-destructive", action="store_true")
    train.add_argument("--holdout-percent", type=int, default=15)
    train.add_argument("--include-holdout", action="store_true")
    train.add_argument("--repeat", type=int, default=1)
    train.add_argument("--fail-fast", action="store_true")
    train.add_argument("--retry-quarantined", action="store_true")
    train.add_argument("--output", default="report/training/latest.json")
    train.add_argument("--memory-db", default="memory/web_agent_training.db")

    subparsers.add_parser("capabilities", help="Show per-agent tool permissions")
    subparsers.add_parser("doctor", help="Validate production configuration")
    return parser


def _normalized_argv(argv: Sequence[str] | None) -> list[str]:
    arguments = list(argv or [])
    if not arguments:
        return ["explore"]
    if arguments[0] not in COMMANDS:
        return ["explore", *arguments]
    return arguments


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(_normalized_argv(argv))

    if args.command == "capabilities":
        print(
            json.dumps(
                create_runner(headless=True).capability_manifest(),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "doctor":
        policy = AuthenticationPolicy.from_environment()
        policy.validate()
        runner = ProductionRunner(
            headless=True,
            dependencies=production_dependencies(policy),
        )
        print("runner=web_agent.runner.ProductionRunner")
        print("browser_executor=web_agent.browser.PolicyAwareBrowserExecutor")
        print("reasoning_policy=CredentialAwareReasoningState")
        print(f"login_path={policy.login_path}")
        print(f"store_selection_mode={policy.store_selection_mode}")
        print(f"formal_agents={','.join(runner.capability_manifest())}")
        print("status=OK")
        return 0

    if args.command == "benchmark":
        report = run_benchmark(
            args.file,
            args.headless,
            args.repeat,
            args.output,
            args.suite,
        )
        return 0 if report_passed(report) else 1

    if args.command == "train":
        from web_agent.training import (
            TrainingOptions, format_training_summary, run_training,
        )

        options = TrainingOptions(
            headless=args.headless,
            priorities=tuple(args.priority),
            modules=tuple(args.module),
            case_ids=tuple(args.case),
            limit=max(0, args.limit),
            resume=args.resume,
            allow_mutations=args.allow_mutations,
            allow_destructive=args.allow_destructive,
            holdout_percent=args.holdout_percent,
            include_holdout=args.include_holdout,
            repeat=max(1, args.repeat),
            fail_fast=args.fail_fast,
            retry_quarantined=args.retry_quarantined,
        )
        report = run_training(
            args.file,
            options,
            output=args.output,
            memory_db=args.memory_db,
            validate_only=args.validate_only,
        )
        print(format_training_summary(report))
        print(f"[TRAIN] report={args.output}")
        if args.resume and report.get("status") == "completed":
            return 0
        if report.get("selection", {}).get("selected_count", 0) == 0:
            return 2
        if args.validate_only:
            return 0
        summary = report.get("summary", {})
        return 0 if summary.get("executed", 0) and not (
            summary.get("failed", 0) or summary.get("unsupported_pass", 0)
            or summary.get("unpromotable_pass", 0)
            or summary.get("infra_error", 0)
        ) else 1

    if args.command == "regression":
        from web_agent.regression import ProductionRegressionRunner

        runner = ProductionRegressionRunner()
        runner.run_all(
            headless=args.headless,
            case_filter=args.case,
            module_filter=args.module,
        )
        return 0 if runner.results and all(
            item.get("result") == "pass" for item in runner.results
        ) else 1

    if args.task:
        if not args.url:
            parser.error("--task requires --url")
        result = run_planned_task(
            args.task,
            args.url,
            args.headless,
            args.module,
            args.preconditions,
        )
        print(f"[{'PASS' if result['success'] else 'FAIL'}] {args.task}")
        return 0 if result["success"] else 1

    outputs = run_excel(args.file, args.headless, case_ids=args.case)
    return 0 if outputs and all(item["success"] for item in outputs) else 1


__all__ = [
    "_normalized_argv",
    "build_parser",
    "create_runner",
    "main",
    "production_dependencies",
    "run_benchmark",
    "run_excel",
    "run_planned_task",
]
