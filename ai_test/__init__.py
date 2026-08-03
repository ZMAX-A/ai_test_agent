"""Official CLI package for the verified unified Web test agent."""

from __future__ import annotations

import argparse
import json

from agents.planner_agent import PlannerAgent
from core.credential_vault import CredentialVault
from loader.excel_loader import load_excel_cases
from runner.verified_unified_runner import VerifiedUnifiedSmartRunner


def run_excel(filepath: str, headless: bool) -> list[dict]:
    cases = load_excel_cases(filepath)
    print(f"[VERIFIED-UNIFIED] data={filepath}, cases={len(cases)}")
    outputs = []
    for case in cases:
        steps = [{"goal": goal} for goal in case.get("_steps_parsed", [])]
        if steps and case.get("expected"):
            steps[-1]["success_criteria"] = case["expected"]
        result = VerifiedUnifiedSmartRunner(headless=headless).run_case(
            task_name=case.get("case_name", case.get("case_id", "unnamed")),
            steps=steps,
            start_url=case.get("start_url", ""),
            module=case.get("module", ""),
            preconditions=case.get("preconditions", ""),
        )
        outputs.append(result)
        collaboration = result.get("collaboration", {})
        print(
            f"[{'PASS' if result['success'] else 'FAIL'}] {case.get('case_id')} | "
            f"active_roles={collaboration.get('agents', [])} | "
            f"events={collaboration.get('event_count', 0)} | "
            f"model_calls={collaboration.get('model_calls', 0)}"
        )
    return outputs


def run_planned_task(task: str, start_url: str, headless: bool,
                     module: str, preconditions: str) -> dict:
    vault = CredentialVault()
    safe_task = vault.sanitize_text(task)
    plan = PlannerAgent().ask({"user_task": safe_task})
    steps = plan.get("steps", [])
    if not steps:
        raise RuntimeError("Planner returned no executable steps")
    result = VerifiedUnifiedSmartRunner(headless=headless, vault=vault).run_case(
        task_name=safe_task,
        steps=steps,
        start_url=start_url,
        module=module,
        preconditions=vault.sanitize_text(preconditions),
    )
    collaboration = result.setdefault("collaboration", {})
    collaboration["model_calls"] = int(collaboration.get("model_calls", 0)) + 1
    collaboration["planning_steps"] = len(steps)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verified unified Web test agent")
    subparsers = parser.add_subparsers(dest="command")

    explore = subparsers.add_parser("explore")
    explore.add_argument("--file", default="test_cases/explore_cases.xlsx")
    explore.add_argument("--headless", action="store_true")
    explore.add_argument("--task")
    explore.add_argument("--url")
    explore.add_argument("--module", default="natural-language-exploration")
    explore.add_argument("--preconditions", default="")

    regression = subparsers.add_parser("regression")
    regression.add_argument("--headless", action="store_true")
    regression.add_argument("--case", default="")
    regression.add_argument("--module", default="")
    subparsers.add_parser("capabilities")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "explore"
    if command == "capabilities":
        runner = VerifiedUnifiedSmartRunner(headless=True)
        print(json.dumps(runner.capability_manifest(), ensure_ascii=False, indent=2))
        return
    if command == "regression":
        from runner.generic_runner import GenericTestRunner
        GenericTestRunner().run_all(
            headless=args.headless,
            case_filter=args.case,
            module_filter=args.module,
        )
        return
    if getattr(args, "task", None):
        if not args.url:
            parser.error("--task requires --url")
        result = run_planned_task(
            args.task, args.url, args.headless, args.module, args.preconditions
        )
        print(f"[{'PASS' if result['success'] else 'FAIL'}] {args.task}")
        return
    run_excel(args.file, args.headless)


__all__ = ["build_parser", "main", "run_excel", "run_planned_task"]
