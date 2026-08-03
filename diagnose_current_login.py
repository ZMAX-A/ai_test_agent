"""No-model login diagnosis for the current site without credential output."""

from __future__ import annotations

import os

from playwright.sync_api import sync_playwright

from config.settings import settings


def main() -> int:
    target_store = os.getenv("LOGIN_STORE_OPTION_TEXT", "").strip()
    if not target_store:
        raise RuntimeError("LOGIN_STORE_OPTION_TEXT is required")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(no_viewport=True)
        page = context.new_page()
        network_events = []

        def record_response(response):
            lowered = response.url.lower()
            if any(token in lowered for token in ("login", "auth", "token")):
                network_events.append((response.status, response.url))

        page.on("response", record_response)
        try:
            page.goto(settings.LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
            page.locator("input[type='text']").first.fill(settings.LOGIN_USERNAME)
            page.locator("input[type='password']").first.fill(settings.LOGIN_PASSWORD)

            combo = page.get_by_role("combobox")
            combo.click()
            page.wait_for_timeout(600)
            options = page.locator(
                ".ant-select-dropdown:not(.ant-select-dropdown-hidden) "
                ".ant-select-item-option"
            )
            option_labels = [text.strip() for text in options.all_inner_texts() if text.strip()]
            print(f"option_labels={option_labels}")

            matched = False
            for _ in range(max(options.count() + 2, 4)):
                active = page.locator(
                    ".ant-select-dropdown:not(.ant-select-dropdown-hidden) "
                    ".ant-select-item-option-active"
                ).first
                try:
                    active_text = (active.inner_text(timeout=500) or "").strip()
                except Exception:
                    active_text = ""
                if target_store in active_text:
                    page.keyboard.press("Enter")
                    matched = True
                    break
                page.keyboard.press("ArrowDown")
                page.wait_for_timeout(150)
            page.wait_for_timeout(600)

            selected = page.locator(".ant-select-selection-item:visible").all_inner_texts()
            username_present = bool(page.locator("input[type='text']").first.input_value())
            password_present = bool(page.locator("input[type='password']").first.input_value())
            print(
                f"matched={matched} selected={selected} "
                f"username_present={username_present} password_present={password_present}"
            )
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)

            submit = page.locator("button[type='submit']").first
            try:
                submit.click(timeout=5000)
                print("submit_click=normal")
            except Exception:
                submit.click(force=True, timeout=3000)
                print("submit_click=force")
            try:
                page.wait_for_function(
                    "!window.location.pathname.includes('/login')", timeout=20000
                )
            except Exception:
                pass
            page.wait_for_timeout(1000)
            errors = page.locator(
                ".ant-message-notice-content:visible, "
                ".ant-form-item-explain-error:visible, "
                "[role='alert']:visible"
            ).all_inner_texts()
            print(f"post_url={page.url}")
            print(f"visible_errors={errors}")
            print(f"auth_responses={network_events}")
            passed = "/login" not in page.url
            print(f"probe_result={'PASS' if passed else 'FAIL'}")
            return 0 if passed else 1
        finally:
            browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
