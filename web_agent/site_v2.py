"""Current-site production entry with keyboard text selection."""

from __future__ import annotations

import argparse
from dataclasses import replace
import sys

from loader.excel_loader import load_excel_cases
from web_agent.auth import AuthenticationPolicy
from web_agent.commands import production_dependencies
from web_agent.keyboard_text_browser import KeyboardTextPolicyBrowserExecutor
from web_agent.runner import ProductionRunner


def dependencies(policy: AuthenticationPolicy | None = None):
    selected = policy or AuthenticationPolicy.from_environment()
    base = production_dependencies(selected)

    def browser_factory(page, visual_sensor):
        return KeyboardTextPolicyBrowserExecutor(
            page, visual_sensor=visual_sensor, auth_policy=selected
        )

    return replace(base, browser_executor_factory=browser_factory)


def create_runner(headless: bool) -> ProductionRunner:
    return ProductionRunner(headless=headless, dependencies=dependencies())


def run_excel(filepath: str, headless: bool) -> list[dict]:
    cases = load_excel_cases(filepath)
    print(f"[WEB-AGENT-SITE-V2] data={filepath}, cases={len(cases)}")
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", default="explore", choices=("explore", "doctor"))
    parser.add_argument("--file", default="test_cases/explore_cases.xlsx")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "doctor":
        policy = AuthenticationPolicy.from_environment()
        policy.validate()
        print("runner=web_agent.runner.ProductionRunner")
        print("browser_executor=KeyboardTextPolicyBrowserExecutor")
        print(f"store_option_text={policy.store_option_text}")
        print("status=OK")
        return 0
    outputs = run_excel(args.file, args.headless)
    return 0 if outputs and all(item["success"] for item in outputs) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
