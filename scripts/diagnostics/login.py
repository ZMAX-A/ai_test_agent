"""Verify the configured login flow without invoking an LLM."""

from __future__ import annotations

import argparse

from playwright.sync_api import sync_playwright

from config.settings import settings
from web_agent.auth import AuthenticationPolicy
from web_agent.browser import PolicyAwareBrowserExecutor


def authenticate(page, policy: AuthenticationPolicy) -> list[dict]:
    """Run the same deterministic login actions used by production."""

    executor = PolicyAwareBrowserExecutor(
        page,
        visual_sensor=object(),
        auth_policy=policy,
    )
    actions = (
        {"action": "fill", "parameters": {"role": "textbox", "index": 0}},
        {"action": "fill", "parameters": {"role": "textbox", "index": 1}},
        {
            "action": "select_option",
            "parameters": {"role": "combobox", "option_text": ""},
        },
        {
            "action": "click",
            "parameters": {"role": "button", "name": "登录"},
        },
    )
    return [executor.execute(action) for action in actions]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Production login diagnostic")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args(argv)

    policy = AuthenticationPolicy.from_environment()
    policy.validate()
    if not settings.LOGIN_URL:
        raise RuntimeError("LOGIN_URL is not configured")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=args.headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(no_viewport=True)
        page = context.new_page()
        try:
            page.goto(
                settings.LOGIN_URL,
                wait_until="domcontentloaded",
                timeout=settings.PAGE_TIMEOUT,
            )
            results = authenticate(page, policy)
            success = all(result.get("success") for result in results)
            print(f"login_actions={[result.get('success') for result in results]}")
            print(f"post_url={page.url}")
            print(f"probe_result={'PASS' if success else 'FAIL'}")
            return 0 if success else 1
        finally:
            browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
