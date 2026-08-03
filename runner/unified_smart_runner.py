"""无全局 Monkey Patch 的统一 Smart Agent Runner。"""

from __future__ import annotations

from datetime import datetime
import json
import os
import re
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from agents.coordinator_agent import CoordinatorAgent
from agents.strict_verifier_agent import StrictVerifierAgent
from agents.unified_deliberative_executor import UnifiedDeliberativeExecutorAgent
from case import case_generator
from config.settings import settings
from core.agent_runtime import AgentRuntime
from core.authenticated_collaborative_reasoning import AuthenticatedCollaborativeStepReasoningState
from core.blackboard import TaskBlackboard
from core.credential_vault import CredentialVault
from core.task_world_model import TaskWorldModel
from core.tool_registry import create_web_tool_registry
from core.unified_context import bind_task_context, reset_task_context
from executor.action_validator import validate_action
from executor.secure_playwright_exec import SecurePlaywrightExecutor
from perception.aria_sensor import AriaSensor
from perception.visual_sensor import VisualSensor


FORMAL_AGENTS = ("planner", "coordinator", "executor", "verifier", "critic", "replanner")
LOGIN_SETUP_KEYWORDS = (
    "打开登录", "登录页面", "用户名输入", "账号输入", "密码输入",
    "输入用户名", "输入账号", "输入密码", "点击登录",
)


def filter_login_setup_trace(trace: list[dict], preconditions: str) -> list[dict]:
    if "登录" not in (preconditions or ""):
        return trace
    filtered = [
        entry for entry in trace
        if not any(keyword in str(entry.get("goal", "")) for keyword in LOGIN_SETUP_KEYWORDS)
    ]
    return filtered or trace


