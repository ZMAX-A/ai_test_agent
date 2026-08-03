"""
回归执行器

读取标准用例（JSON 或 Excel），逐步骤直接调用 PlaywrightExecutor 执行。
全程不调用 LLM、不做感知快照、不做缓存加速，纯原生 Playwright 操作。

执行结果同步写入 Allure 报告，失败自动截图。
执行失败自动标记对应用例为待更新，结果回写到 standard.xlsx。
"""

import os
import time
from datetime import datetime

from config.settings import settings
from executor.playwright_exec import PlaywrightExecutor
from case import case_manager

# Excel 结果回写
try:
    from standard.store import get_store
    HAS_STORE = True
except ImportError:
    HAS_STORE = False


# ── Assert 类型到 PlaywrightExecutor 参数映射 ──
_ASSERT_MAP = {
    "url_contains": {"expect_url_contains": None},
    "url_exact":    {"expect_url_contains": None},
    "title_contains": {"expect_title_contains": None},
    "text_exists":  {"expect_text": None},
    "element_visible": {},
}


def _build_assert_params(assert_type: str, target: str) -> dict:
    """将标准化的断言转换回 executor 可识别的参数格式"""
    mapping = _ASSERT_MAP.get(assert_type, {})
    params = {}
    for k in mapping:
        params[k] = target
    # 特殊处理：text_exists 需要 role + expect_text
    if assert_type == "text_exists":
        params["locator_strategy"] = "role"
        params["role"] = "textbox"  # 兜底，优先用 expect_text 匹配
    if assert_type == "element_visible":
        params["locator_strategy"] = "role"
        params["role"] = "button"
        params["name"] = target
    return params


