"""Single-source production runner with explicit dependency injection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
import re
import time
from typing import Any, Callable
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from agents.coordinator_agent import CoordinatorAgent
from agents.strict_verifier_agent import StrictVerifierAgent
from agents.unified_deliberative_executor import UnifiedDeliberativeExecutorAgent
from case import case_generator
from config.settings import settings
from core.agent_runtime import AgentRuntime
from core.authenticated_collaborative_reasoning import (
    AuthenticatedCollaborativeStepReasoningState,
)
from core.blackboard import TaskBlackboard
from core.credential_vault import CredentialVault
from core.task_world_model import TaskWorldModel
from core.tool_registry import create_web_tool_registry
from core.unified_context import bind_task_context, reset_task_context
from executor.action_validator import validate_action
from perception.aria_sensor import AriaSensor
from perception.visual_sensor import VisualSensor
from web_agent.auth import AuthenticationPolicy
from web_agent.browser import PolicyAwareBrowserExecutor


FORMAL_AGENTS = (
    "planner", "coordinator", "executor", "verifier", "critic", "replanner"
)
SENSITIVE_MODULES = frozenset({
    "顾客列表", "顾客详情", "影像阅览", "个人中心",
})
SENSITIVE_PATH_PREFIXES = (
    "/customer", "/image", "/profile", "/personal",
)
LOGIN_SETUP_KEYWORDS = (
    "打开登录", "登录页面", "用户名输入", "账号输入", "密码输入",
    "输入用户名", "输入账号", "输入密码", "点击登录",
)


def _executor_agent(registry):
    return UnifiedDeliberativeExecutorAgent(registry)


def _browser_executor(policy: AuthenticationPolicy):
    def create(page, visual_sensor):
        return PolicyAwareBrowserExecutor(
            page, visual_sensor=visual_sensor, auth_policy=policy
        )
    return create


@dataclass(frozen=True)
class RunnerDependencies:
    registry_factory: Callable[[], Any]
    coordinator_factory: Callable[[], Any]
    executor_agent_factory: Callable[[Any], Any]
    verifier_factory: Callable[[], Any]
    aria_sensor_factory: Callable[[], Any]
    visual_sensor_factory: Callable[[], Any]
    reasoning_factory: Callable[..., Any]
    browser_executor_factory: Callable[[Any, Any], Any]
    playwright_factory: Callable[[], Any]
    case_writer: Callable[..., Any]


def default_dependencies(
    auth_policy: AuthenticationPolicy | None = None,
) -> RunnerDependencies:
    policy = auth_policy or AuthenticationPolicy.from_environment()
    policy.validate()
    return RunnerDependencies(
        registry_factory=create_web_tool_registry,
        coordinator_factory=CoordinatorAgent,
        executor_agent_factory=_executor_agent,
        verifier_factory=StrictVerifierAgent,
        aria_sensor_factory=AriaSensor,
        visual_sensor_factory=VisualSensor,
        reasoning_factory=AuthenticatedCollaborativeStepReasoningState,
        browser_executor_factory=_browser_executor(policy),
        playwright_factory=sync_playwright,
        case_writer=case_generator.generate_and_save,
    )


def filter_login_setup_trace(
    trace: list[dict], preconditions: str, module: str = ""
) -> list[dict]:
    if str(module or "").strip() == "账号登录":
        return trace
    if "登录" not in str(preconditions or ""):
        return trace
    filtered = [
        entry for entry in trace
        if not any(
            keyword in str(entry.get("goal", ""))
            for keyword in LOGIN_SETUP_KEYWORDS
        )
    ]
    return filtered or trace


@dataclass
class _TaskSession:
    page: Any
    browser_executor: Any
    runtime: AgentRuntime
    world: TaskWorldModel
    blackboard: TaskBlackboard
    deadline: float
    experience_context: str = ""
    sensitive_context: bool = False


class ProductionRunner:
    """Production runner whose external collaborators are instance-owned."""

    def __init__(self, headless: bool = False,
                 dependencies: RunnerDependencies | None = None,
                 registry=None, vault: CredentialVault | None = None):
        self.headless = headless
        self.dependencies = dependencies or default_dependencies()
        self.registry = registry or self.dependencies.registry_factory()
        self.vault = vault or CredentialVault()
        self.coordinator = self.dependencies.coordinator_factory()
        self.executor_agent = self.dependencies.executor_agent_factory(self.registry)
        self.verifier = self.dependencies.verifier_factory()
        self.aria_sensor = self.dependencies.aria_sensor_factory()
        self.visual_sensor = self.dependencies.visual_sensor_factory()
        self.model_api_disabled = os.getenv(
            "WEB_AGENT_DISABLE_MODEL_API", ""
        ).strip().lower() in {"1", "true", "yes", "on"}

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
    def _is_sensitive_url(url: str) -> bool:
        path = urlparse(str(url or "")).path.lower()
        return any(
            path.startswith(prefix) for prefix in SENSITIVE_PATH_PREFIXES
        )

    @staticmethod
    def _clean_som_marks(page) -> None:
        """Remove only attributes injected by VisualSensor, never page nodes."""
        try:
            page.evaluate("""
                document.querySelectorAll('[data-som-index]').forEach(
                    element => element.removeAttribute('data-som-index')
                );
                delete window.__som_map;
            """)
        except Exception:
            pass

    def _perceive(self, session: _TaskSession, route: str, goal: str) -> str:
        context = {
            "page": session.page,
            "aria_sensor": self.aria_sensor,
            "visual_sensor": self.visual_sensor,
        }
        if route == "visual_sensor":
            state = session.runtime.invoke(
                "coordinator", "observe_visual", {"step_goal": goal}, context
            )
        else:
            state = session.runtime.invoke(
                "coordinator", "observe_aria", {}, context
            )
        return self.vault.sanitize_text(state)

    def _verify(self, session: _TaskSession, goal: str, criteria: str,
                page_state: str, action: dict | None,
                action_result: dict | None):
        verification = session.runtime.invoke(
            "verifier",
            "verify_page",
            {"goal": goal, "success_criteria": criteria},
            {
                "page": session.page,
                "verifier": self.verifier,
                "page_state": page_state,
                "action": action,
                "action_result": action_result,
            },
        )
        session.world.begin_goal(goal)
        session.world.record_verification(verification, action=action)
        session.blackboard.record_verification(verification.to_dict())
        return verification

    @staticmethod
    def _merge_page_change(
        execution: dict,
        before: str,
        after: str,
        safe_before: str | None = None,
        safe_after: str | None = None,
    ) -> None:
        change = execution.setdefault("page_change", {})
        changed = before != after
        change["url_changed"] = changed
        if changed:
            change.update({
                "url_changed": True,
                "old_url": before if safe_before is None else safe_before,
                "new_url": after if safe_after is None else safe_after,
            })
        else:
            change.pop("old_url", None)
            change.pop("new_url", None)

    def _run_step(self, session: _TaskSession, step_num: int,
                  step: dict) -> tuple[dict, dict]:
        raw_goal = str(step.get("goal", ""))
        raw_criteria = step.get("success_criteria", "") or step.get("assert", "")
        criteria_text = (
            json.dumps(raw_criteria, ensure_ascii=False)
            if isinstance(raw_criteria, dict) else str(raw_criteria)
        )
        goal = self.vault.sanitize_text(raw_goal)
        criteria = self.vault.sanitize_text(criteria_text)
        session.blackboard.start_step(step_num, goal, criteria)
        session.world.begin_goal(goal)
        print(f"\n[WEB-AGENT] 第{step_num}步: {goal}")

        reasoning = self.dependencies.reasoning_factory(
            goal=goal,
            success_criteria=criteria,
            max_rounds=settings.MAX_REASONING_ROUNDS,
        )
        actions: list[dict] = []
        last_action_resolved = None
        last_result = None
        last_verification = None
        fail_count = 0
        success = False
        message = "尚未执行"

        for round_num in range(1, settings.MAX_REASONING_ROUNDS + 1):
            decision = self.coordinator.before_decision(
                session.blackboard,
                session.deadline,
                session.blackboard.model_calls,
            )
            if decision.stop:
                message = decision.reason
                session.blackboard.publish(
                    "coordinator", "stopped", reason=message
                )
                break

            if (
                not session.sensitive_context
                and self._is_sensitive_url(session.page.url)
            ):
                session.sensitive_context = True
                session.browser_executor.suppress_screenshots = True
                session.blackboard.publish(
                    "coordinator", "sensitive_context_enabled",
                    reason="current URL entered a sensitive path",
                )
            perception = self.coordinator.choose_perception(reasoning, fail_count)
            route = perception.route
            if self.model_api_disabled and route == "visual_sensor":
                route = "aria_sensor"
                session.blackboard.publish(
                    "coordinator", "model_perception_blocked",
                    reason="WEB_AGENT_DISABLE_MODEL_API 已启用",
                )
            if session.sensitive_context and route == "visual_sensor":
                route = "aria_sensor"
                session.blackboard.publish(
                    "coordinator", "visual_blocked",
                    reason="敏感业务页面禁止视觉数据外发",
                )
            session.blackboard.publish(
                "coordinator", "route",
                route=route, reason=perception.reason,
            )
            try:
                if route == "visual_sensor":
                    session.blackboard.model_calls += 1
                page_state = self._perceive(session, route, goal)
            except Exception as exc:
                page_state = f"感知异常: {exc}"
            page_state = self.vault.sanitize_text(page_state)

            safe_url = self.vault.sanitize_text(session.page.url)
            title = self.vault.sanitize_text(session.page.title() or "")
            reasoning.observe(page_state, safe_url, title)
            session.blackboard.publish(
                "perception", "page_observed",
                sensor=route,
                url=safe_url,
                title=title,
                fingerprint=reasoning.observation_fingerprint,
            )

            verification = self._verify(
                session, goal, criteria, page_state,
                last_action_resolved, last_result,
            )
            last_verification = verification
            if self.coordinator.after_verification(verification).route == "complete_step":
                success = True
                message = "Verifier通过: " + "；".join(verification.evidence)
                print(f"  [VERIFIER] {message}")
                break

            action = reasoning.deterministic_action()
            if action and reasoning.repeated_on_same_observation(action):
                action = None
            if action:
                action = self.vault.tokenize_action(action)
                session.blackboard.publish(
                    "coordinator", "deterministic_action", action=action
                )
                print(f"  [COORDINATOR] 确定性动作: {action['action']}")
            else:
                if self.model_api_disabled:
                    message = "模型API已禁用且当前目标缺少确定性动作"
                    session.blackboard.publish(
                        "coordinator", "model_decision_blocked",
                        reason=message,
                    )
                    break
                if session.sensitive_context:
                    message = (
                        "敏感页面缺少确定性动作，"
                        "已阻止页面内容发送给模型"
                    )
                    session.blackboard.publish(
                        "coordinator", "model_context_blocked", reason=message,
                    )
                    break
                session.blackboard.model_calls += 1
                action = self.executor_agent.ask({
                    "step_goal": goal,
                    "last_result": message,
                    "page_state": page_state,
                    "page_url": safe_url,
                    "page_title": title,
                    "tried_strategies": reasoning.next_directive(),
                    "reasoning_state": (
                        reasoning.prompt_context(round_num)
                        + "\n\n【多Agent共享黑板】\n"
                        + session.blackboard.compact_context()
                        + (
                            "\n\n【已验证历史经验】\n"
                            "历史经验仅供参考，必须以当前页面和Verifier证据为准。\n"
                            + session.experience_context
                            if session.experience_context else ""
                        )
                    ),
                })
                action = self.vault.tokenize_action(action)

            session.blackboard.publish(
                "executor", "action_proposed", action=action
            )
            action, repair_notes = reasoning.repair_action(action)
            for note in repair_notes:
                session.blackboard.publish(
                    "coordinator", "action_repaired", note=note
                )

            if (
                session.sensitive_context
                and action.get("action") == "assert_visual"
            ):
                message = "敏感页面禁止视觉断言"
                session.blackboard.publish(
                    "coordinator", "action_blocked", reason=message,
                )
                fail_count += 1
                continue

            if reasoning.repeated_on_same_observation(action):
                message = "相同页面状态下禁止重复完全相同的动作"
                synthetic = {
                    "success": False,
                    "error_type": "DUPLICATE_STRATEGY",
                    "message": message,
                }
                reasoning.record(
                    round_num, action, synthetic,
                    session.page.url, session.page.url,
                )
                session.world.record_action(
                    action, synthetic, session.page.url, session.page.url
                )
                session.blackboard.publish(
                    "coordinator", "action_blocked", reason=message
                )
                fail_count += 1
                continue

            valid, validation_error = validate_action(action)
            if not valid:
                message = validation_error
                session.blackboard.publish(
                    "coordinator", "action_blocked", reason=message
                )
                fail_count += 1
                continue

            if action.get("action") == "finish":
                declared = action.get("parameters", {}).get("result", "success")
                if declared != "success":
                    message = declared
                    break
                verification = self._verify(
                    session, goal, criteria, page_state,
                    last_action_resolved, last_result,
                )
                last_verification = verification
                if verification.passed:
                    success = True
                    message = "Verifier通过: " + "；".join(verification.evidence)
                    break
                message = f"Verifier拒绝finish: {verification.reason}"
                fail_count += 1
                continue

            actions.append(action)
            resolved = self.vault.resolve_action(action)
            before = session.page.url
            try:
                execution = session.runtime.invoke_action(
                    "executor", resolved,
                    {"browser_executor": session.browser_executor},
                )
            except Exception as exc:
                execution = {
                    "success": False,
                    "error_type": "EXECUTION_EXCEPTION",
                    "message": str(exc),
                    "page_change": {},
                }
            self._clean_som_marks(session.page)

            if execution.get("success") and action.get("action") == "click":
                try:
                    session.page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
                session.page.wait_for_timeout(1000)

            after = session.page.url
            safe_before = self.vault.sanitize_text(before)
            safe_after = self.vault.sanitize_text(after)
            execution = self.vault.sanitize(execution)
            self._merge_page_change(
                execution, before, after, safe_before, safe_after
            )
            if (
                not session.sensitive_context
                and self._is_sensitive_url(after)
            ):
                session.sensitive_context = True
                session.browser_executor.suppress_screenshots = True
                session.blackboard.publish(
                    "coordinator", "sensitive_context_enabled",
                    reason="navigation entered a sensitive path",
                )
            reasoning.record(
                round_num, action, execution, safe_before, safe_after
            )
            session.world.record_action(
                action, execution, safe_before, safe_after
            )
            last_action_resolved = resolved
            last_result = execution
            message = str(execution.get("message", ""))
            session.blackboard.publish(
                "executor", "action_executed",
                action=action,
                success=execution.get("success", False),
                error_type=execution.get("error_type", ""),
                message=message,
                url_before=safe_before,
                url_after=safe_after,
            )

            verification = self._verify(
                session, goal, criteria, page_state, resolved, execution
            )
            last_verification = verification
            if self.coordinator.after_verification(verification).route == "complete_step":
                success = True
                message = "Verifier通过: " + "；".join(verification.evidence)
                print(f"  [VERIFIER] {message}")
                break
            if not execution.get("success"):
                fail_count += 1

        css_selector = ""
        if actions and actions[-1].get("action") in {
            "click", "fill", "select_option"
        }:
            css_selector = session.browser_executor.get_css_selector(
                actions[-1].get("parameters", {}), actions[-1].get("action", "")
            )
        trace = {
            "goal": goal,
            "action": actions[-1].get("action") if actions else "finish",
            "parameters": actions[-1].get("parameters", {}) if actions else {},
            "page_url": self.vault.sanitize_text(session.page.url),
            "all_actions": actions,
            "css_selector": css_selector,
            "completion_evidence": (
                last_verification.evidence if last_verification else []
            ),
            "agent_events": session.blackboard.events_for_step(step_num),
        }
        result = {
            "step": step_num,
            "goal": goal,
            "success": success,
            "msg": message,
            "verification": (
                last_verification.to_dict() if last_verification else {}
            ),
        }
        return result, trace

    def run_case(self, task_name: str, steps: list[dict], start_url: str,
                 module: str = "", preconditions: str = "",
                 experience_context: str = "",
                 sensitive_context: bool = False,
                 source_case_id: str = "") -> dict:
        safe_task = self.vault.sanitize_text(task_name)
        safe_preconditions = self.vault.sanitize_text(preconditions)
        safe_start_url = self.vault.sanitize_text(start_url)
        safe_experience = self.vault.sanitize_text(experience_context)[:8000]
        sensitive_context = bool(
            sensitive_context or module in SENSITIVE_MODULES
            or self._is_sensitive_url(start_url)
        )
        system = urlparse(start_url).netloc or "unknown"
        blackboard = TaskBlackboard(
            task_id=f"production:{system}:{safe_task}",
            task_name=safe_task,
            global_goal=safe_task,
        )
        world = TaskWorldModel(blackboard.task_id, safe_task)
        runtime = AgentRuntime(self.registry, blackboard)
        context_tokens = bind_task_context(runtime, world)
        blackboard.publish(
            "coordinator", "task_started",
            start_url=safe_start_url,
            step_count=len(steps),
            formal_agents=list(FORMAL_AGENTS),
            verified_experience_available=bool(safe_experience),
            sensitive_context=sensitive_context,
        )
        deadline = time.monotonic() + settings.EXPLORE_TASK_TIMEOUT_SECONDS
        results: list[dict] = []
        trace: list[dict] = []
        overall_success = bool(steps)

        screenshot_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "report", "screenshots"
        )
        os.makedirs(screenshot_dir, exist_ok=True)
        session: _TaskSession | None = None

        try:
            with self.dependencies.playwright_factory() as playwright:
                browser = playwright.chromium.launch(
                    headless=self.headless,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                browser_context = browser.new_context(no_viewport=True)
                page = browser_context.new_page()
                page.goto(
                    start_url,
                    wait_until="domcontentloaded",
                    timeout=settings.PAGE_TIMEOUT,
                )
                page.wait_for_timeout(settings.NAVIGATION_SETTLE_MS)
                browser_executor = self.dependencies.browser_executor_factory(
                    page, self.visual_sensor
                )
                browser_executor.suppress_screenshots = bool(
                    sensitive_context
                )
                session = _TaskSession(
                    page=page,
                    browser_executor=browser_executor,
                    runtime=runtime,
                    world=world,
                    blackboard=blackboard,
                    deadline=deadline,
                    experience_context=safe_experience,
                    sensitive_context=sensitive_context,
                )
                try:
                    for step_num, step in enumerate(steps, 1):
                        result, step_trace = self._run_step(
                            session, step_num, step
                        )
                        results.append(result)
                        trace.append(step_trace)
                        if result["success"]:
                            blackboard.publish(
                                "coordinator", "step_completed",
                                evidence=result["msg"],
                            )
                            continue

                        overall_success = False
                        blackboard.publish(
                            "coordinator", "step_failed", reason=result["msg"]
                        )
                        timestamp = datetime.now().strftime("%H%M%S")
                        if session.sensitive_context:
                            blackboard.publish(
                                "coordinator", "screenshot_skipped",
                                reason="敏感业务页面不保存失败截图",
                            )
                        else:
                            try:
                                page.screenshot(path=os.path.join(
                                    screenshot_dir,
                                    f"production_step{step_num}_fail_{timestamp}.png",
                                ))
                            except Exception:
                                pass
                        break
                finally:
                    browser.close()
        finally:
            reset_task_context(context_tokens)

        blackboard.status = "passed" if overall_success else "failed"
        blackboard.publish(
            "coordinator", "task_finished", status=blackboard.status
        )
        case_id = None
        final_sensitive_context = bool(
            sensitive_context
            or safe_start_url != start_url
            or (session is not None and session.sensitive_context)
        )
        if overall_success and not final_sensitive_context:
            safe_module = re.sub(r'[\\/:*?"<>|]', "_", module or "通用")[:20]
            safe_name = re.sub(r'[\\/:*?"<>|]', "_", safe_task)[:30]
            safe_source_id = re.sub(
                r'[\\/:*?"<>|]', "_", str(source_case_id or "")
            )[:80]
            case_id = safe_source_id or f"GEN_{safe_module}_{safe_name}"
            self.dependencies.case_writer(
                trace=filter_login_setup_trace(
                    trace, safe_preconditions, module=module
                ),
                case_id=case_id,
                case_name=safe_task,
                module=module,
                preconditions=safe_preconditions,
                start_url=safe_start_url,
                expected=(
                    steps[-1].get("success_criteria", "") if steps else ""
                ),
            )
        elif overall_success:
            blackboard.publish(
                "coordinator", "case_persistence_skipped",
                reason="sensitive context is not persisted as a generated case",
            )

        collaboration = blackboard.summary()
        collaboration["formal_agents"] = list(FORMAL_AGENTS)
        collaboration["world_model"] = world.compact_snapshot()
        collaboration["runner"] = "web_agent.ProductionRunner"
        return {
            "success": overall_success,
            "results": results,
            "trace": trace,
            "case_id": case_id,
            "collaboration": collaboration,
        }


__all__ = [
    "FORMAL_AGENTS",
    "SENSITIVE_MODULES",
    "ProductionRunner",
    "RunnerDependencies",
    "default_dependencies",
    "filter_login_setup_trace",
]
