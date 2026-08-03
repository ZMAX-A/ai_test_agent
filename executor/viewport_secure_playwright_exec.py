"""Viewport-aware and credential-safe browser executor.

Only the select-option path differs from the shared executor.  Ant Design can
leave detached dropdown portals in the DOM; Playwright may report their items
as visible even though their bounding boxes are outside the browser viewport.
This implementation accepts candidates only from the active dropdown portal
and verifies the selected label after clicking.
"""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO

from core.credential_vault import CredentialVault
from executor.secure_playwright_exec import SecurePlaywrightExecutor


def _ok(message: str, page_change: dict | None = None) -> dict:
    return {
        "success": True,
        "error_type": "",
        "message": message,
        "page_change": page_change or {},
        "context": {},
    }


def _fail(error_type: str, message: str, context: dict | None = None) -> dict:
    return {
        "success": False,
        "error_type": error_type,
        "message": message,
        "page_change": {},
        "context": context or {},
    }


class ViewportSecurePlaywrightExecutor(SecurePlaywrightExecutor):
    ACTIVE_OPTION_SELECTOR = (
        ".ant-select-dropdown:not(.ant-select-dropdown-hidden) "
        ".ant-select-item-option:not(.ant-select-item-option-disabled), "
        "[role='listbox']:visible [role='option']:not([aria-disabled='true']), "
        ".el-select-dropdown:visible .el-select-dropdown__item:not(.is-disabled)"
    )

    def execute(self, action_info: dict) -> dict:
        if action_info.get("action") != "select_option":
            return super().execute(action_info)

        vault = getattr(self, "_credential_vault", CredentialVault())
        safe_params = vault.sanitize(dict(action_info.get("parameters", {})))
        print(f"[BOT] select_option | {safe_params}")
        with redirect_stdout(StringIO()):
            result = self._select_active_option(action_info)
        safe_message = vault.sanitize_text(str(result.get("message", "")))
        error = str(result.get("error_type", "") or "-")
        print(
            f"[TOOL] select_option success={bool(result.get('success'))} "
            f"error={error} message={safe_message}"
        )
        return result

    def _select_active_option(self, action_info: dict) -> dict:
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
            self.page.wait_for_timeout(400)

            viewport = self.page.evaluate(
                "() => ({width: window.innerWidth, height: window.innerHeight})"
            )
            options = self.page.locator(self.ACTIVE_OPTION_SELECTOR)
            candidates = []
            for index in range(options.count()):
                item = options.nth(index)
                try:
                    if not item.is_visible(timeout=300):
                        continue
                    box = item.bounding_box(timeout=500)
                    if not box or (
                        box["x"] + box["width"] <= 0
                        or box["y"] + box["height"] <= 0
                        or box["x"] >= viewport["width"]
                        or box["y"] >= viewport["height"]
                    ):
                        continue
                    label = (item.inner_text(timeout=1000) or "").strip()
                    if label and (not option_text or option_text in label):
                        candidates.append((item, label))
                except Exception:
                    continue

            if not candidates:
                target = option_text or "first visible enabled option"
                return _fail(
                    "ELEMENT_NOT_FOUND",
                    f"No active dropdown option found: {target}",
                    self._get_error_context(locator_info),
                )

            option, clicked_label = candidates[0]
            option.scroll_into_view_if_needed(timeout=1000)
            option.click(timeout=3000)
            self.page.wait_for_timeout(400)

            selected_labels = []
            selected = self.page.locator(
                ".ant-select-selection-item, "
                ".ant-select-item-option-selected, "
                "[role='option'][aria-selected='true']"
            )
            for index in range(selected.count()):
                try:
                    label = (selected.nth(index).inner_text(timeout=500) or "").strip()
                    if label:
                        selected_labels.append(label)
                except Exception:
                    continue

            if not any(
                clicked_label in label or label in clicked_label
                for label in selected_labels
            ):
                return _fail(
                    "ASSERT_FAILED",
                    f"Dropdown selection was not observable after click: {clicked_label}",
                    self._get_error_context(locator_info),
                )
            return _ok(
                f"Selected option confirmed: {clicked_label}",
                self._snapshot_page_change(),
            )
        except Exception as exc:
            return _fail(
                "UNKNOWN_ERROR",
                f"Dropdown selection failed: {exc}",
                self._get_error_context(locator_info),
            )


__all__ = ["ViewportSecurePlaywrightExecutor"]
