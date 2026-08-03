"""
探索执行入口

流程：读取 Excel 探索用例 → 逐个执行探索模式 → 成功后自动生成标准用例 → 输出汇总

用法：
    python run_explore.py                          # 默认读取 test_cases/explore_cases.xlsx
    python run_explore.py test_cases/my_cases.xlsx  # 指定文件
"""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8', line_buffering=True, write_through=True)

from loader.excel_loader import load_excel_cases
from core.runner import TestRunner

# 结果回写
try:
    from standard.store import get_store
    HAS_STORE = True
except ImportError:
    HAS_STORE = False


def run_explore(filepath: str = None):
    # 从 main.py 调用时 sys.argv[1] 是子命令"explore"，不能当文件路径用
    if filepath:
        target = filepath
    elif len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        target = sys.argv[1]
    else:
        target = "test_cases/explore_cases.xlsx"
    if not os.path.isfile(target):
        print(f"[!] 文件不存在: {target}")
        print()
        print("请先用以下命令生成模板：")
        print("  python scripts/generate_explore_template.py")
        sys.exit(1)

    print(f"[数据源] {target}")
    cases = load_excel_cases(target)
    print(f"共 {len(cases)} 个探索用例\n")

    all_results = []
    for case in cases:
        case_id = case["case_id"]
        case_name = case["case_name"]
        steps_desc = case.get("_steps_parsed", [])
        start_url = case.get("start_url", "https://www.baidu.com")
        module = case.get("module", "")
        preconditions = case.get("preconditions", "")
        expected = case.get("expected", "")

        if not steps_desc:
            print(f"[!] {case_id} 无步骤描述，跳过")
            continue

        steps = [{"goal": s} for s in steps_desc]
        if steps and expected:
            # Excel 的“预期结果”是整条场景的最终完成条件，交给最后一步验证。
            steps[-1]["success_criteria"] = expected

        print(f"\n{'#'*60}")
        print(f"#  探索: {case_id} - {case_name}")
        print(f"#  步骤: {len(steps)} 步")
        print(f"{'#'*60}")

        start_t = time.time()
        runner = TestRunner(start_url=start_url)
        result = runner.explore(
            task_name=case_name,
            steps=steps,
            start_url=start_url,
            module=module,
            preconditions=preconditions,
        )
        elapsed = time.time() - start_t

        # ── 结果回写到 Excel ──
        if HAS_STORE and result.get("case_id"):
            try:
                passed_steps = sum(1 for r in result["results"] if r["success"])
                total_steps = len(result["results"])
                store = get_store()
                status = f"pass ({passed_steps}/{total_steps})" if result["success"] else f"fail ({passed_steps}/{total_steps})"
                store.write_result(result["case_id"], status)
            except Exception as e:
                print(f"  [WARN] 结果回写失败: {e}")

        all_results.append({
            "case_id": case_id,
            "name": case_name,
            "success": result["success"],
            "passed": sum(1 for r in result["results"] if r["success"]),
            "total": len(result["results"]),
            "generated_case_id": result.get("case_id"),
        })

    # ── 汇总报告 ──
    print(f"\n\n{'='*60}")
    print(f"  探索执行汇总")
    print(f"{'='*60}")
    for r in all_results:
        status = "[PASS]" if r["success"] else "[FAIL]"
        gen = f" → 用例: {r['generated_case_id']}" if r.get("generated_case_id") else ""
        print(f"  {status} {r['name']} — {r['passed']}/{r['total']}{gen}")

    passed = sum(1 for r in all_results if r["success"])
    print(f"\n  通过: {passed}/{len(all_results)}")
    print()
    if passed:
        print("生成的用例已保存到:")
        print("  · case_library/ (JSON)")
        print("  · test_cases/standard.xlsx (Excel标准库)")
    else:
        print("失败场景未生成或覆盖标准用例。")
    print()
    print("后续操作：")
    print("  python main.py regression   # 回归执行")
    print("  python main.py generate     # 生成脚本")
    print("  python main.py run-scripts  # 执行脚本")
    print()


if __name__ == "__main__":
    run_explore()
