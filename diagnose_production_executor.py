"""Exercise the production browser executor without the Agent loop."""

from __future__ import annotations

import os

from playwright.sync_api import sync_playwright

from config.settings import settings
from web_agent.auth import AuthenticationPolicy
from web_agent.keyboard_text_browser import KeyboardTextPolicyBrowserExecutor


def main() -> int:
    policy = AuthenticationPolicy(
        store_option_text=os.getenv("LOGIN_STORE_OPTION_TEXT", "").strip(),
        store_selection_mode="text",
    )
    policy.validate()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(no_viewport=True)
        page = context.new_page()
        try:
            page.goto(settings.LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
            executor = KeyboardTextPolicyBrowserExecutor(
                page, visual_sensor=object(), auth_policy=policy
            )
            results = [
                executor.execute({
                    "action": "fill",
                    "parameters": {"role": "textbox", "index": 0, "value": "ignored"},
                }),
                executor.execute({
                    "action": "fill",
                    "parameters": {"role": "textbox", "index": 1, "value": "ignored"},
                }),
                executor.execute({
                    "action": "select_option",
                    "parameters": {"role": "combobox", "option_text": ""},
                }),
                executor.execute({
                    "action": "click",
                    "parameters": {"role": "button", "name": "登 录"},
                }),
            ]
            print(f"success_flags={[item.get('success') for item in results]}")
            print(f"submit_error={results[-1].get('error_type', '')}")
            print(f"submit_page_change={results[-1].get('page_change', {})}")
            print(f"post_url={page.url}")
            return 0 if all(item.get("success") for item in results) else 1
        finally:
            browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
