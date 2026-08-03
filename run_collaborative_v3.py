"""多 Agent 协作测试 v3 正式入口。"""

import argparse

from loader.excel_loader import load_excel_cases
from runner.collaborative_runner_v3 import CollaborativeTestRunnerV3


def run(filepath: str = "test_cases/explore_cases.xlsx", headless: bool = False) -> list[dict]:
    cases = load_excel_cases(filepath)
    print(f"[COLLABORATIVE-V3] 数据源={filepath}, 用例数={len(cases)}")
    outputs = []
    for case in cases:
        steps = [{"goal": goal} for goal in case.get("_steps_parsed", [])]
        if steps and case.get("expected"):
            steps[-1]["success_criteria"] = case["expected"]
        result = CollaborativeTestRunnerV3(headless=headless).run_case(
            task_name=case.get("case_name", case.get("case_id", "未命名")),
            steps=steps,
            start_url=case.get("start_url", ""),
            module=case.get("module", ""),
            preconditions=case.get("preconditions", ""),
        )
        outputs.append(result)
        collab = result.get("collaboration", {})
        print(
            f"[{'PASS' if result['success'] else 'FAIL'}] {case.get('case_id')} | "
            f"agents={collab.get('agents', [])} | events={collab.get('event_count', 0)} | "
            f"model_calls={collab.get('model_calls', 0)}"
        )
    return outputs


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="多 Agent 协作 Web 测试 v3")
    parser.add_argument("--file", default="test_cases/explore_cases.xlsx")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()
    run(args.file, args.headless)
