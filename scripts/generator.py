"""
测试脚本生成器

从 standard.xlsx 标准用例库读取用例，生成可独立运行的 Playwright Python 脚本。
生成的脚本零依赖（只需 playwright），可直接 `python generated_scripts/TC001.py` 运行。

特性：
  - 支持 --headless 命令行参数
  - 失败自动截图到 screenshots/ 目录
  - 输出 JSON 格式执行结果
  - 包含清晰的步骤注释
  - 变更检测：默认只重新生成有变更的用例
"""

import os
import sys
import json
from datetime import datetime

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import settings

try:
    from standard.store import StandardCaseStore, get_store
    HAS_STORE = True
except ImportError:
    HAS_STORE = False


# ── 脚本模板 ──

SCRIPT_TEMPLATE = '''# -*- coding: utf-8 -*-
"""
自动生成的 Playwright 测试脚本
  用例编号: __CASE_ID__
  用例名称: __CASE_NAME__
  模块: __MODULE__
  生成时间: __GENERATED_AT__
  来源: standard.xlsx

用法:
  python __SCRIPT_NAME__               # 有头模式执行
  python __SCRIPT_NAME__ --headless    # 无头模式执行
"""

import sys, os, json, time
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ── 配置 ──
HEADLESS = "--headless" in sys.argv
PAGE_TIMEOUT = __PAGE_TIMEOUT__
ACTION_TIMEOUT = __ACTION_TIMEOUT__
SCREENSHOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

# ── 截图辅助 ──
def _screenshot(page, name="fail"):
    try:
        ts = datetime.now().strftime("%H%M%S")
        path = os.path.join(SCREENSHOT_DIR, f"{ts}_{name}.png")
        page.screenshot(path=path)
        return path
    except Exception:
        return ""

# ═══════════════════════════════════════════════
#  测试: __CASE_NAME__ (__CASE_ID__)
# ═══════════════════════════════════════════════

def __CASE_ID_SAFE__():
    """__CASE_NAME__"""
    results = []
    start_time = time.time()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(no_viewport=True)
        page = context.new_page()
        page.set_default_timeout(PAGE_TIMEOUT)

        try:
__STEPS_CODE__
        except Exception as e:
            results.append({
                "step": 0, "goal": "全局异常",
                "success": False, "msg": str(e)
            })

        browser.close()

    duration = time.time() - start_time
    passed = sum(1 for r in results if r["success"])
    total = len(results)

    summary = {
        "case_id": "__CASE_ID__",
        "name": "__CASE_NAME__",
        "passed": passed,
        "total": total,
        "duration": round(duration, 1),
        "status": "passed" if passed == total else "failed",
        "results": results,
    }

    print(f"\\n{'='*50}")
    print(f"  测试: __CASE_NAME__ (__CASE_ID__)")
    print(f"  结果: {passed}/{total} 通过 ({duration:.1f}s)")
    for r in results:
        s = "[OK]" if r["success"] else "[FAIL]"
        print(f"  {s} 步骤{r['step']}: {r['goal'][:50]}")
    print(f"{'='*50}")

    # 输出 JSON（可被外部工具解析）
    if "--json" in sys.argv:
        print("\\n__RESULT_JSON__")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        print("__END_RESULT_JSON__")

    return summary


if __name__ == "__main__":
    __CASE_ID_SAFE__()
'''

# ── 动作→代码映射 ──


def _render_goto(params: dict, indent: str) -> str:
    url = params.get("url", "")
    if not url:
        return f'{indent}# goto 未指定URL，跳过'
    return f'{indent}page.goto("{url}", timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")\n' \
           f'{indent}print("  [NAV] {url}")'


