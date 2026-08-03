"""Deterministic regression using the canonical production browser executor."""

from __future__ import annotations

import argparse
from urllib.parse import urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from config.settings import settings
from runner.generic_runner import (
    AssertionExecutor,
    GenericTestRunner,
    StepExecutor,
    _precondition_mode,
    _split_steps,
    logger,
)
from web_agent.auth import AuthenticationPolicy
from web_agent.browser import PolicyAwareBrowserExecutor


class ProductionRegressionRunner(GenericTestRunner):
    def __init__(
        self,
        auth_policy: AuthenticationPolicy | None = None,
        executor_factory=PolicyAwareBrowserExecutor,
    ):
        super().__init__()
        self.auth_policy = auth_policy or AuthenticationPolicy.from_environment()
        self.auth_policy.validate()
        self.executor_factory = executor_factory

    def _handle_preconditions(self, page, preconditions: str, login_url: str):
        if _precondition_mode(preconditions) != "auto_login":
            return super()._handle_preconditions(page, preconditions, login_url)
        if not login_url:
            raise ValueError("Auto login requires LOGIN_URL")
        if not settings.LOGIN_USERNAME or not settings.LOGIN_PASSWORD:
            raise ValueError("Auto login credentials are not configured")

        page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1000)
        executor = self.executor_factory(
            page,
            visual_sensor=object(),
            auth_policy=self.auth_policy,
        )
        actions = (
            {
                "action": "fill",
                "parameters": {
                    "role": "textbox",
                    "index": 0,
                    "value": settings.LOGIN_USERNAME,
                },
            },
            {
                "action": "fill",
                "parameters": {
                    "role": "textbox",
                    "index": 1,
                    "value": settings.LOGIN_PASSWORD,
                },
            },
            {
                "action": "select_option",
                "parameters": {"role": "combobox", "option_text": ""},
            },
            {
                "action": "click",
                "parameters": {"role": "button", "name": "登录"},
            },
        )
        for action in actions:
            result = executor.execute(action)
            if not result.get("success"):
                raise RuntimeError(
                    f"Production login failed: {result.get('error_type', '')} "
                    f"{result.get('message', '')}"
                )

        try:
            notice = page.get_by_text("知道了").first
            if notice.is_visible(timeout=1000):
                notice.click()
        except Exception:
            pass

    @staticmethod
    def _last_navigation_target(case: dict) -> str:
        locators = _split_steps(str(case.get("元素定位器", "")))
        operations = _split_steps(str(case.get("操作类型", "")))
        raw_data = str(case.get("输入数据", "") or "")
        data_parts = [part.strip() for part in raw_data.split("|")] if raw_data else []
        while len(data_parts) < len(operations):
            data_parts.append("")

        data_index = 0
        target = ""
        for index, operation in enumerate(operations):
            locator = locators[index] if index < len(locators) else ""
            if operation in {"input", "select", "upload"}:
                data_index += 1
            elif operation == "nav":
                candidate = (
                    data_parts[data_index]
                    if data_index < len(data_parts)
                    else locator
                )
                data_index += 1
                target = candidate or locator
        return target

    @classmethod
    def _navigation_timeout_reached(cls, page, case: dict) -> bool:
        """Accept a goto timeout only when URL evidence proves arrival."""

        actual_url = str(page.url or "")
        assertion = str(case.get("断言类型", "") or "").strip()
        verify_point = str(case.get("验证点", "") or "").strip()
        if assertion == "url_contains" and verify_point:
            return verify_point in actual_url

        target = cls._last_navigation_target(case)
        if not target:
            return False
        actual_path = urlparse(actual_url).path.rstrip("/") or "/"
        target_path = urlparse(target).path.rstrip("/") or "/"
        return actual_path == target_path

    def _run_one(self, page, case: dict, login_url: str):
        """Run a case and tolerate only evidence-backed navigation timeouts."""

        preconditions = case.get("前置条件", "")
        locators = case.get("元素定位器", "")
        operations = case.get("操作类型", "")
        data = case.get("输入数据", "")
        assertion_type = case.get("断言类型", "")
        verify_point = case.get("验证点", "")
        expected = case.get("期望结果", "")

        self._handle_preconditions(page, preconditions, login_url)
        try:
            StepExecutor(page).execute(locators, operations, data)
        except PlaywrightTimeoutError:
            if not self._navigation_timeout_reached(page, case):
                raise
            logger.warning(
                "Navigation load event timed out, but target URL was reached: %s",
                page.url,
            )
            if settings.NAVIGATION_SETTLE_MS > 0:
                page.wait_for_timeout(settings.NAVIGATION_SETTLE_MS)

        locator_list = [locator for locator in _split_steps(locators) if locator]
        last_locator = locator_list[-1] if locator_list else ""
        page.wait_for_timeout(500)
        AssertionExecutor(page).assert_by_type(
            assertion_type,
            verify_point or expected,
            last_locator,
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--case", default="")
    parser.add_argument("--module", default="")
    args = parser.parse_args(argv)
    runner = ProductionRegressionRunner()
    runner.run_all(
        headless=args.headless,
        case_filter=args.case,
        module_filter=args.module,
    )
    return 0 if runner.results and all(
        item.get("result") == "pass" for item in runner.results
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
