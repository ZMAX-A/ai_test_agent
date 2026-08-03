"""Credential-safe select executor using verified keyboard semantics.

Ant Design highlights an initial option when its portal opens.  The target
application expects the next keyboard option rather than the highlighted
placeholder/store entry.  ArrowDown + Enter matches the known-good regression
flow, while visible-value readback removes the legacy false-positive.
"""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO

from core.credential_vault import CredentialVault
from executor.secure_playwright_exec import SecurePlaywrightExecutor


def _result(success: bool, message: str, error_type: str = "", **extra) -> dict:
    return {
        "success": success,
        "error_type": error_type,
        "message": message,
        "page_change": extra.get("page_change", {}) if success else {},
        "context": extra.get("context", {}),
    }


class KeyboardVerifiedSecurePlaywrightExecutor(SecurePlaywrightExecutor):
    def execute(self, action_info: dict) -> dict:
        if action_info.get("action") != "select_option":
            return super().execute(action_info)

        vault = getattr(self, "_credential_vault", CredentialVault())
        safe_params = vault.sanitize(dict(action_info.get("parameters", {})))
        print(f"[BOT] select_option | {safe_params}")
        with redirect_stdout(StringIO()):
            result = self._keyboard_select(action_info)
        safe_message = vault.sanitize_text(str(result.get("message", "")))
        error = str(result.get("error_type", "") or "-")
        print(
            f"[TOOL] select_option success={bool(result.get('success'))} "
            f"error={error} message={safe_message}"
        )
        return result

    def _keyboard_select(self, action_info: dict) -> dict:
        params = action_info.get("parameters", {})
        option_text = str(params.get("option_text", "") or "").strip()
        locator_info = (
            f"role={params.get('role', '?')}, name={params.get('name', '?')}, "
            f"index={params.get('index', '?')}"
        )
        try:
            combo = self._build_locator(params)
            combo.wait_for(state="visible", timeout=3000)
            combo.click(timeout=3000)
            self.page.wait_for_timeout(600)

            if option_text:
                option = self.page.locator(
                    ".ant-select-dropdown:not(.ant-select-dropdown-hidden) "
                    f".ant-select-item-option:has-text('{option_text}')"
                ).first
                option.wait_for(state="visible", timeout=3000)
                option.click(timeout=3000)
            else:
                self.page.keyboard.press("ArrowDown")
                self.page.keyboard.press("Enter")
            self.page.wait_for_timeout(600)

            selected = self.page.locator(
                ".ant-select-selection-item:visible, "
                "[role='option'][aria-selected='true']:visible"
            )
            selected_labels = []
            for index in range(selected.count()):
                try:
                    label = (selected.nth(index).inner_text(timeout=500) or "").strip()
                    if label:
                        selected_labels.append(label)
                except Exception:
                    continue
            if option_text:
                selected_labels = [
                    label for label in selected_labels if option_text in label
                ]
            if not selected_labels:
                return _result(
                    False,
                    "Dropdown keyboard action produced no visible selected value",
                    "ASSERT_FAILED",
                    context=self._get_error_context(locator_info),
                )
            return _result(
                True,
                f"Selected value confirmed: {selected_labels[0]}",
                page_change=self._snapshot_page_change(),
            )
        except Exception as exc:
            return _result(
                False,
                f"Verified keyboard selection failed: {exc}",
                "UNKNOWN_ERROR",
                context=self._get_error_context(locator_info),
            )


__all__ = ["KeyboardVerifiedSecurePlaywrightExecutor"]
