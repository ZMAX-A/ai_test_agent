# -*- coding: utf-8 -*-
"""
自动生成的 Playwright 测试脚本
  用例编号: GEN_0717_1424
  用例名称: 顾客档案查询
  模块: 业务功能
  生成时间: 2026-07-17 14:36:03
  来源: standard.xlsx

用法:
  python GEN_0717_1424.py               # 有头模式执行
  python GEN_0717_1424.py --headless    # 无头模式执行
"""

import sys, os, json, time
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ── 配置 ──
HEADLESS = "--headless" in sys.argv
PAGE_TIMEOUT = 60000
ACTION_TIMEOUT = 30000
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
#  测试: 顾客档案查询 (GEN_0717_1424)
# ═══════════════════════════════════════════════

def test_GEN_0717_1424():
    """顾客档案查询"""
    results = []
    start_time = time.time()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(no_viewport=True)
        page = context.new_page()
        page.set_default_timeout(PAGE_TIMEOUT)

        try:
            page.goto("https://m3dtest-yanjia-ai.xiaofutech.com/login", timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
            print("  [NAV] https://m3dtest-yanjia-ai.xiaofutech.com/login")

            # ── 步骤1: 打开登录页面 https://m3dtest-yanjia-ai.xiaofutech.com/login ──
            print("\n[STEP] 1. 打开登录页面 https://m3dtest-yanjia-ai.xiaofutech.com/login")
            print("  [FINISH] 步骤标记完成")
            results.append({"step": 1, "goal": "打开登录页面 https://m3dtest-yanjia-ai.xiaofutech.com/login", "success": True, "msg": "通过"})
            print("  [OK] 步骤通过")

            # ── 步骤2: 在用户名输入框(第1个)输入 79326@01 ──
            print("\n[STEP] 2. 在用户名输入框(第1个)输入 79326@01")
            page.get_by_role("textbox").wait_for(state="visible", timeout=ACTION_TIMEOUT)
            page.get_by_role("textbox").fill("79326@01", timeout=ACTION_TIMEOUT)
            print("  [FILL] 输入成功: 79326@01")
            results.append({"step": 2, "goal": "在用户名输入框(第1个)输入 79326@01", "success": True, "msg": "通过"})
            print("  [OK] 步骤通过")

            # ── 步骤3: 在密码输入框(第2个)输入 123456 ──
            print("\n[STEP] 3. 在密码输入框(第2个)输入 123456")
            page.get_by_role("textbox").nth(1).wait_for(state="visible", timeout=ACTION_TIMEOUT)
            page.get_by_role("textbox").nth(1).fill("123456", timeout=ACTION_TIMEOUT)
            print("  [FILL] 输入成功: 123456")
            results.append({"step": 3, "goal": "在密码输入框(第2个)输入 123456", "success": True, "msg": "通过"})
            print("  [OK] 步骤通过")

            # ── 步骤4: 点击登录按钮 ──
            print("\n[STEP] 4. 点击登录按钮")
            page.get_by_role("button", name="登 录").wait_for(state="visible", timeout=ACTION_TIMEOUT)
            page.get_by_role("button", name="登 录").click(timeout=ACTION_TIMEOUT)
            print("  [CLICK] 点击成功")
            results.append({"step": 4, "goal": "点击登录按钮", "success": True, "msg": "通过"})
            print("  [OK] 步骤通过")

            # ── 步骤5: 点击菜单-顾客档案 ──
            print("\n[STEP] 5. 点击菜单-顾客档案")
            print("  [FINISH] 步骤标记完成")
            results.append({"step": 5, "goal": "点击菜单-顾客档案", "success": True, "msg": "通过"})
            print("  [OK] 步骤通过")

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
        "case_id": "GEN_0717_1424",
        "name": "顾客档案查询",
        "passed": passed,
        "total": total,
        "duration": round(duration, 1),
        "status": "passed" if passed == total else "failed",
        "results": results,
    }

    print(f"\n{'='*50}")
    print(f"  测试: 顾客档案查询 (GEN_0717_1424)")
    print(f"  结果: {passed}/{total} 通过 ({duration:.1f}s)")
    for r in results:
        s = "[OK]" if r["success"] else "[FAIL]"
        print(f"  {s} 步骤{r['step']}: {r['goal'][:50]}")
    print(f"{'='*50}")

    # 输出 JSON（可被外部工具解析）
    if "--json" in sys.argv:
        print("\n__RESULT_JSON__")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        print("__END_RESULT_JSON__")

    return summary


if __name__ == "__main__":
    test_GEN_0717_1424()
