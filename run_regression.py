"""
回归执行入口

兼容入口：委托给当前统一的 GenericTestRunner 执行 standard.xlsx。
全程不调用 LLM，纯 Playwright 原生操作。

用法：
    python run_regression.py                      # 执行所有 active 用例
    python run_regression.py --module 搜索功能     # 按模块过滤
    python run_regression.py --case TC001         # 执行单个用例
    python run_regression.py --headless           # 无头模式
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')

from runner.generic_runner import GenericTestRunner


def run_regression(module_filter: str = "", case_filter: str = "",
                   source: str = "", headless: bool = False):
    """运行确定性回归；保留旧函数签名供外部调用方平滑迁移。"""
    filter_module = module_filter
    filter_case = case_filter

    if not filter_module and not filter_case:
        for i, arg in enumerate(sys.argv[1:], 1):
            if arg == "--module" and i < len(sys.argv):
                filter_module = sys.argv[i + 1]
            if arg == "--case" and i < len(sys.argv):
                filter_case = sys.argv[i + 1]
            if arg == "--headless":
                headless = True

    if source and source != "xlsx":
        raise ValueError("统一回归入口仅支持 standard.xlsx；JSON 回归链已弃用")

    runner = GenericTestRunner()
    return runner.run_all(
        headless=headless,
        case_filter=filter_case,
        module_filter=filter_module,
    )


if __name__ == "__main__":
    run_regression()
