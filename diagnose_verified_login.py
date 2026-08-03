"""Real-browser login probe with no credential output.

This intentionally bypasses the LLM loop so browser interaction semantics can
be compared with the deterministic regression runner.
"""

from __future__ import annotations

import argparse

from playwright.sync_api import sync_playwright

from config.settings import settings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=args.headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(no_viewport=True)
        page = context.new_page()
        try:
            page.goto(settings.LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
            page.locator("input[type='text']").first.fill(settings.LOGIN_USERNAME)
            page.locator("input[type='password']").first.fill(settings.LOGIN_PASSWORD)

            combo = page.locator(".ant-select-selector").first
            combo.click()
            page.wait_for_timeout(600)
            page.keyboard.press("ArrowDown")
            page.keyboard.press("Enter")
            page.wait_for_timeout(600)

            selected = page.locator(".ant-select-selection-item:visible").first
            selected_label = (
                (selected.inner_text(timeout=2000) or "").strip()
                if selected.count() else ""
            )
            print(f"selected_observable={bool(selected_label)} label={selected_label}")
            if not selected_label:
                print("probe_result=FAIL reason=selection_not_observable")
                return 1

            page.locator("button[type='submit']").first.click(timeout=5000)
            try:
                page.wait_for_function(
                    "!window.location.href.includes('/login')", timeout=15000
                )
            except Exception:
                pass
            print(f"post_login_url={page.url}")
            if "/login" in page.url:
                visible_errors = page.locator(
                    ".ant-message-notice-content:visible, "
                    ".ant-form-item-explain-error:visible, "
                    "[role='alert']:visible"
                ).all_inner_texts()
                print(f"visible_errors={visible_errors}")
                print("probe_result=FAIL reason=login_did_not_navigate")
                return 1

            page.goto(
                settings.LOGIN_URL.rsplit("/login", 1)[0] + "/customer",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            page.wait_for_timeout(2000)
            print(f"customer_url={page.url}")
            passed = "/customer" in page.url
            print(f"probe_result={'PASS' if passed else 'FAIL'}")
            return 0 if passed else 1
        finally:
            browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