def _render_click(params: dict, indent: str) -> str:
    role = params.get("role", "")
    name = params.get("name", "")
    idx = params.get("index", "")
    lines = [f'{indent}# 点击: role={role}, name={name}' if name else f'{indent}# 点击: role={role}']

    if role:
        locator = f'page.get_by_role("{role}"'
        if name:
            locator += f', name="{name}"'
        locator += ')'
        if idx:
            locator += f'.nth({idx})'
        lines.append(f'{indent}try:')
        lines.append(f'{indent}    {locator}.wait_for(state="visible", timeout=ACTION_TIMEOUT)')
        lines.append(f'{indent}    {locator}.click(timeout=ACTION_TIMEOUT)')
        lines.append(f'{indent}    print("  [CLICK] 点击成功")')
        lines.append(f'{indent}except Exception as e:')
        lines.append(f'{indent}    return False, f"点击失败: {{e}}"')
    else:
        lines.append(f'{indent}print("  [WARN] 点击缺少role定位器，跳过")')
    return '\n'.join(lines)


def _render_fill(params: dict, indent: str) -> str:
    role = params.get("role", "")
    name = params.get("name", "")
    value = params.get("value", "")
    idx = params.get("index", "")
    lines = [f'{indent}# 输入: "{value}" → role={role}']

    if role:
        locator = f'page.get_by_role("{role}"'
        if name:
            locator += f', name="{name}"'
        locator += ')'
        if idx:
            locator += f'.nth({idx})'
        lines.append(f'{indent}try:')
        lines.append(f'{indent}    {locator}.wait_for(state="visible", timeout=ACTION_TIMEOUT)')
        lines.append(f'{indent}    {locator}.fill("{value}", timeout=ACTION_TIMEOUT)')
        lines.append(f'{indent}    print("  [FILL] 输入成功: {value}")')
        lines.append(f'{indent}except Exception as e:')
        lines.append(f'{indent}    return False, f"输入失败: {{e}}"')
    else:
        lines.append(f'{indent}print("  [WARN] 输入缺少role定位器，跳过")')
    return '\n'.join(lines)


def _render_assert_url(params: dict, indent: str) -> str:
    target = params.get("expect_url_contains", "")
    lines = [
        f'{indent}current_url = page.url',
        f'{indent}if "{target}" in current_url:',
        f'{indent}    print("  [OK] URL断言通过: " + current_url)',
        f'{indent}else:',
        f'{indent}    _screenshot(page, "assert_url")',
        f'{indent}    return False, f"URL断言失败，当前URL: {{current_url}}"',
    ]
    return '\n'.join(lines)


def _render_assert_title(params: dict, indent: str) -> str:
    target = params.get("expect_title_contains", "")
    lines = [
        f'{indent}current_title = page.title()',
        f'{indent}if "{target}" in current_title:',
        f'{indent}    print("  [OK] 标题断言通过: " + current_title)',
        f'{indent}else:',
        f'{indent}    _screenshot(page, "assert_title")',
        f'{indent}    return False, f"标题断言失败，当前标题: {{current_title}}"',
    ]
    return '\n'.join(lines)


def _render_assert_text(params: dict, indent: str) -> str:
    target = params.get("expect_text", "")
    lines = [
        f'{indent}page_content = page.content()',
        f'{indent}if "{target}" in page_content:',
        f'{indent}    print("  [OK] 文本断言通过: 页面含 \\"{target}\\"" )',
        f'{indent}else:',
        f'{indent}    _screenshot(page, "assert_text")',
        f'{indent}    return False, f"文本断言失败: 未找到 \\"{target}\\""',
    ]
    return '\n'.join(lines)


def _render_scroll(params: dict, indent: str) -> str:
    direction = params.get("direction", "down")
    offset = 600 if direction == "down" else -600
    return f'{indent}page.evaluate("window.scrollBy(0, {offset})")\n' \
           f'{indent}print("  [SCROLL] 滚动: {direction}")'


def _render_finish(params: dict, indent: str) -> str:
    result = params.get("result", "步骤完成")
    return f'{indent}print("  [FINISH] {result}")'


ACTION_RENDERERS = {
    "goto": _render_goto,
    "click": _render_click,
    "fill": _render_fill,
    "assert_url": _render_assert_url,
    "assert_title": _render_assert_title,
    "assert_text": _render_assert_text,
    "scroll": _render_scroll,
    "finish": _render_finish,
}


