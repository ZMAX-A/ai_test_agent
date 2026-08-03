"""Single production CLI and dependency composition."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from typing import Sequence

from agents.planner_agent import PlannerAgent
from core.credential_vault import CredentialVault
from loader.excel_loader import load_excel_cases
from web_agent.auth import AuthenticationPolicy
from web_agent.browser import PolicyAwareBrowserExecutor
from web_agent.reasoning import CredentialAwareReasoningState
from web_agent.runner import ProductionRunner, default_dependencies


COMMANDS = {"explore", "regression", "capabilities", "doctor"}


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


def run_excel(filepath: str, headless: bool) -> list[dict]:
    cases = load_excel_cases(filepath)
    print(f"[WEB-AGENT] data={filepath}, cases={len(cases)}")
    outputs = []
    for case in cases:
        steps = [{"goal": goal} for goal in case.get("_steps_parsed", [])]
        if steps and case.get("expected"):
            steps[-1]["success_criteria"] = case["expected"]
        result = create_runner(headless).run_case(
            task_name=case.get("case_name", case.get("case_id", "unnamed")),
            steps=steps,
            start_url=case.get("start_url", ""),
            module=case.get("module", ""),
            preconditions=case.get("preconditions", ""),
        )
        outputs.append(result)
        collaboration = result.get("collaboration", {})
        print(
            f"[{'PASS' if result['success'] else 'FAIL'}] "
            f"{case.get('case_id')} | "
            f"runner={collaboration.get('runner', '-')} | "
            f"events={collaboration.get('event_count', 0)} | "
            f"model_calls={collaboration.get('model_calls', 0)}"
        )
    return outputs


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

    regression = subparsers.add_parser(
        "regression",
        help="Run deterministic regression with the production browser executor",
    )
    regression.add_argument("--headless", action="store_true")
    regression.add_argument("--case", default="")
    regression.add_argument("--module", default="")

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

    outputs = run_excel(args.file, args.headless)
    return 0 if outputs and all(item["success"] for item in outputs) else 1


__all__ = [
    "_normalized_argv",
    "build_parser",
    "create_runner",
    "main",
    "production_dependencies",
    "run_excel",
    "run_planned_task",
]
