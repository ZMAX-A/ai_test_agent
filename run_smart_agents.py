"""推荐的增强推理 CLI：世界模型、Critic、Replanner、ToolRuntime。"""

from __future__ import annotations

import argparse

from run_agent_runtime import run_excel, run_planned_task
from runner.reasoning_runtime_activation import ReasoningAgentRunner


def main() -> None:
    parser = argparse.ArgumentParser(description="增强推理多 Agent Web 测试")
    parser.add_argument("--file", default="test_cases/explore_cases.xlsx")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--task", help="自然语言测试目标；提供后启用 Planner")
    parser.add_argument("--url", help="自然语言任务的起始 URL")
    parser.add_argument("--module", default="自然语言探索")
    parser.add_argument("--preconditions", default="")
    parser.add_argument("--show-capabilities", action="store_true")
    args = parser.parse_args()

    if args.show_capabilities:
        for role, tools in ReasoningAgentRunner.capability_manifest().items():
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
