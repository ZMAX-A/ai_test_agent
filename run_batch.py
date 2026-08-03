"""
批量测试运行器：支持 Excel / JSON 两种数据源

数据源自动探测（按优先级）：
  1. 命令行指定 .xlsx 文件 → 读取 Excel
  2. 命令行指定 .json 文件 → 读取单个 JSON
  3. 默认 → test_cases/test_cases.xlsx（若存在）→ test_cases/*.json
"""
import glob
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.runner import TestRunner
from config.settings import settings

# Excel 加载器（可选）
try:
    from utils.excel_loader import load_from_xlsx
    HAS_EXCEL = True
except ImportError:
    HAS_EXCEL = False


def get_default_xlsx() -> str:
    """返回默认 xlsx 路径（如果存在）"""
    xlsx = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_cases", "test_cases.xlsx")
    return xlsx if os.path.isfile(xlsx) else None


def load_test_cases(case_dir: str = None) -> list[dict]:
    """自动选择数据源：优先 xlsx，其次 JSON"""
    base = os.path.dirname(os.path.abspath(__file__))
    if case_dir is None:
        case_dir = os.path.join(base, "test_cases")

    # 1) 尝试 Excel
    xlsx_path = get_default_xlsx()
    if xlsx_path and HAS_EXCEL:
        print(f"[数据源] 检测到 Excel 文件: {xlsx_path}")
        try:
            cases = load_from_xlsx(xlsx_path, only_enabled=True)
            for c in cases:
                print(f"  ─ {c['_case_id']:6s} {c['name']:20s} mode={c['mode']}")
            if cases:
                return cases
            print("  (Excel 中无启用用例，回退 JSON)")
        except Exception as e:
            print(f"  [!] Excel 读取失败: {e}")

    # 2) 回退 JSON
    if not os.path.isdir(case_dir):
        print(f"[!] 测试用例目录不存在: {case_dir}")
        return []

    case_files = sorted(glob.glob(os.path.join(case_dir, "*.json")))
    if not case_files:
        print(f"[!] 目录中无 JSON 用例: {case_dir}")
        return []

    cases = []
    for fp in case_files:
        try:
            with open(fp, "r", encoding="utf-8") as f:
                case = json.load(f)
            if "name" not in case:
                case["name"] = os.path.basename(fp)
            case["_file"] = fp
            cases.append(case)
            print(f"  [{os.path.basename(fp)}] {case['name']}")
        except (json.JSONDecodeError, OSError) as e:
            print(f"  [!] {os.path.basename(fp)} 加载失败: {e}")

    return cases


def load_single_file(filepath: str) -> list[dict]:
    """加载单个文件（.xlsx 或 .json）"""
    if filepath.endswith(".xlsx"):
        if not HAS_EXCEL:
            raise ImportError("需要 openpyxl 库: pip install openpyxl")
        print(f"[Excel] 加载: {filepath}")
        return load_from_xlsx(filepath, only_enabled=True)
    else:
        with open(filepath, "r", encoding="utf-8") as f:
            case = json.load(f)
        if "name" not in case:
            case["name"] = os.path.basename(filepath)
        case["_file"] = filepath
        print(f"[JSON] 加载: {filepath} → {case['name']}")
        return [case]


def run_test_case(case: dict) -> dict:
    """执行单个测试用例，返回结果"""
    print(f"\n{'='*60}")
    print(f"  [>>] 开始执行: {case['name']}")
    print(f"{'='*60}")

    runner = TestRunner(start_url=case.get("start_url", "https://www.baidu.com"))

    mode = case.get("mode", "auto")
    if mode == "steps" and "steps" in case:
        steps = list(case["steps"])
        # 注入登录预置步骤
        if case.get("_login_required"):
            cred = settings.get_credential(case.get("_credential_key", ""))
            login_url = settings.LOGIN_URL or case.get("start_url", "")
            login_steps = [
                {"step": -3, "goal": f"打开登录页面 {login_url}"},
                {"step": -2, "goal": f"在用户名输入框(第1个)输入 {cred['username']}"},
                {"step": -1, "goal": f"在密码输入框(第2个)输入 {cred['password']}"},
                {"step": 0,  "goal": "点击登录按钮，验证登录成功"},
            ]
            steps = login_steps + steps
            print(f"  [LOGIN] 注入 {len(login_steps)} 个登录前置步骤 (credential_key={case.get('_credential_key','')})")
        result = runner.run(user_task=case.get("name", ""), custom_steps=steps)
    else:
        result = runner.run(user_task=case.get("task", case.get("name", "")))

    passed = sum(1 for r in result if r.get("success"))
    total = len(result)
    return {
        "name": case["name"],
        "passed": passed,
        "total": total,
        "rate": round(passed / total * 100, 1) if total > 0 else 0,
        "results": result,
    }


def print_summary(results: list[dict], elapsed: float):
    """打印汇总报告"""
    print(f"\n\n{'='*60}")
    print(f"  批量测试执行汇总")
    print(f"{'='*60}")
    passed = sum(1 for r in results if r["passed"] == r["total"])
    failed = len(results) - passed
    total_cases = sum(r["total"] for r in results)
    total_passed = sum(r["passed"] for r in results)

    for r in results:
        status = "[PASS]" if r["passed"] == r["total"] else "[FAIL]"
        print(f"  {status} {r['name']} — {r['passed']}/{r['total']} ({r['rate']}%)")

    print(f"\n  [TIME] 总耗时: {elapsed:.1f}s")
    print(f"  [STAT] 用例: {len(results)} 个 | 步骤: {total_passed}/{total_cases}")
    print(f"  [STAT] 通过: {passed} 个 | 失败: {failed} 个")


if __name__ == "__main__":
    import time

    start = time.time()

    # 命令行参数处理
    if len(sys.argv) > 1:
        cases = load_single_file(sys.argv[1])
    else:
        print("加载测试用例...")
        cases = load_test_cases()

    if not cases:
        print("[!] 没有测试用例可执行")
        sys.exit(1)

    print(f"\n共 {len(cases)} 个测试用例，开始执行...")

    all_results = []
    for case in cases:
        result = run_test_case(case)
        all_results.append(result)

    elapsed = time.time() - start
    print_summary(all_results, elapsed)