class UnifiedSmartRunner:
    """所有依赖均由实例持有，可安全创建多个独立 Runner。"""

    def __init__(self, headless: bool = False, registry=None,
                 vault: CredentialVault | None = None):
        self.headless = headless
        self.registry = registry or create_web_tool_registry()
        self.vault = vault or CredentialVault()
        self.coordinator = CoordinatorAgent()
        self.executor_agent = UnifiedDeliberativeExecutorAgent(self.registry)
        self.verifier = StrictVerifierAgent()
        self.aria_sensor = AriaSensor()
        self.visual_sensor = VisualSensor()

    def capability_manifest(self) -> dict[str, list[str]]:
        return {
            "planner": [],
            "coordinator": self.registry.names_for("coordinator"),
            "executor": self.registry.names_for("executor"),
            "verifier": self.registry.names_for("verifier"),
            "critic": [],
            "replanner": [],
        }

    @staticmethod
    def _clean_som_marks(page) -> None:
        try:
            page.evaluate("""
                document.querySelectorAll('div[style*="pointerEvents:none"]').forEach(d=>d.remove());
                delete window.__som_map;
            """)
        except Exception:
            pass

    def _perceive(self, runtime: AgentRuntime, route: str, page, goal: str) -> str:
        context = {
            "page": page,
            "aria_sensor": self.aria_sensor,
            "visual_sensor": self.visual_sensor,
        }
        if route == "visual_sensor":
            state = runtime.invoke(
                "coordinator", "observe_visual", {"step_goal": goal}, context
            )
        else:
            state = runtime.invoke("coordinator", "observe_aria", {}, context)
        return self.vault.sanitize_text(state)

    def _verify(self, runtime: AgentRuntime, world: TaskWorldModel, blackboard,
                page, goal: str, criteria: str, page_state: str,
                action: dict | None, action_result: dict | None):
        verification = runtime.invoke(
            "verifier",
            "verify_page",
            {"goal": goal, "success_criteria": criteria},
            {
                "page": page,
                "verifier": self.verifier,
                "page_state": page_state,
                "action": action,
                "action_result": action_result,
            },
        )
        world.begin_goal(goal)
        world.record_verification(verification, action=action)
        blackboard.record_verification(verification.to_dict())
        return verification

    def run_case(self, task_name: str, steps: list[dict], start_url: str,
                 module: str = "", preconditions: str = "") -> dict:
        safe_task_name = self.vault.sanitize_text(task_name)
        safe_preconditions = self.vault.sanitize_text(preconditions)
        system = urlparse(start_url).netloc or "unknown"
        deadline = time.monotonic() + settings.EXPLORE_TASK_TIMEOUT_SECONDS
        blackboard = TaskBlackboard(
            task_id=f"unified:{system}:{safe_task_name}",
            task_name=safe_task_name,
            global_goal=safe_task_name,
        )
        world = TaskWorldModel(blackboard.task_id, safe_task_name)
        runtime = AgentRuntime(self.registry, blackboard)
        context_tokens = bind_task_context(runtime, world)
        blackboard.publish(
            "coordinator", "task_started", start_url=start_url,
            step_count=len(steps), formal_agents=list(FORMAL_AGENTS),
        )
        trace: list[dict] = []
        results: list[dict] = []
        overall_success = bool(steps)

        screenshot_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "report", "screenshots"
        )
        os.makedirs(screenshot_dir, exist_ok=True)

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=self.headless,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                browser_context = browser.new_context(no_viewport=True)
                page = browser_context.new_page()
                page.goto(start_url, timeout=settings.PAGE_TIMEOUT)
                page.wait_for_timeout(settings.NAVIGATION_SETTLE_MS)
                browser_executor = SecurePlaywrightExecutor(
                    page, visual_sensor=self.visual_sensor
                )

                try:
                    for step_num, step in enumerate(steps, 1):
                        raw_goal = str(step.get("goal", ""))
                        raw_criteria = step.get("success_criteria", "") or step.get("assert", "")
                        criteria_text = (
                            json.dumps(raw_criteria, ensure_ascii=False)
                            if isinstance(raw_criteria, dict) else str(raw_criteria)
                        )
                        goal = self.vault.sanitize_text(raw_goal)
                        criteria = self.vault.sanitize_text(criteria_text)
                        blackboard.start_step(step_num, goal, criteria)
                        world.begin_goal(goal)
                        print(f"\n[UNIFIED-SMART] 第{step_num}步: {goal}")

                        reasoning = AuthenticatedCollaborativeStepReasoningState(
                            goal=goal,
                            success_criteria=criteria,
                            max_rounds=settings.MAX_REASONING_ROUNDS,
                        )
                        step_actions: list[dict] = []
                        last_action_safe = None
                        last_action_resolved = None
                        last_result = None
                        last_verification = None
                        fail_count = 0
                        step_success = False
                        message = "未执行"

                        for round_num in range(1, settings.MAX_REASONING_ROUNDS + 1):
                            decision = self.coordinator.before_decision(
                                blackboard, deadline, blackboard.model_calls
                            )
                            if decision.stop:
                                message = decision.reason
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
                                page_state = self._perceive(runtime, perception.route, page, goal)
                            except Exception as exc:
                                page_state = f"感知异常: {exc}"

                            title = self.vault.sanitize_text(page.title() or "")
                            reasoning.observe(page_state, page.url, title)
                            blackboard.publish(
                                "perception", "page_observed",
                                sensor=perception.route, url=page.url, title=title,
                                fingerprint=reasoning.observation_fingerprint,
                            )

                            verification = self._verify(
                                runtime, world, blackboard, page, goal, criteria,
                                page_state, last_action_resolved, last_result,
                            )
                            last_verification = verification
                            if self.coordinator.after_verification(verification).route == "complete_step":
                                step_success = True
                                message = f"Verifier通过: {'；'.join(verification.evidence)}"
                                print(f"  [VERIFIER] {message}")
                                break

                            action = reasoning.deterministic_action()
                            if action and reasoning.repeated_on_same_observation(action):
                                action = None
                            if action:
                                action = self.vault.tokenize_action(action)
                                blackboard.publish(
                                    "coordinator", "deterministic_action", action=action
                                )
                                print(f"  [COORDINATOR] 确定性动作: {action['action']}")
                            else:
                                blackboard.model_calls += 1
                                action = self.executor_agent.ask({
                                    "step_goal": goal,
                                    "last_result": message,
                                    "page_state": page_state,
                                    "page_url": page.url,
                                    "page_title": title,
                                    "tried_strategies": reasoning.next_directive(),
                                    "reasoning_state": (
                                        reasoning.prompt_context(round_num)
                                        + "\n\n【多Agent共享黑板】\n"
                                        + blackboard.compact_context()
                                    ),
                                })
                                action = self.vault.tokenize_action(action)

                            blackboard.publish("executor", "action_proposed", action=action)
                            action, repair_notes = reasoning.repair_action(action)
                            for note in repair_notes:
                                blackboard.publish("coordinator", "action_repaired", note=note)

                            if reasoning.repeated_on_same_observation(action):
                                message = "相同页面状态下禁止重复完全相同的动作"
                                synthetic = {
                                    "success": False,
                                    "error_type": "DUPLICATE_STRATEGY",
                                    "message": message,
                                }
                                reasoning.record(round_num, action, synthetic, page.url, page.url)
                                world.record_action(action, synthetic, page.url, page.url)
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
                                    break
                                verification = self._verify(
                                    runtime, world, blackboard, page, goal, criteria,
                                    page_state, last_action_resolved, last_result,
                                )
                                last_verification = verification
                                if verification.passed:
                                    step_success = True
                                    message = f"Verifier通过: {'；'.join(verification.evidence)}"
                                    break
                                message = f"Verifier拒绝finish: {verification.reason}"
                                fail_count += 1
                                continue

                            step_actions.append(action)
                            resolved_action = self.vault.resolve_action(action)
                            url_before = page.url
                            try:
                                execution = runtime.invoke_action(
                                    "executor", resolved_action,
                                    {"browser_executor": browser_executor},
                                )
                            except Exception as exc:
                                execution = {
                                    "success": False,
                                    "error_type": "EXECUTION_EXCEPTION",
                                    "message": str(exc),
                                }
                            self._clean_som_marks(page)

                            if execution.get("success") and action.get("action") == "click":
                                try:
                                    page.wait_for_load_state("networkidle", timeout=5000)
                                except Exception:
                                    pass
                                page.wait_for_timeout(1000)

                            url_after = page.url
                            reasoning.record(round_num, action, execution, url_before, url_after)
                            world.record_action(action, execution, url_before, url_after)
                            last_action_safe = action
                            last_action_resolved = resolved_action
                            last_result = execution
                            message = str(execution.get("message", ""))
                            blackboard.publish(
                                "executor", "action_executed", action=action,
                                success=execution.get("success", False),
                                error_type=execution.get("error_type", ""),
                                message=message, url_before=url_before, url_after=url_after,
                            )

                            verification = self._verify(
                                runtime, world, blackboard, page, goal, criteria,
                                page_state, resolved_action, execution,
                            )
                            last_verification = verification
                            followup = self.coordinator.after_verification(verification)
                            if followup.route == "complete_step":
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
                                css_selector = browser_executor.get_css_selector(
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
                            "step": step_num, "goal": goal,
                            "success": step_success, "msg": message,
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
                                    screenshot_dir, f"unified_step{step_num}_fail_{ts}.png"
                                ))
                            except Exception:
                                pass
                            break
                finally:
                    browser.close()
        finally:
            reset_task_context(context_tokens)

        blackboard.status = "passed" if overall_success else "failed"
        blackboard.publish("coordinator", "task_finished", status=blackboard.status)
        case_id = None
        if overall_success:
            safe_module = re.sub(r'[\\/:*?"<>|]', '_', module or '通用')[:20]
            safe_name = re.sub(r'[\\/:*?"<>|]', '_', safe_task_name)[:30]
            case_id = f"GEN_{safe_module}_{safe_name}"
            case_generator.generate_and_save(
                trace=filter_login_setup_trace(trace, safe_preconditions),
                case_id=case_id,
                case_name=safe_task_name,
                module=module,
                preconditions=safe_preconditions,
                start_url=start_url,
            )

        collaboration = blackboard.summary()
        collaboration["formal_agents"] = list(FORMAL_AGENTS)
        collaboration["world_model"] = world.compact_snapshot()
        return {
            "success": overall_success,
            "results": results,
            "trace": trace,
            "case_id": case_id,
            "collaboration": collaboration,
        }