# ═══════════════════════════════════════════════
#  ScriptGenerator
# ═══════════════════════════════════════════════

class ScriptGenerator:
    """从标准用例生成独立的 Playwright 测试脚本"""

    def __init__(self, store: StandardCaseStore = None):
        if HAS_STORE:
            self.store = store or get_store()
        else:
            self.store = None

    def generate_script(self, case: dict) -> str:
        """生成单个用例的脚本源码"""
        case_id = case.get("case_id", "UNKNOWN")
        case_name = case.get("case_name", case.get("name", case_id))
        module = case.get("module", "")
        steps = case.get("steps", [])
        start_url = case.get("start_url", "")

        # 安全的 Python 标识符
        case_id_safe = case_id.replace("-", "_").replace(".", "_")

        # 渲染步骤代码
        steps_code = self._render_steps(steps, start_url)

        # 用 replace 避免模板中 Python 代码的花括号冲突
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        script = SCRIPT_TEMPLATE
        script = script.replace("__CASE_ID__", case_id)
        script = script.replace("__CASE_NAME__", case_name)
        script = script.replace("__MODULE__", module)
        script = script.replace("__GENERATED_AT__", now_str)
        script = script.replace("__SCRIPT_NAME__", f"{case_id}.py")
        script = script.replace("__CASE_ID_SAFE__", f"test_{case_id_safe}")
        script = script.replace("__PAGE_TIMEOUT__", str(settings.PAGE_TIMEOUT))
        script = script.replace("__ACTION_TIMEOUT__", str(settings.ACTION_TIMEOUT))
        script = script.replace("__STEPS_CODE__", steps_code)
        return script

    def _render_steps(self, steps: list, start_url: str) -> str:
        """渲染所有步骤代码"""
        lines = []
        # 如果有起始URL且步骤中没有 goto，先加导航
        has_goto = any(s.get("action") == "goto" for s in steps)
        if start_url and not has_goto:
            lines.append(f'            # ── 导航到起始页 ──')
            lines.append(f'            page.goto("{start_url}", timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")')
            lines.append(f'            print("  [NAV] {start_url}")')
            lines.append('')

        for step in steps:
            step_num = step.get("step", 0)
            goal = step.get("goal", "")
            action = step.get("action", "")
            params = step.get("parameters", {})
            asserts = step.get("asserts", [])

            indent = "            "

            lines.append(f'{indent}# ── 步骤{step_num}: {goal} ──')
            lines.append(f'{indent}print("\\n[STEP] {step_num}. {goal}")')

            # 执行动作
            renderer = ACTION_RENDERERS.get(action)
            if renderer:
                if action in ("assert_url", "assert_title", "assert_text"):
                    # 断言类：返回 (success, msg)
                    lines.append(f'{indent}success, msg = _step_{step_num}_action(page)')
                    # 生成一个内联函数
                    func_body = renderer(params, indent + "    ")
                    func_code = [
                        f'{indent}def _step_{step_num}_action(page):',
                        f'{indent}    """步骤{step_num}: {goal}"""',
                        func_body,
                        f'{indent}    return True, ""',
                    ]
                    # 把 func 定义插入前面
                    lines.insert(-1, '\n'.join(func_code))
                elif action == "goto":
                    code = renderer(params, indent)
                    lines.append(code)
                    lines.append(f'{indent}step_success = True')
                    lines.append(f'{indent}step_msg = "导航完成"')
                elif action == "click":
                    # 需要特殊处理：click 失败返回 (False, msg)
                    code = renderer(params, indent)
                    # 包装成 try-except 返回形式
                    lines.append(f'{indent}try:')
                    lines.append(f'{indent}    ' + code.split('\n')[2] if '\n' in code else code)  # 简化处理
                    lines.append(f'{indent}    step_success = True')
                    lines.append(f'{indent}    step_msg = "点击成功"')
                    lines.append(f'{indent}except Exception as e:')
                    lines.append(f'{indent}    _screenshot(page, "step{step_num}_click")')
                    lines.append(f'{indent}    step_success = False')
                    lines.append(f'{indent}    step_msg = f"点击失败: {{e}}"')
                elif action == "fill":
                    lines.append(f'{indent}try:')
                    # 简单写出 fill 代码
                    role = params.get("role", "")
                    name = params.get("name", "")
                    value = params.get("value", "")
                    idx = params.get("index", "")
                    locator = f'page.get_by_role("{role}"'
                    if name:
                        locator += f', name="{name}"'
                    locator += ')'
                    if idx:
                        locator += f'.nth({idx})'
                    lines.append(f'{indent}    {locator}.wait_for(state="visible", timeout=ACTION_TIMEOUT)')
                    lines.append(f'{indent}    {locator}.fill("{value}", timeout=ACTION_TIMEOUT)')
                    lines.append(f'{indent}    step_success = True')
                    lines.append(f'{indent}    step_msg = f"输入成功: {value}"')
                    lines.append(f'{indent}except Exception as e:')
                    lines.append(f'{indent}    _screenshot(page, "step{step_num}_fill")')
                    lines.append(f'{indent}    step_success = False')
                    lines.append(f'{indent}    step_msg = f"输入失败: {{e}}"')
                elif action == "scroll":
                    code = renderer(params, indent)
                    lines.append(code)
                    lines.append(f'{indent}step_success = True')
                    lines.append(f'{indent}step_msg = "滚动完成"')
                elif action == "finish":
                    lines.append(f'{indent}step_success = True')
                    lines.append(f'{indent}step_msg = "步骤完成"')
                else:
                    lines.append(f'{indent}print("  [WARN] 未支持的动作: {action}")')
                    lines.append(f'{indent}step_success = True')
                    lines.append(f'{indent}step_msg = "跳过不支持的动作"')
            else:
                lines.append(f'{indent}print("  [WARN] 未知动作类型: {action}")')
                lines.append(f'{indent}step_success = True')
                lines.append(f'{indent}step_msg = "跳过未知动作"')

            # 执行断言
            if asserts:
                for a in asserts:
                    a_type = a.get("type", "")
                    a_target = a.get("target", "")
                    if a_type == "url_contains":
                        lines.append(f'{indent}if "{a_target}" not in page.url:')
                        lines.append(f'{indent}    step_success = False')
                        lines.append(f'{indent}    step_msg = f"断言失败: URL不含 \\"{a_target}\\""')
                    elif a_type == "title_contains":
                        lines.append(f'{indent}if "{a_target}" not in page.title():')
                        lines.append(f'{indent}    step_success = False')
                        lines.append(f'{indent}    step_msg = f"断言失败: 标题不含 \\"{a_target}\\""')
                    elif a_type == "text_exists":
                        lines.append(f'{indent}if "{a_target}" not in page.content():')
                        lines.append(f'{indent}    step_success = False')
                        lines.append(f'{indent}    step_msg = f"断言失败: 页面不含 \\"{a_target}\\""')

                    if not step_success:
                        lines.append(f'{indent}    _screenshot(page, "step{step_num}_assert")')

            # 记录结果
            lines.append(f'{indent}results.append({{')
            lines.append(f'{indent}    "step": {step_num},')
            lines.append(f'{indent}    "goal": "{goal}",')
            lines.append(f'{indent}    "success": step_success,')
            lines.append(f'{indent}    "msg": step_msg')
            lines.append(f'{indent}}})')

            # 失败时中断
            lines.append(f'{indent}if not step_success:')
            lines.append(f'{indent}    print(f"  [FAIL] {{step_msg}}")')
            lines.append(f'{indent}    break')
            lines.append(f'{indent}print("  [OK] 步骤通过")')
            lines.append('')

        return '\n'.join(lines)

    # ── 面向更简单生成的"纯线性"渲染（推荐用于标准用例） ──

    def generate_script_simple(self, case: dict) -> str:
        """简化版脚本生成：纯线性执行，适合从标准用例库生成的稳定用例"""
        case_id = case.get("case_id", "UNKNOWN")
        case_name = case.get("case_name", case.get("name", case_id))
        module = case.get("module", "")
        steps = case.get("steps", [])
        start_url = case.get("start_url", "")
        case_id_safe = case_id.replace("-", "_").replace(".", "_")

        # 渲染步骤
        step_lines = self._render_steps_linear(steps, start_url)

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        script = SCRIPT_TEMPLATE
        script = script.replace("__CASE_ID__", case_id)
        script = script.replace("__CASE_NAME__", case_name)
        script = script.replace("__MODULE__", module)
        script = script.replace("__GENERATED_AT__", now_str)
        script = script.replace("__SCRIPT_NAME__", f"{case_id}.py")
        script = script.replace("__CASE_ID_SAFE__", f"test_{case_id_safe}")
        script = script.replace("__PAGE_TIMEOUT__", str(settings.PAGE_TIMEOUT))
        script = script.replace("__ACTION_TIMEOUT__", str(settings.ACTION_TIMEOUT))
        script = script.replace("__STEPS_CODE__", step_lines)
        return script

    def _render_steps_linear(self, steps: list, start_url: str) -> str:
        """纯线性渲染步骤，错误即停"""
        lines = []
        has_goto = any(s.get("action") == "goto" for s in steps)
        if start_url and not has_goto:
            lines.append(f'            page.goto("{start_url}", timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")')
            lines.append(f'            print("  [NAV] {start_url}")')
            lines.append('')

        for step in steps:
            step_num = step.get("step", 0)
            goal = step.get("goal", "")
            action = step.get("action", "")
            params = step.get("parameters", {})
            asserts = step.get("asserts", [])

            lines.append(f'            # ── 步骤{step_num}: {goal} ──')
            lines.append(f'            print("\\n[STEP] {step_num}. {goal}")')

            # 渲染动作
            action_code = self._render_action_simple(action, params, step_num)
            lines.append(action_code)

            # 渲染断言
            for a in asserts:
                assert_code = self._render_assert_simple(a, step_num)
                lines.append(assert_code)

            # 记录成功
            lines.append(f'            results.append({{"step": {step_num}, "goal": "{goal}", "success": True, "msg": "通过"}})')
            lines.append(f'            print("  [OK] 步骤通过")')
            lines.append('')

        return '\n'.join(lines)

    def _render_action_simple(self, action: str, params: dict, step_num: int) -> str:
        """渲染单个动作（纯线性版），失败抛异常"""
        indent = "            "
        if action == "goto":
            url = params.get("url", "")
            return f'{indent}page.goto("{url}", timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")\n' \
                   f'{indent}print("  [NAV] {url}")'
        elif action == "click":
            role = params.get("role", "")
            name = params.get("name", "")
            idx = params.get("index", "")
            locator = f'page.get_by_role("{role}"'
            if name:
                locator += f', name="{name}"'
            locator += ')'
            if idx:
                locator += f'.nth({idx})'
            return f'{indent}{locator}.wait_for(state="visible", timeout=ACTION_TIMEOUT)\n' \
                   f'{indent}{locator}.click(timeout=ACTION_TIMEOUT)\n' \
                   f'{indent}print("  [CLICK] 点击成功")'
        elif action == "fill":
            role = params.get("role", "")
            name = params.get("name", "")
            value = params.get("value", "")
            idx = params.get("index", "")
            locator = f'page.get_by_role("{role}"'
            if name:
                locator += f', name="{name}"'
            locator += ')'
            if idx:
                locator += f'.nth({idx})'
            return f'{indent}{locator}.wait_for(state="visible", timeout=ACTION_TIMEOUT)\n' \
                   f'{indent}{locator}.fill("{value}", timeout=ACTION_TIMEOUT)\n' \
                   f'{indent}print("  [FILL] 输入成功: {value}")'
        elif action == "scroll":
            offset = 600 if params.get("direction") == "down" else -600
            return f'{indent}page.evaluate("window.scrollBy(0, {offset})")\n' \
                   f'{indent}print("  [SCROLL] 滚动完成")'
        elif action == "finish":
            return f'{indent}print("  [FINISH] 步骤标记完成")'
        else:
            return f'{indent}print("  [WARN] 未处理动作: {action}")'

    def _render_assert_simple(self, assert_item: dict, step_num: int) -> str:
        """渲染单个断言（纯线性版），失败抛异常"""
        indent = "            "
        a_type = assert_item.get("type", "")
        a_target = assert_item.get("target", "")
        if a_type == "url_contains":
            return f'{indent}assert "{a_target}" in page.url, f"URL断言失败: 不含 \\"{a_target}\\", 当前URL: {{page.url}}"'
        elif a_type == "title_contains":
            return f'{indent}assert "{a_target}" in page.title(), f"标题断言失败: 不含 \\"{a_target}\\", 当前标题: {{page.title()}}"'
        elif a_type == "text_exists":
            return f'{indent}assert "{a_target}" in page.content(), f"文本断言失败: 页面不含 \\"{a_target}\\""'
        elif a_type == "url_exact":
            return f'{indent}assert page.url == "{a_target}", f"URL断言失败: 期望 \\"{a_target}\\", 实际: {{page.url}}"'
        else:
            return f'{indent}# 断言类型 {a_type}: {a_target}（需手动实现）'

    # ── 批量生成 ──

    def generate_all(self, output_dir: str = "generated_scripts",
                     force: bool = False) -> list[str]:
        """批量生成全部用例脚本

        Args:
            output_dir: 输出目录
            force: True=全量生成, False=仅生成有变更的

        Returns:
            生成的文件路径列表
        """
        if not self.store:
            raise RuntimeError("StandardCaseStore 不可用")

        cases = self.store.load_cases()

        # 变更检测
        if not force:
            changes = self.store.detect_changes()
            changed_ids = set(changes.get("changed", []) + changes.get("new", []))
            if changed_ids:
                cases = [c for c in cases if c["case_id"] in changed_ids]
                print(f"[GENERATOR] 检测到 {len(changed_ids)} 个变更用例，仅重新生成这些")
            else:
                print("[GENERATOR] 无变更用例，跳过生成。使用 --force 强制全量生成")
                return []

        os.makedirs(output_dir, exist_ok=True)
        generated = []

        for case in cases:
            case_id = case.get("case_id", "unknown")
            script_content = self.generate_script_simple(case)
            filepath = os.path.join(output_dir, f"{case_id}.py")

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(script_content)

            generated.append(filepath)
            print(f"  [GEN] {case_id}.py ({len(case.get('steps',[]))} 步)")

        # 保存 manifest
        self.store.save_manifest()

        print(f"\n[GENERATOR] 已生成 {len(generated)} 个脚本 → {os.path.abspath(output_dir)}/")
        print(f"  运行方式: python {output_dir}/TC001.py")
        print(f"  无头模式: python {output_dir}/TC001.py --headless")
        return generated

    def generate_one(self, case_id: str, output_dir: str = "generated_scripts") -> str:
        """生成单个用例的脚本"""
        if not self.store:
            raise RuntimeError("StandardCaseStore 不可用")

        case = self.store.load_case(case_id)
        if not case:
            raise ValueError(f"用例不存在: {case_id}")

        script_content = self.generate_script_simple(case)
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, f"{case_id}.py")

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(script_content)

        print(f"[GENERATOR] 已生成: {filepath}")
        return filepath


# ═══════════════════════════════════════════════
#  命令行
# ═══════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="生成 Playwright 测试脚本")
    parser.add_argument("--case", default="", help="指定单个用例ID")
    parser.add_argument("--force", action="store_true", help="强制全量生成")
    parser.add_argument("--output", default="generated_scripts", help="输出目录")
    args = parser.parse_args()

    gen = ScriptGenerator()

    if args.case:
        gen.generate_one(args.case, args.output)
    else:
        gen.generate_all(args.output, force=args.force)
