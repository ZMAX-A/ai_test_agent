"""
AI Web 测试智能体 — 统一入口

用法:
  python main.py                    # 交互式菜单选择模式
  python main.py explore            # 探索模式：读 explore_cases.xlsx → LLM自主探索 → 生成标准用例
  python main.py regression         # 回归模式：读 standard.xlsx → 纯Playwright执行 → 结果回写
  python main.py generate           # 脚本生成：从 standard.xlsx 生成独立 .py 测试脚本
  python main.py run-scripts        # 执行已生成的脚本
  python main.py status             # 查看用例库状态
  python main.py status --changes   # 查看变更检测

选项:
  explore:
    --file PATH         指定探索用例文件（默认 test_cases/explore_cases.xlsx）
    --headless          无头模式

  regression:
    --module MODULE     按模块过滤
    --case CASE_ID      执行单个用例
    --headless          无头模式

  generate:
    --module MODULE     按模块过滤
    --case CASE_ID      生成单个用例脚本
    --force             强制全量生成（忽略变更检测）
    --output DIR        输出目录（默认 generated_scripts/）

  run-scripts:
    --headless          无头模式
"""

import sys
import os
import glob
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8', line_buffering=True, write_through=True)


def print_banner():
    print(r"""
   ╔══════════════════════════════════════════╗
   ║     🤖 AI Web 测试智能体                  ║
   ║     LLM + Playwright 自主探索测试         ║
   ╚══════════════════════════════════════════╝
    """)


def print_menu():
    print_banner()
    print("  请选择运行模式：\n")
    print("  [1] 🔍 探索模式")
    print("      读取 explore_cases.xlsx，LLM 自主探索页面")
    print("      成功后自动写入 standard.xlsx（17列格式）\n")
    print("  [2] ▶️  回归执行（推荐）")
    print("      通用脚本读取 standard.xlsx，逐条执行+断言+回写结果")
    print("      一条脚本跑所有用例，不消耗 LLM 额度\n")
    print("  [3] 📊 查看状态")
    print("      用例库统计 + 变更检测\n")
    print("  [q] 退出\n")


def cmd_explore(args: list = None):
    """探索模式"""
    from run_explore import run_explore
    filepath = None
    headless = False

    if args:
        for i, a in enumerate(args):
            if a == "--file" and i + 1 < len(args):
                filepath = args[i + 1]
            if a == "--headless":
                headless = True

    if headless:
        print("[INFO] 无头模式暂未实现，使用默认有头模式")

    run_explore(filepath)


def cmd_regression(args: list = None):
    """回归模式 — 通用脚本执行 standard.xlsx 中全部用例"""
    from runner.generic_runner import GenericTestRunner

    case_filter = ""
    module_filter = ""
    headless = False
    if args:
        for i, a in enumerate(args):
            if a == "--case" and i + 1 < len(args):
                case_filter = args[i + 1]
            if a == "--module" and i + 1 < len(args):
                module_filter = args[i + 1]
            if a == "--headless":
                headless = True

    runner = GenericTestRunner()
    runner.run_all(
        headless=headless,
        case_filter=case_filter,
        module_filter=module_filter,
    )


def cmd_generate(args: list = None):
    """(保留) 生成独立脚本 — 现在推荐直接用 regression 模式"""
    try:
        from scripts.generator import ScriptGenerator
        gen = ScriptGenerator()
        force = "--force" in (args or [])
        gen.generate_all("generated_scripts", force=force)
    except ImportError:
        print("[!] ScriptGenerator 不可用")
    except Exception as e:
        print(f"[!] 生成失败: {e}")
        print("  提示：现在推荐直接使用回归模式:")
        print("    python main.py regression")


def cmd_run_scripts(args: list = None):
    """执行回归模式（通用脚本） — 推荐方式"""
    print("  现在推荐使用通用脚本执行:")
    print("    python main.py regression")
    print("    python main.py regression --case TC001")
    print()
    from runner.generic_runner import GenericTestRunner
    case_filter = ""
    headless = False
    if args:
        for i, a in enumerate(args):
            if a == "--case" and i + 1 < len(args):
                case_filter = args[i + 1]
            if a == "--headless":
                headless = True
    runner = GenericTestRunner()
    runner.run_all(headless=headless, case_filter=case_filter)


