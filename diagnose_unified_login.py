"""Instrument the unified login submit without exposing credential values."""

from __future__ import annotations

from executor.keyboard_verified_secure_playwright_exec import (
    KeyboardVerifiedSecurePlaywrightExecutor,
)


class AuditedLoginExecutor(KeyboardVerifiedSecurePlaywrightExecutor):
    def _submit_login(self) -> dict:
        username = self.page.locator("input[type='text']").first.input_value()
        password = self.page.locator("input[type='password']").first.input_value()
        selected = self.page.locator(".ant-select-selection-item:visible")
        labels = [text.strip() for text in selected.all_inner_texts() if text.strip()]
        print(
            "[PREFLIGHT] "
            f"username_present={bool(username)} "
            f"password_present={bool(password)} "
            f"selected_present={bool(labels)} "
            f"selected_labels={labels}"
        )
        result = super()._submit_login()
        if result.get("success"):
            try:
                self.page.wait_for_function(
                    "!window.location.href.includes('/login')", timeout=15000
                )
            except Exception:
                pass
            errors = self.page.locator(
                ".ant-message-notice-content:visible, "
                ".ant-form-item-explain-error:visible, "
                "[role='alert']:visible"
            ).all_inner_texts()
            print(f"[POST-SUBMIT] url={self.page.url} visible_errors={errors}")
        return result


def main() -> None:
    from runner.verified_unified_runner import VerifiedUnifiedSmartRunner

    source_globals = VerifiedUnifiedSmartRunner.run_case.__globals__
    original = source_globals["SecurePlaywrightExecutor"]
    source_globals["SecurePlaywrightExecutor"] = AuditedLoginExecutor
    try:
        from ai_test import run_excel
        run_excel("test_cases/explore_cases.xlsx", headless=False)
    finally:
        source_globals["SecurePlaywrightExecutor"] = original


if __name__ == "__main__":
    main()
