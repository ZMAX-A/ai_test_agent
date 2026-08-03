"""AI Web 测试智能体统一正式入口。

用法：
  python ai_test.py explore
  python ai_test.py explore --headless
  python ai_test.py explore --task "进入顾客档案 /customer" --url "https://..."
  python ai_test.py regression --headless
  python ai_test.py capabilities
"""

from __future__ import annotations

import argparse
import sys

from agents.planner_agent import PlannerAgent
from core.credential_vault import CredentialVault
from loader.excel_loader import load_excel_cases
from runner.unified_smart_runner import UnifiedSmartRunner


def run_excel(filepath: str, headless: bool) -> list[dict]:
    cases = load_excel_cases(filepath)
    print(f"[UNIFIED] 数据源={filepath}, 用例数={len(cases)}")
    outputs = []
    for case in cases:
        steps = [{"goal": goal} for goal in case.get("_steps_parsed", [])]
        if steps and case.get("expected"):
            steps[-1]["success_criteria"] = case["expected"]
        result = UnifiedSmartRunner(headless=headless).run_case(
            task_name=case.get("case_name", case.get("case_id", "未命名")),
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
        raise RuntimeError("Planner 未生成可执行步骤")
    result = UnifiedSmartRunner(headless=headless, vault=vault).run_case(
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
    parser = argparse.ArgumentParser(description="统一 Smart Agent Web 测试")
    subparsers = parser.add_subparsers(dest="command")

    explore = subparsers.add_parser("explore", help="AI 探索并生成标准用例")
    explore.add_argument("--file", default="test_cases/explore_cases.xlsx")
    explore.add_argument("--headless", action="store_true")
    explore.add_argument("--task", help="自然语言测试目标")
    explore.add_argument("--url", help="自然语言任务起始 URL")
    explore.add_argument("--module", default="自然语言探索")
    explore.add_argument("--preconditions", default="")

    regression = subparsers.add_parser("regression", help="无模型确定性回归")
    regression.add_argument("--headless", action="store_true")
    regression.add_argument("--case", default="")
    regression.add_argument("--module", default="")

    subparsers.add_parser("capabilities", help="显示 Agent 与工具权限")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "explore"

    if command == "capabilities":
        for role, tools in UnifiedSmartRunner(headless=True).capability_manifest().items():
            print(f"{role}: {', '.join(tools) if tools else '(no tools)'}")
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
            parser.error("使用 --task 时必须提供 --url")
        result = run_planned_task(
            args.task, args.url, args.headless, args.module, args.preconditions
        )
        print(f"[{'PASS' if result['success'] else 'FAIL'}] {args.task}")
        return
    run_excel(args.file, args.headless)


if __name__ == "__main__":
    main(sys.argv[1:])