def cmd_status(args: list = None):
    """查看用例库状态"""
    show_changes = args and "--changes" in args

    # 1) Excel 标准库统计
    try:
        from standard.store import StandardCaseStore
        store = StandardCaseStore()
        stats = store.get_stats()
        print(f"\n  📊 标准用例库 (standard.xlsx)")
        print(f"  {'─' * 40}")
        print(f"  用例总数: {stats['total']}")
        if stats['by_status']:
            print(f"  按状态: {stats['by_status']}")
        if stats['by_module']:
            print(f"  按模块: {stats['by_module']}")

        if stats['total'] > 0:
            print(f"\n  用例列表:")
            cases = store.load_cases()
            for c in cases:
                case_id = c.get("用例ID", c.get("case_id", ""))
                name = c.get("测试场景", c.get("name", ""))
                result = c.get("实际结果", c.get("last_result", ""))
                operations = c.get("操作类型", "")
                delimiter = "|" if "|" in operations else ","
                step_count = len([s for s in operations.split(delimiter) if s.strip()]) if operations else 0
                status = result or "untested"
                print(f"    {case_id:28s} [{status:12s}] {name:24s} {step_count}步")
    except ImportError:
        print("  [WARN] StandardCaseStore 不可用")
    except Exception as e:
        print(f"  [WARN] Excel 读取失败: {e}")

    # 2) JSON 用例库统计
    try:
        from case import case_manager
        json_stats = case_manager.get_stats()
        if json_stats.get("total", 0) > 0:
            print(f"\n  📁 JSON 用例库 (case_library/)")
            print(f"  {'─' * 40}")
            print(f"  用例总数: {json_stats['total']}")
            if json_stats.get("by_status"):
                print(f"  按状态: {json_stats['by_status']}")
            if json_stats.get("by_module"):
                print(f"  按模块: {json_stats['by_module']}")
            modules = case_manager.list_modules()
            if modules:
                print(f"  模块: {', '.join(modules)}")
    except Exception:
        pass

    # 3) 变更检测
    if show_changes:
        try:
            store = StandardCaseStore()
            changes = store.detect_changes()
            print(f"\n  🔄 变更检测 (vs 上次脚本生成)")
            print(f"  {'─' * 40}")
            if changes.get("new"):
                print(f"  新增: {changes['new']}")
            if changes.get("changed"):
                print(f"  修改: {changes['changed']}")
            if changes.get("deleted"):
                print(f"  删除: {changes['deleted']}")
            if changes.get("unchanged"):
                print(f"  未变更: {len(changes['unchanged'])} 个")
            if not any([changes.get("new"), changes.get("changed"), changes.get("deleted")]):
                print(f"  ✅ 所有用例均未变更")
        except Exception as e:
            print(f"  [WARN] 变更检测失败: {e}")

    # 4) 内存记忆
    try:
        from memory.memory_manager import MemoryManager
        mm = MemoryManager()
        flows = mm.get_flow_stats()
        if flows:
            print(f"\n  🧠 流程记忆 ({len(flows)} 条)")
            print(f"  {'─' * 40}")
            for f in flows[:5]:
                print(f"    {f['system']:20s} | {f['task_desc'][:30]:30s} | 成功率 {f['success_count']}/{f['total_count']}")
    except Exception:
        pass

    # 5) 生成脚本状态
    scripts_dir = "generated_scripts"
    if os.path.isdir(scripts_dir):
        scripts = glob.glob(os.path.join(scripts_dir, "*.py"))
        if scripts:
            print(f"\n  📜 已生成脚本 ({len(scripts)} 个)")
            print(f"  {'─' * 40}")
            for s in sorted(scripts):
                name = os.path.basename(s)
                size = os.path.getsize(s)
                print(f"    {name:30s} {size/1024:.1f} KB")

    print()


def interactive_menu():
    """交互式菜单"""
    while True:
        print_menu()
        choice = input("  请输入选项 [1-5/q]: ").strip().lower()

        if choice == "1" or choice == "explore":
            cmd_explore()
        elif choice == "2" or choice == "regression" or choice == "run":
            cmd_regression()
        elif choice == "3" or choice == "status":
            cmd_status(["--changes"])
        elif choice in ("q", "quit", "exit", "0"):
            print("\n  再见！👋\n")
            break
        else:
            print(f"\n  [!] 无效选项: {choice}\n")


def main():
    """主入口：子命令或交互菜单"""
    if len(sys.argv) > 1:
        mode = sys.argv[1].lower()
        remaining = sys.argv[2:]

        if mode == "explore":
            cmd_explore(remaining)
        elif mode == "regression":
            cmd_regression(remaining)
        elif mode == "generate":
            cmd_generate(remaining)
        elif mode == "run-scripts":
            cmd_run_scripts(remaining)
        elif mode == "status":
            cmd_status(remaining)
        elif mode in ("-h", "--help", "help"):
            print(__doc__)
            print_menu()
        else:
            print(f"未知模式: {mode}")
            print(__doc__)
    else:
        interactive_menu()


if __name__ == "__main__":
    main()
