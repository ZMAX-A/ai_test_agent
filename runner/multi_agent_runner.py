"""真正的多 Agent Web 探索执行链。

职责边界：
- CoordinatorAgent：路由感知、控制预算、决定继续或停止
- ExecutorAgent：只提出浏览器动作
- VerifierAgent：独立回读页面并裁决步骤是否完成
- TaskBlackboard：共享结构化事实和协作事件
"""

from __future__ import annotations

from datetime import datetime
import os
import re
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from agents.coordinator_agent import CoordinatorAgent
from agents.executor_agent import ExecutorAgent
from agents.verifier_agent import VerifierAgent
from case import case_generator
from config.settings import settings
from core.blackboard import TaskBlackboard
from core.reasoning_engine import StepReasoningState
from executor.action_validator import validate_action
from executor.playwright_exec import PlaywrightExecutor
from perception.aria_sensor import AriaSensor
from perception.visual_sensor import VisualSensor


class MultiAgentTestRunner:
    def __init__(self, headless: bool = False):
        self.headless = headless
        self.coordinator = CoordinatorAgent()
        self.executor_agent = ExecutorAgent()
        self.verifier = VerifierAgent()
        self.aria_sensor = AriaSensor()
        self.visual_sensor = VisualSensor()

    @staticmethod
    def _clean_som_marks(page) -> None:
        try:
            page.evaluate("""
                document.querySelectorAll('div[style*="pointerEvents:none"]').forEach(d=>d.remove());
                delete window.__som_map;
            """)
        except Exception:
            pass

    def run_case(self, task_name: str, steps: list[dict], start_url: str,
                 module: str = "", preconditions: str = "") -> dict:
        system = urlparse(start_url).netloc or "unknown"
        deadline = time.monotonic() + settings.EXPLORE_TASK_TIMEOUT_SECONDS
        blackboard = TaskBlackboard(
            task_id=f"multi:{system}:{task_name}",
            task_name=task_name,
            global_goal=task_name,
        )
        blackboard.publish("coordinator", "task_started", start_url=start_url, step_count=len(steps))
        trace: list[dict] = []
        results: list[dict] = []
        overall_success = True

        screenshot_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "report", "screenshots"
        )
        os.makedirs(screenshot_dir, exist_ok=True)

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(no_viewport=True)
            page = context.new_page()
            page.goto(start_url, timeout=settings.PAGE_TIMEOUT)
            executor = PlaywrightExecutor(page, visual_sensor=self.visual_sensor)

            try:
                for step_num, step in enumerate(steps, 1):
                    goal = step.get("goal", "")
                    criteria = step.get("success_criteria", "") or step.get("assert", "")
                    blackboard.start_step(step_num, goal, criteria)
                    print(f"\n[MULTI-AGENT] 第{step_num}步: {goal}")

                    reasoning = StepReasoningState(
                        goal=goal,
                        success_criteria=criteria,
                        max_rounds=settings.MAX_REASONING_ROUNDS,
                    )
                    step_actions: list[dict] = []
                    last_action = None
                    last_result = None
                    last_verification = None
                    fail_count = 0
                    step_success = False
                    message = "未执行"

                    for round_num in range(1, settings.MAX_REASONING_ROUNDS + 1):
                        coordination = self.coordinator.before_decision(
                            blackboard, deadline, blackboard.model_calls,
                        )
                        if coordination.stop:
                            message = coordination.reason
                            blackboard.publish("coordinator", "stopped", reason=message)
                            break

                        perception = self.coordinator.choose_perception(reasoning, fail_count)
                        blackboard.publish(
                            "coordinator", "route",
                            route=perception.route, reason=perception.reason,
                        )
                        try:
                            if perception.route == "visual_sensor":
                                blackboard.model_calls += 1
                                page_state = self.visual_sensor.capture(page, step_goal=goal)
                            else:
                                page_state = self.aria_sensor.capture(page)
                        except Exception as exc:
                            page_state = f"感知异常: {exc}"

                        reasoning.observe(page_state, page.url, page.title() or "")
                        blackboard.publish(
                            "perception", "page_observed",
                            sensor=perception.route,
                            url=page.url,
                            title=page.title() or "",
                            fingerprint=reasoning.observation_fingerprint,
                        )

                        verification = self.verifier.verify(
                            page, goal, criteria, page_state,
                            action=last_action, action_result=last_result,
                        )
                        last_verification = verification
                        blackboard.record_verification(verification.to_dict())
                        if self.coordinator.after_verification(verification).route == "complete_step":
                            step_success = True
                            message = f"Verifier通过: {'；'.join(verification.evidence)}"
                            print(f"  [VERIFIER] {message}")
                            break

                        action = reasoning.deterministic_action()
                        if action and reasoning.repeated_on_same_observation(action):
                            action = None
                        if action:
                            blackboard.publish("coordinator", "deterministic_action", action=action)
                            print(f"  [COORDINATOR] 确定性动作: {action['action']}")
                        else:
                            blackboard.model_calls += 1
                            action = self.executor_agent.ask({
                                "step_goal": goal,
                                "last_result": message,
                                "page_state": page_state,
                                "page_url": page.url,
                                "page_title": page.title() or "",
                                "tried_strategies": reasoning.next_directive(),
                                "reasoning_state": (
                                    reasoning.prompt_context(round_num)
                                    + "\n\n【多Agent共享黑板】\n"
                                    + blackboard.compact_context()
                                ),
                            })

                        blackboard.publish("executor", "action_proposed", action=action)
                        action, repair_notes = reasoning.repair_action(action)
                        for note in repair_notes:
                            blackboard.publish("coordinator", "action_repaired", note=note)
                            print(f"  [COORDINATOR] {note}")

                        if reasoning.repeated_on_same_observation(action):
                            message = "相同页面状态下禁止重复完全相同的动作"
                            synthetic = {
                                "success": False,
                                "error_type": "DUPLICATE_STRATEGY",
                                "message": message,
                            }
                            reasoning.record(round_num, action, synthetic, page.url, page.url)
                            blackboard.publish("coordinator", "action_blocked", reason=message)
                            fail_count += 1
                            continue

                        valid, validation_error = validate_action(action)
                        if not valid:
                            message = validation_error
                            blackboard.publish("coordinator", "action_blocked", reason=message)
                            fail_count += 1
                            continue

                        if action.get("action") == "finish":
                            declared = action.get("parameters", {}).get("result", "success")
                            if declared != "success":
                                message = declared
                                blackboard.publish("executor", "declared_failure", reason=declared)
                                break
                            verification = self.verifier.verify(
                                page, goal, criteria, page_state,
                                action=last_action, action_result=last_result,
                            )
                            last_verification = verification
                            blackboard.record_verification(verification.to_dict())
                            if verification.passed:
                                step_success = True
                                message = f"Verifier通过: {'；'.join(verification.evidence)}"
                                break
                            message = f"Verifier拒绝finish: {verification.reason}"
                            fail_count += 1
                            continue

                        step_actions.append(action)
                        url_before = page.url
                        try:
                            execution = executor.execute(action)
                        except Exception as exc:
                            execution = {
                                "success": False,
                                "error_type": "EXECUTION_EXCEPTION",
                                "message": str(exc),
                            }
                        self._clean_som_marks(page)

                        if execution.get("success") and action.get("action") == "click":
                            name = action.get("parameters", {}).get("name", "")
                            if any(k in name for k in ("登录", "登 录", "Login", "提交", "确认")):
                                try:
                                    page.wait_for_load_state("networkidle", timeout=5000)
                                except Exception:
                                    pass
                                page.wait_for_timeout(1000)

                        url_after = page.url
                        reasoning.record(round_num, action, execution, url_before, url_after)
                        last_action, last_result = action, execution
                        message = str(execution.get("message", ""))
                        blackboard.publish(
                            "executor", "action_executed",
                            action=action,
                            success=execution.get("success", False),
                            error_type=execution.get("error_type", ""),
                            message=message,
                            url_before=url_before,
                            url_after=url_after,
                        )

                        verification = self.verifier.verify(
                            page, goal, criteria, page_state,
                            action=action, action_result=execution,
                        )
                        last_verification = verification
                        blackboard.record_verification(verification.to_dict())
                        decision = self.coordinator.after_verification(verification)
                        if decision.route == "complete_step":
                            step_success = True
                            message = f"Verifier通过: {'；'.join(verification.evidence)}"
                            print(f"  [VERIFIER] {message}")
                            break
                        if not execution.get("success"):
                            fail_count += 1

                    css_selector = ""
                    if step_actions:
                        last_core = step_actions[-1]
                        if last_core.get("action") in ("click", "fill", "select_option"):
                            css_selector = executor.get_css_selector(
                                last_core.get("parameters", {}), last_core.get("action", "")
                            )
                    trace.append({
                        "goal": goal,
                        "action": step_actions[-1].get("action") if step_actions else "finish",
                        "parameters": step_actions[-1].get("parameters", {}) if step_actions else {},
                        "page_url": page.url,
                        "all_actions": step_actions,
                        "css_selector": css_selector,
                        "completion_evidence": last_verification.evidence if last_verification else [],
                        "agent_events": blackboard.events_for_step(step_num),
                    })
                    results.append({
                        "step": step_num,
                        "goal": goal,
                        "success": step_success,
                        "msg": message,
                        "verification": last_verification.to_dict() if last_verification else {},
                    })

                    if step_success:
                        blackboard.publish("coordinator", "step_completed", evidence=message)
                    else:
                        overall_success = False
                        blackboard.publish("coordinator", "step_failed", reason=message)
                        ts = datetime.now().strftime("%H%M%S")
                        try:
                            page.screenshot(path=os.path.join(
                                screenshot_dir, f"multi_step{step_num}_fail_{ts}.png"
                            ))
                        except Exception:
                            pass
                        break
            finally:
                browser.close()

        blackboard.status = "passed" if overall_success else "failed"
        blackboard.publish("coordinator", "task_finished", status=blackboard.status)

        case_id = None
        if overall_success:
            safe_module = re.sub(r'[\\/:*?"<>|]', '_', module or '通用')[:20]
            safe_name = re.sub(r'[\\/:*?"<>|]', '_', task_name)[:30]
            case_id = f"GEN_{safe_module}_{safe_name}"
            case_generator.generate_and_save(
                trace=trace,
                case_id=case_id,
                case_name=task_name,
                module=module,
                preconditions=preconditions,
                start_url=start_url,
            )

        return {
            "success": overall_success,
            "results": results,
            "trace": trace,
            "case_id": case_id,
            "collaboration": blackboard.summary(),
        }
