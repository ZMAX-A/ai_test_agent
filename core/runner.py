import re
import os
import time
from datetime import datetime
from playwright.sync_api import sync_playwright, Page
from config.settings import settings
from perception.aria_sensor import AriaSensor
from perception.visual_sensor import VisualSensor
from agents.planner_agent import PlannerAgent
from agents.executor_agent import ExecutorAgent
from executor.playwright_exec import PlaywrightExecutor
from executor.action_validator import validate_action
from core.self_healer import SelfHealer
from pom.element_cache import ElementCache
from urllib.parse import urlparse
from memory.memory_manager import MemoryManager
from core.reasoning_engine import StepReasoningState

# 探索模式与用例生成（可选）
try:
    from case import case_generator
    HAS_CASE_GEN = True
except ImportError:
    HAS_CASE_GEN = False

try:
    from runner.regression_runner import RegressionRunner
    HAS_REG_RUNNER = True
except ImportError:
    HAS_REG_RUNNER = False

# 标准用例库
try:
    from standard.store import StandardCaseStore, get_store
    HAS_STORE = True
except ImportError:
    HAS_STORE = False

# ReAct 闭环执行器
try:
    from agents.react_executor import ReactExecutor
    HAS_REACT = True
except ImportError:
    HAS_REACT = False

# Allure 报告（可选依赖，不影响核心流程）
try:
    from report.allure_reporter import AllureReport
    HAS_ALLURE = True
except ImportError:
    HAS_ALLURE = False