class RegressionRunner:
    """回归执行器：零 LLM，纯 Playwright 执行标准用例"""

    def __init__(self, page=None):
        self.page = page
        self.executor = None
        self.step_results = []
        self.allure = None

    def set_page(self, page):
        """绑定 Playwright page 和执行器"""
        self.page = page
        self.executor = PlaywrightExecutor(page)

    def set_allure(self, allure_instance):
        """绑定 Allure 报告实例"""
        self.allure = allure_instance

    # ── 主入口 ──────────────────────────────────

    def run_case(self, case: dict) -> dict:
        """执行一个标准用例，返回执行结果"""
        if not self.executor or not self.page:
            raise RuntimeError("RegressionRunner 未关联 page，请先调用 set_page(page)")

        case_id = case.get("case_id", "?")
        case_name = case.get("case_name", case.get("name", case_id))
        start_url = case.get("start_url", "")
        steps = case.get("steps", [])
        start_time = time.time()

        print(f"\n{'='*60}")
        print(f"  [REGRESSION] 执行: {case_name} ({case_id})")
        print(f"{'='*60}")

        # ── Allure 开始 ──
        if self.allure:
            self.allure.start_test(name=case_name, feature="回归测试", story=start_url)

        # ── 导航到起始页 ──
        if start_url:
            print(f"  [NAV] {start_url}")
            try:
                self.page.goto(start_url, timeout=settings.PAGE_TIMEOUT, wait_until="domcontentloaded")
            except Exception as e:
                print(f"  [WARN] 导航异常: {e}")

        self.step_results = []
        all_passed = True

        for step in steps:
            step_num = step.get("step", 0)
            goal = step.get("goal", "")
            action = step.get("action", "")
            params = dict(step.get("parameters", {}))
            asserts = step.get("asserts", [])

            print(f"\n  [STEP] {step_num}. {goal} ({action})")

            if self.allure:
                self.allure.start_step(goal)

            step_success = True
            step_msg = ""

            # ── 执行动作 ──
            if action == "goto":
                url = params.get("url", "")
                if url:
                    try:
                        self.page.goto(url, timeout=settings.PAGE_TIMEOUT, wait_until="domcontentloaded")
                        step_msg = f"导航成功: {url}"
                    except Exception as e:
                        step_success = False
                        step_msg = f"导航失败: {e}"
                else:
                    step_msg = "goto 未指定 url"
            elif action in ("click", "fill", "assert_text", "assert_url", "assert_title", "scroll"):
                try:
                    act_success, act_msg = self.executor.execute({
                        "action": action,
                        "parameters": params,
                    })
                    if not act_success:
                        step_success = False
                        step_msg = act_msg
                    else:
                        step_msg = act_msg
                except Exception as e:
                    step_success = False
                    step_msg = f"执行异常: {e}"
            elif action == "finish":
                step_msg = "步骤完成"
            else:
                step_msg = f"不支持的动作类型: {action}（跳过）"

            # ── 执行断言 ──
            if step_success and asserts:
                for a in asserts:
                    a_type = a.get("type", "")
                    a_target = a.get("target", "")
                    if not a_type or not a_target:
                        continue
                    try:
                        a_params = _build_assert_params(a_type, a_target)
                        a_success, a_msg = self.executor.execute({
                            "action": f"assert_{a_type}",
                            "parameters": a_params,
                        })
                        if not a_success:
                            step_success = False
                            step_msg = f"断言失败: {a_msg}"
                            break
                    except Exception as e:
                        step_success = False
                        step_msg = f"断言异常: {e}"
                        break

            # ── 失败截图 ──
            screenshot_path = None
            if not step_success:
                ts = datetime.now().strftime("%H%M%S")
                screenshot_dir = os.path.join(
                    os.path.dirname(os.path.dirname(__file__)), "report", "screenshots"
                )
                os.makedirs(screenshot_dir, exist_ok=True)
                filename = f"reg_{case_id}_step{step_num}_fail_{ts}.png"
                full_path = os.path.join(screenshot_dir, filename)
                try:
                    self.page.screenshot(path=full_path)
                    screenshot_path = os.path.join("screenshots", filename)
                except Exception:
                    pass

                if self.allure:
                    try:
                        self.allure.attach_screenshot(self.page, name=f"回归步骤{step_num}失败截图")
                    except Exception:
                        pass

            # ── 记录结果 ──
            self.step_results.append({
                "step": step_num,
                "goal": goal,
                "success": step_success,
                "msg": step_msg,
                "screenshot": screenshot_path,
            })

            if self.allure:
                s_status = "passed" if step_success else "failed"
                s_msg = step_msg if not step_success else None
                self.allure.stop_step(status=s_status, message=s_msg)

            status_tag = "[OK]" if step_success else "[FAIL]"
            print(f"  {status_tag} {step_msg[:80]}")

            if not step_success:
                all_passed = False
                break

        # ── 汇总 ──
        if self.allure:
            overall = "passed" if all_passed else "failed"
            self.allure.stop_test(status=overall)

        passed = sum(1 for r in self.step_results if r["success"])
        total = len(self.step_results)
        print(f"\n  [RESULT] {'[PASS]' if all_passed else '[FAIL]'} {passed}/{total} 步骤通过")

        duration = time.time() - start_time

        # ── 失败标记为待更新 ──
        if not all_passed:
            try:
                case_manager.mark_needs_update(case_id, case.get("module", ""))
                print(f"  [CASE] 已标记 {case_id} 为待更新")
            except Exception:
                pass

        # ── 结果回写到 standard.xlsx ──
        if HAS_STORE:
            try:
                store = get_store()
                store.write_results(case_id, {
                    "run_mode": "regression",
                    "total_steps": total,
                    "passed_steps": passed,
                    "duration": round(duration, 1),
                    "status": "passed" if all_passed else "failed",
                    "details": self.step_results,
                })
            except Exception as e:
                print(f"  [WARN] 结果回写失败: {e}")

        return {
            "case_id": case_id,
            "name": case_name,
            "all_passed": all_passed,
            "passed": passed,
            "total": total,
            "duration": round(duration, 1),
            "results": self.step_results,
        }
