"""Stable viewport-aware select implementation.

This package supersedes the compatibility module of the same name.  Once an
option has been proven to belong to the active dropdown and intersect the
browser viewport, no extra scrolling is performed: animated Ant Design
portals can otherwise remain perpetually "unstable" to Playwright.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


_SOURCE = Path(__file__).resolve().parent.parent / "viewport_secure_playwright_exec.py"
_SPEC = importlib.util.spec_from_file_location(
    "executor._viewport_secure_playwright_exec_source", _SOURCE
)
_SOURCE_MODULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_SOURCE_MODULE)


class ViewportSecurePlaywrightExecutor(
    _SOURCE_MODULE.ViewportSecurePlaywrightExecutor
):
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
            self.page.wait_for_timeout(700)

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
                return _SOURCE_MODULE._fail(
                    "ELEMENT_NOT_FOUND",
                    f"No active dropdown option found: {target}",
                    self._get_error_context(locator_info),
                )

            option, clicked_label = candidates[0]
            # Bounding-box and active-portal checks above make forced click safe,
            # while avoiding Ant Design motion's stability wait.
            option.click(force=True, timeout=3000)
            self.page.wait_for_timeout(500)

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
                return _SOURCE_MODULE._fail(
                    "ASSERT_FAILED",
                    f"Dropdown selection was not observable after click: {clicked_label}",
                    self._get_error_context(locator_info),
                )
            return _SOURCE_MODULE._ok(
                f"Selected option confirmed: {clicked_label}",
                self._snapshot_page_change(),
            )
        except Exception as exc:
            return _SOURCE_MODULE._fail(
                "UNKNOWN_ERROR",
                f"Dropdown selection failed: {exc}",
                self._get_error_context(locator_info),
            )


__all__ = ["ViewportSecurePlaywrightExecutor"]