class TestRunner:
    def __init__(self, start_url: str = "https://www.baidu.com"):
        self.start_url = start_url
        self.planner = PlannerAgent()
        self.executor_agent = ExecutorAgent()
        self.aria_sensor = AriaSensor()
        self.visual_sensor = VisualSensor()
        self.healer = SelfHealer()
        self.step_results = []
        self.element_cache = ElementCache()
        # 模型调用统计
        self.model_calls = {}  # {"模型名": 调用次数}
        self.allure = None  # Allure 报告实例，run() 中惰性初始化
        self.memory = MemoryManager()  # 记忆管理器

    def _log_model_call(self, model: str, role: str):
        """记录并打印一次模型调用"""
        self.model_calls[model] = self.model_calls.get(model, 0) + 1
        call_count = self.model_calls[model]
        print(f"[MODEL] [{model}] ({role}) 第{call_count}次调用")

    @staticmethod
    def _clean_som_marks(page):
        """清理页面上SoM视觉标注残留（保留 data-som-index 供定位使用）"""
        try:
            page.evaluate("""
                document.querySelectorAll('div[style*="pointerEvents:none"]').forEach(d=>d.remove());
                delete window.__som_map;
            """)
        except Exception:
            pass

    def run(self, user_task: str, custom_steps: list = None):
        """主入口：支持自然语言任务/自定义步骤两种模式"""
        with sync_playwright() as p:
            # ── 初始化浏览器 ──
            browser = p.chromium.launch(
                headless=False,
                args=["--disable-blink-features=AutomationControlled"]
            )
            context = browser.new_context(no_viewport=True)
            page = context.new_page()
            page.goto(self.start_url, timeout=settings.PAGE_TIMEOUT)

            # ── 截图目录 ──
            screenshot_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "report", "screenshots")
            os.makedirs(screenshot_dir, exist_ok=True)

            # ── Allure 报告（可选） ──
            if HAS_ALLURE:
                self.allure = AllureReport(report_dir="allure-results")

            executor = PlaywrightExecutor(page, visual_sensor=self.visual_sensor)

            # ── 1. 规划阶段（含流程记忆） ──
            if custom_steps:
                steps = custom_steps
            else:
                system = urlparse(self.start_url).netloc
                cached_flow = self.memory.find_flow(system, user_task)
                if cached_flow:
                    steps = cached_flow["steps"]
                    rate = cached_flow["success_count"] / max(cached_flow["total_count"], 1)
                    print(f"[MEMORY] 命中流程记忆！复用历史步骤 ({cached_flow['success_count']}/{cached_flow['total_count']} 次成功)")
                else:
                    print("[PLAN] 正在规划测试步骤...")
                    self._log_model_call(self.planner.model_name, "Planner 规划")
                    self.healer.record_api_call()
                    plan_result = self.planner.ask({"user_task": user_task})
                    steps = plan_result["steps"]
                    print(f"[OK] 规划完成，共{len(steps)}步")

            # ── Allure: 开始测试用例 ──
            if self.allure:
                self.allure.start_test(name=user_task, feature="测试套件", story=self.start_url)

            # ── 2. 执行阶段 ──
            global_step = 0
            for idx, step in enumerate(steps):
                step_num = idx + 1

                # ── 熔断检测：每步开始前检查 ──
                if self.healer.check_fuse():
                    print(f"\n{'='*50}")
                    print(f"[SKIP] 第{step_num}步跳过（熔断已触发）：{step['goal']}")
                    self.step_results.append({
                        "step": step_num,
                        "goal": step["goal"],
                        "success": False,
                        "msg": "全局熔断已触发，跳过执行"
                    })
                    continue

                print(f"\n{'='*50}")
                print(f"[STEP] 第{step_num}步目标：{step['goal']}")
                self.healer.reset_step()
                last_result = "无"
                step_success = False
                action_history = []
                last_good_action = None
                last_good_url = ""
                cache_tried = False

                # ── Allure: 开始步骤 ──
                if self.allure:
                    self.allure.start_step(step["goal"])

                while self.healer.should_retry() and global_step < settings.MAX_GLOBAL_STEPS:
                    global_step += 1
                    print(f"\n--- 执行轮次 {global_step} ---")

                    # ── 策略追踪（上报已尝试策略给LLM，辅助自主反思） ──
                    tried_strategies_desc = "无（首次尝试）"
                    if action_history:
                        strategies = []
                        for h in action_history[-3:]:
                            a = h.get("action", "?")
                            p = h.get("parameters", {})
                            strategies.append(f"{a}(role={p.get('role','?')},name={p.get('name','?')})")
                        tried_strategies_desc = "已尝试: " + " → ".join(strategies)

                    # ── 死循环检测 ──
                    if len(action_history) >= 3:
                        recent = action_history[-3:]
                        if all(a.get("action") == recent[0].get("action")
                               and a.get("parameters") == recent[0].get("parameters")
                               for a in recent):
                            last_action = recent[0]
                            print(f"[WARN] 检测到死循环：连续3次相同动作 {last_action['action']}，强制跳过本步骤")
                            last_result = f"死循环：连续{len(action_history)}次{last_action['action']}均未达成"
                            self.healer.record_fail()
                            break

                    # ── 缓存直通：完整动作缓存命中时跳过感知+LLM ──
                    cached_action = None
                    if not cache_tried and not self.healer.use_visual:
                        cached_action = self.element_cache.get_action(step['goal'], page.url)
                        cache_tried = True

                    if cached_action:
                        print(f"[CACHE] 缓存直通：执行缓存完整动作 [{cached_action.get('action')}]")
                        exec_result = executor.execute(cached_action)
                        success = exec_result["success"]; msg = exec_result["message"]
                        last_result = msg
                        self._clean_som_marks(page)

                        if success:
                            step_success = True
                            break
                        else:
                            print(f"[WARN] 缓存直通失败，删除缓存降级: {msg}")
                            self.element_cache.delete_action(step['goal'], page.url)
                            last_result = msg
                            continue

                    # ── 感知层 ──
                    if self.healer.use_visual:
                        self._log_model_call(self.visual_sensor.model_name, "Visual 视觉感知")
                        print("[VISUAL] 触发视觉感知兜底")
                        page_state = self.visual_sensor.capture(page, step_goal=step.get("goal", ""))
                    else:
                        page_state = self.aria_sensor.capture(page)

                    # ── 决策层：元素缓存加速 ──
                    cached = None
                    if not cache_tried and not self.healer.use_visual:
                        cached = self.element_cache.get(step["goal"], page.url)
                        cache_tried = True

                    if cached:
                        # ── 缓存命中路径 ──
                        is_fill = any(kw in step["goal"] for kw in ("输入", "填入", "搜索"))
                        value = step["goal"]
                        if is_fill:
                            m = re.search(r"(?:输入|填入)(.+?)(?:$|，|。|到|在)", step["goal"])
                            if not m:
                                m = re.search(r"搜索(.+?)(?:$|，|。)", step["goal"])
                            value = m.group(1).strip() if m else step["goal"]
                        action = {
                            "thought": f"[缓存加速] 复用历史定位策略 role={cached.get('role','?')}",
                            "action": "fill" if is_fill else "click",
                            "parameters": {
                                "role": cached.get("role"),
                                "name": cached.get("name", ""),
                                "value": value if is_fill else None,
                            },
                        }
                        action["parameters"] = {k: v for k, v in action["parameters"].items() if v is not None}

                        exec_result = executor.execute(action)
                        success = exec_result["success"]; msg = exec_result["message"]
                        last_result = msg
                        self._clean_som_marks(page)

                        if success:
                            print("[CACHE] 缓存动作执行成功，步骤目标已达成")
                            last_result = f"缓存加速完成: {msg}"
                            step_success = True
                            break
                        else:
                            # ── 主动失效：缓存策略执行失败，作废该条目 ──
                            print(f"[WARN] 缓存策略执行失败，降级LLM: {msg}")
                            self.element_cache.invalidate(step["goal"], page.url)
                            cached = None
                            last_result = msg
                            continue
                    else:
                        # ── LLM 决策路径 ──
                        self._log_model_call(self.executor_agent.model_name, "Executor 执行决策")
                        self.healer.record_api_call()
                        action = self.executor_agent.ask({
                            "step_goal": step["goal"],
                            "last_result": last_result,
                            "page_state": page_state,
                            "tried_strategies": tried_strategies_desc
                        })

                        # ── 动作校验：拦截脏数据 ──
                        is_valid, err_msg = validate_action(action)
                        if not is_valid:
                            print(f"[WARN] 动作校验不通过: {err_msg}")
                            print(f"   原始动作: {action}")
                            last_result = f"动作校验被拦截: {err_msg}"
                            self.healer.record_fail()
                            continue

                        exec_result = executor.execute(action)
                        success = exec_result["success"]; msg = exec_result["message"]
                        last_result = msg

                        if action.get("action") != "finish":
                            action_history.append({
                                "action": action.get("action"),
                                "parameters": action.get("parameters", {})
                            })

                        self._clean_som_marks(page)

                        if success:
                            if action.get("action") in ("click", "fill") and not self.healer.use_visual:
                                role = action.get("parameters", {}).get("role", "")
                                if ("输入" in step["goal"] and role in ("textbox", "combobox", "searchbox")) \
                                   or ("点击" in step["goal"] and role in ("button", "link")) \
                                   or ("输入" not in step["goal"] and "点击" not in step["goal"]):
                                    last_good_action = action
                                    last_good_url = page.url
                            if action["action"] == "finish":
                                if last_good_action and not self.healer.use_visual:
                                    params = last_good_action.get("parameters", {})
                                    if "role" in params:
                                        n = params.get("name", "")
                                        if len(n) > 6 and not any(kw in n for kw in ("按钮", "搜索框", "输入框")):
                                            n = ""
                                        self.element_cache.record(
                                            goal_text=step["goal"],
                                            url=last_good_url,
                                            strategy={"role": params["role"], "name": n}
                                        )
                                        # ── 新增：缓存完整动作指令 ──
                                        self.element_cache.set_action(
                                            goal_text=step["goal"],
                                            url=last_good_url,
                                            action=last_good_action
                                        )
                                step_success = True
                                break
                        else:
                            print(f"[FAIL] 失败：{msg}")
                            self.healer.record_fail()

                # ── 失败截图 ──
                screenshot_path = None
                if not step_success:
                    ts = datetime.now().strftime("%H%M%S")
                    filename = f"step{step_num}_fail_{ts}.png"
                    full_path = os.path.join(screenshot_dir, filename)
                    try:
                        page.screenshot(path=full_path)
                        screenshot_path = os.path.join("screenshots", filename)
                        print(f"[SCREENSHOT] 失败截图已保存：{full_path}")
                    except Exception as e:
                        print(f"[WARN] 截图失败：{e}")

                # ── Allure: 失败步骤挂载截图 + 页面快照 ──
                if self.allure and not step_success:
                    self.allure.attach_screenshot(page, name=f"步骤{step_num}失败截图")
                    try:
                        aria_state = self.aria_sensor.capture(page)
                        snapshot_text = str(aria_state)
                        if snapshot_text:
                            self.allure.attach_text(snapshot_text[:3000], name=f"步骤{step_num}页面快照")
                    except Exception:
                        pass

                self.step_results.append({
                    "step": step_num,
                    "goal": step["goal"],
                    "success": step_success,
                    "msg": last_result,
                    "screenshot": screenshot_path,
                    "model_calls": dict(self.model_calls)
                })
                # ── Allure: 结束步骤 ──
                if self.allure:
                    allure_step_status = "passed" if step_success else "failed"
                    allure_msg = last_result if not step_success else None
                    self.allure.stop_step(status=allure_step_status, message=allure_msg)

                status = "[OK] 通过" if step_success else "[FAIL] 失败"
                print(f"\n第{step_num}步结果：{status}")

                # ── 跨步骤熔断计数 ──
                if step_success:
                    self.healer.record_step_success()
                else:
                    self.healer.record_step_fail()

                # ── 失败记忆：记住翻车原因 ──
                if not step_success:
                    try:
                        self.memory.record_failure(urlparse(self.start_url).netloc, step["goal"], page.url, last_result)
                    except Exception:
                        pass

            # ── 3. 汇总结果 ──
            print(f"\n{'='*50}")
            fuse_note = " [SKIP] 测试被熔断中断" if self.healer.is_fuse_blown else ""
            print(f"[REPORT] 测试执行汇总{fuse_note}")
            for res in self.step_results:
                s = "通过" if res["success"] else "失败"
                print(f"  步骤{res['step']} [{s}]：{res['goal']}")
            print(f"  本轮API调用: {self.healer.api_call_count} 次")
            print(f"  [MODEL] 模型调用明细:")
            for model, count in sorted(self.model_calls.items()):
                print(f"    · {model}: {count} 次")
            print(f"  [CACHE] 缓存命中: {sum(1 for r in self.step_results if '缓存加速' in str(r.get('msg','')))} 次")

            # ── 流程记忆：全部通过则记住流程 ──
            all_passed = all(r["success"] for r in self.step_results)
            if all_passed and not custom_steps:
                try:
                    self.memory.record_flow(urlparse(self.start_url).netloc, user_task, steps)
                except Exception:
                    pass

            # ── 记忆统计 ──
            try:
                flow_stats = self.memory.get_flow_stats()
                if flow_stats:
                    print(f"  [MEMORY] 已记忆 {len(flow_stats)} 个流程")
            except Exception:
                pass

            # ── Allure: 结束测试 ──
            if self.allure:
                overall = "failed" if any(not r["success"] for r in self.step_results) else "passed"
                self.allure.stop_test(status=overall)

            browser.close()
            print("\n[DONE] 测试结束，浏览器已关闭")

            return self.step_results

    # ════════════════════════════════════════════════════════════
    #  探索模式（Explore Mode）
    # ════════════════════════════════════════════════════════════

    def explore(self, task_name: str, steps: list,
                start_url: str = "https://www.baidu.com",
                module: str = "", preconditions: str = "") -> dict:
        system = urlparse(start_url).netloc or "unknown"
        exploration_trace = []
        all_results = []
        deadline = time.monotonic() + settings.EXPLORE_TASK_TIMEOUT_SECONDS

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(no_viewport=True)
            page = context.new_page()
            page.goto(start_url, timeout=settings.PAGE_TIMEOUT)

            screenshot_dir = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "report", "screenshots"
            )
            os.makedirs(screenshot_dir, exist_ok=True)

            if HAS_ALLURE:
                self.allure = AllureReport(report_dir="allure-results")
                self.allure.start_test(name=f"[探索] {task_name}", feature="探索模式", story=start_url)

            executor = PlaywrightExecutor(page, visual_sensor=self.visual_sensor)
            overall_success = True

            for idx, step in enumerate(steps):
                if time.monotonic() >= deadline:
                    overall_success = False
                    print(f"  [FUSE] 探索任务超过总时限 {settings.EXPLORE_TASK_TIMEOUT_SECONDS}s")
                    break
                goal = step.get("goal", "")
                step_num = idx + 1

                print(f"\n{'='*50}")
                print(f"[EXPLORE] 第{step_num}步: {goal}")

                if self.allure:
                    self.allure.start_step(goal)

                step_success = False
                last_result = "无"
                loop_iteration = 0
                fail_count = 0
                step_actions = []
                tried_strategies_list = []
                MAX_ACTIONS_PER_STEP = settings.MAX_REASONING_ROUNDS
                reasoning = StepReasoningState(
                    goal=goal,
                    success_criteria=step.get("success_criteria", "") or step.get("assert", ""),
                    max_rounds=MAX_ACTIONS_PER_STEP,
                )

                # ── 预检查：页面就绪 ──
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=5000)
                except Exception:
                    pass

                # ── 注入历史失败记忆 ──
                try:
                    system = urlparse(start_url).netloc
                    failures = self.memory.get_failures(system, goal)
                    if failures:
                        fail_hints = "；".join(f["fail_reason"][:80] for f in failures[:3])
                        reasoning.lessons = [f["fail_reason"][:160] for f in failures[:3]]
                        print(f"  [MEMORY] 历史失败教训: {fail_hints}")
                except Exception:
                    pass

                while (
                    fail_count < settings.MAX_STEP_RETRY + 1
                    and loop_iteration < MAX_ACTIONS_PER_STEP
                    and time.monotonic() < deadline
                ):
                    loop_iteration += 1

                    # 感知（仅失败后切换视觉）
                    use_visual = fail_count > 0 or reasoning.should_use_visual()
                    try:
                        if use_visual:
                            print(f"  [VISUAL] 已失败{fail_count}次，切换到视觉SoM感知")
                            page_state = self.visual_sensor.capture(page, step_goal=goal)
                        else:
                            page_state = self.aria_sensor.capture(page)
                    except Exception:
                        page_state = "(感知异常)"

                    try:
                        current_url = page.url
                        current_title = page.title() or ""
                    except Exception:
                        current_url = ""
                        current_title = ""
                    reasoning.observe(page_state, current_url, current_title)

                    # 页面本身已满足目标时由控制器直接完成，不浪费一次模型调用。
                    already_done, existing_evidence = reasoning.can_finish_success()
                    if already_done:
                        step_success = True
                        last_result = f"控制器自动完成: {existing_evidence}"
                        print(f"  [EVIDENCE] {last_result}")
                        break

                    # ── 构建已尝试策略描述 ──
                    tried_desc = "无（首次尝试）"
                    if tried_strategies_list:
                        tried_desc = "已尝试: " + " → ".join(tried_strategies_list[-3:])

                    # 决策：明确URL目标优先走确定性动作，其他情况再调用模型。
                    action = reasoning.deterministic_action()
                    if action and reasoning.repeated_on_same_observation(action):
                        action = None
                    if action:
                        print(f"  [REASON] 零模型决策: {action['parameters'].get('url', '')}")
                    else:
                        if self.healer.api_budget_exhausted:
                            last_result = f"API调用预算已耗尽 ({self.healer.api_call_count}/{settings.MAX_API_CALLS})"
                            print(f"  [FUSE] {last_result}")
                            break
                        self._log_model_call(self.executor_agent.model_name, "Explore 执行决策")
                        self.healer.record_api_call()
                        try:
                            action = self.executor_agent.ask({
                                "step_goal": goal,
                                "last_result": last_result,
                                "page_state": page_state,
                                "tried_strategies": tried_desc,
                                "page_url": current_url,
                                "page_title": current_title,
                                "reasoning_state": reasoning.prompt_context(loop_iteration),
                            })
                        except Exception as e:
                            print(f"  [FAIL] LLM 调用异常: {e}")
                            last_result = f"LLM异常: {e}"
                            fail_count += 1
                            continue

                    action, repair_notes = reasoning.repair_action(action)
                    for note in repair_notes:
                        print(f"  [REPAIR] {note}")

                    # ── 控制器门禁：禁止无证据完成、禁止同状态重复动作 ──
                    if reasoning.repeated_on_same_observation(action):
                        last_result = "控制器拦截：相同页面状态下已执行过完全相同的动作，请换假设或先观察变化"
                        reasoning.record(
                            loop_iteration, action,
                            {"success": False, "error_type": "DUPLICATE_STRATEGY", "message": last_result},
                            current_url, current_url,
                        )
                        fail_count += 1
                        print(f"  [REASON] {last_result}")
                        continue

                    if action.get("action") == "finish":
                        result_text = action.get("parameters", {}).get("result", "success")
                        if result_text == "success":
                            finish_allowed, finish_evidence = reasoning.can_finish_success()
                            if not finish_allowed:
                                last_result = f"控制器拒绝无证据完成：{finish_evidence}"
                                reasoning.record(
                                    loop_iteration, action,
                                    {"success": False, "error_type": "UNGROUNDED_FINISH", "message": last_result},
                                    current_url, current_url,
                                )
                                fail_count += 1
                                print(f"  [REASON] {last_result}")
                                continue
                            print(f"  [EVIDENCE] 允许完成：{finish_evidence}")

                    # 校验
                    is_valid, err_msg = validate_action(action)
                    if not is_valid:
                        print(f"  [WARN] 校验不通过: {err_msg}")
                        last_result = f"校验拦截: {err_msg}"
                        tried_strategies_list.append(f"invalid({err_msg[:20]})")
                        fail_count += 1
                        continue

                    # 追踪策略
                    act_name = action.get("action", "?")
                    act_params = action.get("parameters", {})
                    strategy_key = f"{act_name}(role={act_params.get('role','?')},name={act_params.get('name','?')},som={act_params.get('som_index','?')})"
                    tried_strategies_list.append(strategy_key)

                    # 死循环检测
                    if len(tried_strategies_list) >= 3:
                        last3 = tried_strategies_list[-3:]
                        if len(set(last3)) == 1:
                            print(f"  [WARN] 检测到策略死循环: {last3[0]} 已连续3次，强制finish")
                            action = {"action": "finish", "parameters": {"result": f"fail: 死循环策略 {strategy_key} 重复3次"}}

                    # 记录动作
                    if action.get("action") != "finish":
                        step_actions.append(action)

                    # 执行
                    url_before = current_url
                    exec_result = None
                    try:
                        exec_result = executor.execute(action)
                        success = exec_result["success"]; msg = exec_result["message"]
                        last_result = msg
                    except Exception as e:
                        err_msg = str(e)
                        last_result = f"执行异常: {err_msg}"
                        msg = last_result
                        success = False
                    try:
                        url_after = page.url
                    except Exception:
                        url_after = url_before
                    reasoning.record(loop_iteration, action, exec_result or {
                        "success": success,
                        "error_type": "EXECUTION_EXCEPTION" if not success else "",
                        "message": msg,
                    }, url_before, url_after)

                    # ── 浏览器关闭检测与恢复 ──
                    if not success and ("has been closed" in msg.lower() or "target closed" in msg.lower()):
                        print(f"  [RECOVERY] 检测到浏览器页面关闭，尝试恢复...")
                        try:
                            # 先尝试复用现有有效页面
                            all_pages = context.pages
                            recovered = False
                            for p in all_pages:
                                try:
                                    _ = p.url
                                    page = p
                                    page.goto(start_url, timeout=30000)
                                    executor.page = page
                                    print(f"  [RECOVERY] 复用已有页面，导航到 {start_url}")
                                    recovered = True
                                    break
                                except Exception:
                                    continue
                            if not recovered:
                                page = context.new_page()
                                page.goto(start_url, timeout=30000)
                                executor.page = page
                                print(f"  [RECOVERY] 已创建新页面，导航到 {start_url}")
                            last_result = "恢复: 已重新打开页面"
                            continue
                        except Exception as recover_err:
                            print(f"  [RECOVERY] 恢复失败: {recover_err}")

                    self._clean_som_marks(page)

                    # 关键点击先等待页面响应，再判断是否具备自动完成证据。
                    if success and action.get("action") == "click":
                        last_name = action.get("parameters", {}).get("name", "")
                        nav_keywords = ("登录", "登 录", "Login", "Sign in", "提交", "Submit", "确定", "确认")
                        if any(kw in last_name for kw in nav_keywords):
                            try:
                                page.wait_for_load_state("networkidle", timeout=5000)
                            except Exception:
                                pass
                            page.wait_for_timeout(1000)
                            try:
                                reasoning.current_url = page.url
                                reasoning.current_title = page.title() or ""
                            except Exception:
                                pass

                    # 成功动作产生强证据时直接完成，避免再调用模型只为输出 finish。
                    if success and action.get("action") != "finish":
                        auto_done, auto_evidence = reasoning.can_finish_success()
                        if auto_done:
                            step_success = True
                            last_result = f"控制器自动完成: {auto_evidence}"
                            print(f"  [EVIDENCE] {last_result}")
                            break

                    if success:
                        if action.get("action") == "finish":
                            if step_actions:
                                last_act = step_actions[-1]
                                if last_act.get("action") == "click":
                                    last_name = last_act.get("parameters", {}).get("name", "")
                                    nav_keywords = ("登录", "登 录", "Login", "Sign in", "提交", "Submit", "确定", "确认", "选择", "门店", "知道了", "OK")
                                    is_nav_click = any(kw in last_name for kw in nav_keywords) or \
                                                   any(kw in str(last_act.get("parameters", {})) for kw in nav_keywords)
                                    if is_nav_click:
                                        print(f"  [WAIT] 检测到关键按钮点击，等待页面响应...")
                                        try:
                                            page.wait_for_load_state("networkidle", timeout=8000)
                                            page.wait_for_timeout(1500)
                                            print(f"  [WAIT] 当前URL: {page.url}")
                                        except Exception:
                                            print(f"  [WAIT] 等待完成，当前URL: {page.url}")
                            result_text = action.get("parameters", {}).get("result", "success")
                            step_success = (result_text == "success")
                            break
                        # 非 finish 成功 → 继续循环
                        print(f"  [>>] 子动作完成，继续当前步骤...")
                    else:
                        fail_count += 1
                        print(f"  [RETRY] 失败 ({fail_count}/{settings.MAX_STEP_RETRY+1}): {msg}")

                # ── 步骤未完成原因诊断 ──
                if not step_success:
                    if time.monotonic() >= deadline:
                        print(f"  [FUSE] 探索任务达到总时限 {settings.EXPLORE_TASK_TIMEOUT_SECONDS}s")
                        last_result = f"探索总时限({settings.EXPLORE_TASK_TIMEOUT_SECONDS}s)内未达成目标"
                    elif loop_iteration >= MAX_ACTIONS_PER_STEP:
                        print(f"  [WARN] 单步推理已达上限 {MAX_ACTIONS_PER_STEP} 轮，强制结束")
                        last_result = f"推理超限({MAX_ACTIONS_PER_STEP}轮)未达成目标"
                    elif fail_count >= settings.MAX_STEP_RETRY + 1:
                        print(f"  [WARN] 失败重试次数已达上限，放弃本步骤")
                        last_result = f"失败{settings.MAX_STEP_RETRY+1}次后放弃: {last_result}"

                # ── 记录 trace ──
                css_selector = ""
                if step_actions:
                    last_act = step_actions[-1]
                    if last_act.get("action") in ("click", "fill", "select_option"):
                        css_selector = executor.get_css_selector(last_act.get("parameters", {}), last_act.get("action", ""))
                exploration_trace.append({
                    "goal": goal,
                    "action": step_actions[-1]["action"] if step_actions else "finish",
                    "parameters": step_actions[-1]["parameters"] if step_actions else {},
                    "page_url": page.url,
                    "all_actions": step_actions,
                    "css_selector": css_selector,
                    "completion_evidence": reasoning.completion_evidence(),
                })

                # ── 失败截图 ──
                screenshot_path = None
                if not step_success:
                    ts = datetime.now().strftime("%H%M%S")
                    filename = f"explore_step{step_num}_fail_{ts}.png"
                    full_path = os.path.join(screenshot_dir, filename)
                    try:
                        page.screenshot(path=full_path)
                        screenshot_path = os.path.join("screenshots", filename)
                    except Exception:
                        pass

                    if self.allure:
                        try:
                            self.allure.attach_screenshot(page, name=f"探索步骤{step_num}失败截图")
                        except Exception:
                            pass

                all_results.append({
                    "step": step_num,
                    "goal": goal,
                    "success": step_success,
                    "msg": last_result,
                    "screenshot": screenshot_path,
                })

                if self.allure:
                    s_status = "passed" if step_success else "failed"
                    self.allure.stop_step(status=s_status, message=last_result if not step_success else None)

                status = "[OK]" if step_success else "[FAIL]"
                print(f"  第{step_num}步结果: {status} {last_result[:60]}")

                if step_success:
                    self.healer.record_step_success()
                else:
                    self.healer.record_step_fail()
                    try:
                        self.memory.record_failure(system, goal, page.url, last_result)
                    except Exception:
                        pass

                if not step_success:
                    overall_success = False
                    break

            # ── Allure 结束 ──
            if self.allure:
                overall = "passed" if overall_success else "failed"
                self.allure.stop_test(status=overall)

            browser.close()
            print(f"\n[DONE] 探索完成，{'全部通过' if overall_success else '存在失败'}")

        # ── 全部成功 → 生成标准用例 ──
        case_id = None
        if overall_success and HAS_CASE_GEN:
            try:
                # 稳定 case_id，同模块+同名覆盖旧记录
                safe_module = re.sub(r'[\\/:*?"<>|]', '_', module or '通用')[:20]
                safe_name = re.sub(r'[\\/:*?"<>|]', '_', task_name)[:30]
                case_id = f"GEN_{safe_module}_{safe_name}"
                path = case_generator.generate_and_save(
                    trace=exploration_trace,
                    case_id=case_id,
                    case_name=task_name,
                    module=module,
                    preconditions=preconditions,
                    start_url=start_url,
                )
                if path:
                    print(f"  [CASE] 用例已保存: {path}")
            except Exception as e:
                print(f"  [WARN] 用例生成失败: {e}")

        return {
            "success": overall_success,
            "results": all_results,
            "trace": exploration_trace,
            "case_id": case_id,
        }
