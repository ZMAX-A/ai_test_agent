"""多 Agent Web 测试入口。

用法：
  python run_multi_agent.py
  python run_multi_agent.py --headless
  python run_multi_agent.py --file test_cases/explore_cases.xlsx
"""

import argparse

from loader.excel_loader import load_excel_cases
from runner.multi_agent_runner import MultiAgentTestRunner


def run(filepath: str = "test_cases/explore_cases.xlsx", headless: bool = False) -> list[dict]:
    cases = load_excel_cases(filepath)
    print(f"[MULTI-AGENT] 数据源={filepath}, 用例数={len(cases)}")
    runner = MultiAgentTestRunner(headless=headless)
    outputs = []
    for case in cases:
        steps = [{"goal": goal} for goal in case.get("_steps_parsed", [])]
        expected = case.get("expected", "")
        if steps and expected:
            steps[-1]["success_criteria"] = expected
        result = runner.run_case(
            task_name=case.get("case_name", case.get("case_id", "未命名")),
            steps=steps,
            start_url=case.get("start_url", ""),
            module=case.get("module", ""),
            preconditions=case.get("preconditions", ""),
        )
        outputs.append(result)
        status = "PASS" if result["success"] else "FAIL"
        collaboration = result.get("collaboration", {})
        print(
            f"[{status}] {case.get('case_id')} | "
            f"agents={collaboration.get('agents', [])} | "
            f"events={collaboration.get('event_count', 0)} | "
            f"model_calls={collaboration.get('model_calls', 0)}"
        )
    return outputs


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="多 Agent Web 探索测试")
    parser.add_argument("--file", default="test_cases/explore_cases.xlsx")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()
    run(args.file, args.headless)
