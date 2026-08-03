"""Authenticate and inspect the customer page with production semantics."""

from __future__ import annotations

import argparse
from urllib.parse import urljoin

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from config.settings import settings
from scripts.diagnostics.login import authenticate
from web_agent.auth import AuthenticationPolicy


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Customer page diagnostic")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--wait-ms", type=int, default=2000)
    args = parser.parse_args(argv)

    policy = AuthenticationPolicy.from_environment()
    policy.validate()
    if not settings.LOGIN_URL:
        raise RuntimeError("LOGIN_URL is not configured")

    target = urljoin(settings.LOGIN_URL, "/customer")
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
            if not all(result.get("success") for result in results):
                print("probe_result=FAIL reason=login")
                return 1

            try:
                page.goto(target, wait_until="domcontentloaded", timeout=30000)
            except PlaywrightTimeoutError:
                if "/customer" not in page.url:
                    raise
            page.wait_for_timeout(max(args.wait_ms, 0))

            print(f"customer_url={page.url}")
            print(f"customer_title={page.title()}")
            passed = "/customer" in page.url
            print(f"probe_result={'PASS' if passed else 'FAIL'}")
            return 0 if passed else 1
        finally:
            browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
