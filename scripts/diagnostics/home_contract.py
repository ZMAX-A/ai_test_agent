"""Read-only probe for homepage labels used by curriculum contracts."""

from __future__ import annotations

import argparse
import json

from playwright.sync_api import sync_playwright

from config.settings import settings
from scripts.diagnostics.login import authenticate
from web_agent.auth import AuthenticationPolicy


DEFAULT_LABELS = ("顾客档案", "美际学院", "案例管理", "案例库", "设置")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Probe homepage contract labels")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--label", action="append", default=[])
    args = parser.parse_args(argv)
    labels = tuple(args.label) or DEFAULT_LABELS
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
            login_results = authenticate(page, policy)
            if not all(item.get("success") for item in login_results):
                print("login=FAIL")
                return 2
            page.wait_for_timeout(settings.NAVIGATION_SETTLE_MS)
            body = page.locator("body").inner_text(timeout=5000) or ""
            matches = {label: label in body for label in labels}
            print(json.dumps(matches, ensure_ascii=False, sort_keys=True))
            return 0 if all(matches.values()) else 1
        finally:
            browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
