"""下一代多 Agent Web 测试入口：权限运行时 + 结构化工具调用。"""

from __future__ import annotations

import argparse

from agents.planner_agent import PlannerAgent
from loader.excel_loader import load_excel_cases
from runner.runtime_collaborative_runner import RuntimeCollaborativeTestRunner


def _run_one(case: dict, headless: bool) -> dict:
    steps = [{"goal": goal} for goal in case.get("_steps_parsed", [])]
    if steps and case.get("expected"):
        steps[-1]["success_criteria"] = case["expected"]
    result = RuntimeCollaborativeTestRunner(headless=headless).run_case(
        task_name=case.get("case_name", case.get("case_id", "未命名")),
        steps=steps,
        start_url=case.get("start_url", ""),
        module=case.get("module", ""),
        preconditions=case.get("preconditions", ""),
    )
    collaboration = result.get("collaboration", {})
    print(
        f"[{'PASS' if result['success'] else 'FAIL'}] {case.get('case_id')} | "
        f"agents={collaboration.get('agents', [])} | "
        f"events={collaboration.get('event_count', 0)} | "
        f"model_calls={collaboration.get('model_calls', 0)}"
    )
    return result


def run_excel(filepath: str = "test_cases/explore_cases.xlsx",
              headless: bool = False) -> list[dict]:
    cases = load_excel_cases(filepath)
    print(f"[AGENT-RUNTIME] 数据源={filepath}, 用例数={len(cases)}")
    return [_run_one(case, headless) for case in cases]


def run_planned_task(user_task: str, start_url: str, headless: bool = False,
                     module: str = "自然语言探索", preconditions: str = "") -> dict:
    """让 Planner 把自然语言目标转换成步骤，再交给完整协作链。"""
    plan = PlannerAgent().ask({"user_task": user_task})
    steps = plan.get("steps", [])
    if not steps:
        raise RuntimeError("Planner 未生成可执行步骤")

    result = RuntimeCollaborativeTestRunner(headless=headless).run_case(
        task_name=user_task,
        steps=steps,
        start_url=start_url,
        module=module,
        preconditions=preconditions,
    )
    collaboration = result.setdefault("collaboration", {})
    collaboration["agents"] = sorted(set(collaboration.get("agents", [])) | {"planner"})
    collaboration["model_calls"] = int(collaboration.get("model_calls", 0)) + 1
    collaboration["planning_steps"] = len(steps)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="多 Agent Web 测试：AgentRuntime + ToolRegistry"
    )
    parser.add_argument("--file", default="test_cases/explore_cases.xlsx")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--task", help="自然语言测试目标；提供后启用 Planner")
    parser.add_argument("--url", help="自然语言任务的起始 URL")
    parser.add_argument("--module", default="自然语言探索")
    parser.add_argument("--preconditions", default="")
    parser.add_argument(
        "--show-capabilities", action="store_true", help="显示各 Agent 工具权限后退出"
    )
    args = parser.parse_args()

    if args.show_capabilities:
        manifest = RuntimeCollaborativeTestRunner.capability_manifest()
        for role, tools in manifest.items():
            print(f"{role}: {', '.join(tools) if tools else '(no tools)'}")
        return
    if args.task:
        if not args.url:
            parser.error("使用 --task 时必须同时提供 --url")
        result = run_planned_task(
            args.task, args.url, args.headless, args.module, args.preconditions
        )
        print(f"[{'PASS' if result['success'] else 'FAIL'}] {args.task}")
        return
    run_excel(args.file, args.headless)


if __name__ == "__main__":
    main()
