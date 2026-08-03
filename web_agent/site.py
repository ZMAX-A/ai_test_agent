"""Runnable current-site composition for the clean ProductionRunner."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
import sys

from loader.excel_loader import load_excel_cases
from web_agent.auth import AuthenticationPolicy
from web_agent.commands import production_dependencies
from web_agent.runner import ProductionRunner
from web_agent.stable_browser import StablePolicyBrowserExecutor


def site_dependencies(policy: AuthenticationPolicy | None = None):
    selected = policy or AuthenticationPolicy.from_environment()
    dependencies = production_dependencies(selected)

    def browser_factory(page, visual_sensor):
        return StablePolicyBrowserExecutor(
            page,
            visual_sensor=visual_sensor,
            auth_policy=selected,
        )

    return replace(
        dependencies,
        browser_executor_factory=browser_factory,
    )


def create_runner(headless: bool) -> ProductionRunner:
    return ProductionRunner(
        headless=headless,
        dependencies=site_dependencies(),
    )


def run_excel(filepath: str, headless: bool) -> list[dict]:
    cases = load_excel_cases(filepath)
    print(f"[WEB-AGENT-SITE] data={filepath}, cases={len(cases)}")
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
            f"[{'PASS' if result['success'] else 'FAIL'}] {case.get('case_id')} | "
            f"runner={collaboration.get('runner', '-')} | "
            f"events={collaboration.get('event_count', 0)} | "
            f"model_calls={collaboration.get('model_calls', 0)}"
        )
    return outputs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Current-site Web agent")
    subparsers = parser.add_subparsers(dest="command")
    explore = subparsers.add_parser("explore")
    explore.add_argument("--file", default="test_cases/explore_cases.xlsx")
    explore.add_argument("--headless", action="store_true")
    regression = subparsers.add_parser("regression")
    regression.add_argument("--headless", action="store_true")
    subparsers.add_parser("doctor")
    subparsers.add_parser("capabilities")
    return parser


def main(argv=None) -> int:
    arguments = list(argv or [])
    if not arguments:
        arguments = ["explore"]
    args = build_parser().parse_args(arguments)
    if args.command == "doctor":
        policy = AuthenticationPolicy.from_environment()
        policy.validate()
        print("runner=web_agent.runner.ProductionRunner")
        print("browser_executor=StablePolicyBrowserExecutor")
        print(f"store_selection_mode={policy.store_selection_mode}")
        print("transient_portal_close=Escape")
        print("status=OK")
        return 0
    if args.command == "capabilities":
        print(json.dumps(
            create_runner(True).capability_manifest(),
            ensure_ascii=False,
            indent=2,
        ))
        return 0
    if args.command == "regression":
        from runner.generic_runner import GenericTestRunner
        runner = GenericTestRunner()
        runner.run_all(headless=args.headless)
        return 0 if runner.results and all(
            item.get("result") == "pass" for item in runner.results
        ) else 1
    outputs = run_excel(args.file, args.headless)
    return 0 if outputs and all(item["success"] for item in outputs) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
