"""Canonical browser executor used by every production workflow.

Authentication is deterministic and fail-closed. Model-provided credential
values are ignored, secrets are resolved only at the execution boundary, and
login success requires an observable navigation away from the login page.
"""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from typing import Callable

from config.settings import settings
from core.credential_vault import CredentialVault
from executor.login_grounded_secure_exec import LoginGroundedSecureExecutor
from web_agent.auth import AuthenticationPolicy


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


class PolicyAwareBrowserExecutor(LoginGroundedSecureExecutor):
    """Execute browser actions with the production authentication policy."""

    def __init__(
        self,
        page,
        visual_sensor=None,
        auth_policy: AuthenticationPolicy | None = None,
    ):
        super().__init__(page, visual_sensor=visual_sensor)
        self.auth_policy = auth_policy or AuthenticationPolicy.from_environment()
        self.auth_policy.validate()
        self._vault = CredentialVault()

    def execute(self, action_info: dict) -> dict:
        if not self.auth_policy.is_login_url(str(self.page.url)):
            return super().execute(action_info)

        action = str(action_info.get("action", ""))
        params = action_info.get("parameters", {})
        if action == "fill":
            semantic = self._login_field_semantic(params)
            if semantic == "username":
                return self._fill_login_field(
                    semantic,
                    self.auth_policy.username_selector,
                    settings.LOGIN_USERNAME,
                )
            if semantic == "password":
                return self._fill_login_field(
                    semantic,
                    self.auth_policy.password_selector,
                    settings.LOGIN_PASSWORD,
                )
            return self._logged(
                "fill",
                {"semantic": "unresolved_login_field", "value": "<redacted>"},
                lambda: _fail(
                    "AMBIGUOUS_LOGIN_FIELD",
                    "Login fill blocked because field meaning is ambiguous",
                ),
            )
        if action == "select_option":
            return self._select_store(params)
        if action == "click" and self._is_login_submit(params):
            return self._submit_and_wait()
        return super().execute(action_info)

    def _login_field_semantic(self, params: dict) -> str:
        index = params.get("index")
        if index in (0, "0"):
            return "username"
        if index in (1, "1"):
            return "password"

        value = str(params.get("value", ""))
        if value and value == settings.LOGIN_USERNAME:
            return "username"
        if value and value == settings.LOGIN_PASSWORD:
            return "password"

        if params.get("som_index") is not None:
            try:
                locator = self.page.locator(
                    f'[data-som-index="{int(params["som_index"])}"]'
                )
                field_type = str(locator.get_attribute("type") or "").lower()
                field_id = str(locator.get_attribute("id") or "").lower()
                name = str(locator.get_attribute("name") or "").lower()
                identity = " ".join((field_id, name))
                if field_type == "password" or "password" in identity:
                    return "password"
                if field_type in {"text", "email"} and any(
                    token in identity for token in ("user", "account", "login")
                ):
                    return "username"
            except Exception:
                return ""
        return ""

    def _logged(
        self,
        action: str,
        safe_params: dict,
        operation: Callable[[], dict],
    ) -> dict:
        print(f"[BOT] {action} | {safe_params}")
        with redirect_stdout(StringIO()):
            result = operation()
        message = self._vault.sanitize_text(str(result.get("message", "")))
        error = str(result.get("error_type", "") or "-")
        print(
            f"[TOOL] {action} success={bool(result.get('success'))} "
            f"error={error} message={message}"
        )
        return result

    def _fill_login_field(self, semantic: str, selector: str, value: str) -> dict:
        def operation() -> dict:
            if not value:
                return _fail(
                    "CREDENTIAL_NOT_CONFIGURED",
                    f"Login {semantic} credential is not configured",
                )
            try:
                target = self.page.locator(selector).first
                target.wait_for(state="visible", timeout=3000)
                target.fill(value, timeout=3000)
                if target.input_value(timeout=1000) != value:
                    return _fail(
                        "ASSERT_FAILED",
                        f"Login {semantic} field readback did not match",
                    )
                return _ok(f"Login {semantic} field filled and confirmed")
            except Exception as exc:
                return _fail(
                    "UNKNOWN_ERROR",
                    f"Login {semantic} fill failed: {exc}",
                )

        return self._logged(
            "fill",
            {"semantic": f"login_{semantic}", "value": "<redacted>"},
            operation,
        )

    def _select_store(self, params: dict) -> dict:
        requested = str(params.get("option_text", "") or "").strip()
        option_text = requested or self.auth_policy.store_option_text
        if option_text:
            return self._select_store_by_keyboard_text(option_text)
        return self._select_next_store()

    def _store_combobox(self):
        try:
            return self.page.get_by_role("combobox")
        except Exception:
            return self.page.locator(self.auth_policy.store_selector).first

    def _select_store_by_keyboard_text(self, option_text: str) -> dict:
        def operation() -> dict:
            try:
                combo = self._store_combobox()
                combo.wait_for(state="visible", timeout=3000)
                combo.click(timeout=3000)
                self.page.wait_for_timeout(600)

                options = self.page.locator(
                    ".ant-select-dropdown:not(.ant-select-dropdown-hidden) "
                    ".ant-select-item-option"
                )
                rounds = max(options.count() + 2, 4)
                matched = False
                for _ in range(rounds):
                    active = self.page.locator(
                        ".ant-select-dropdown:not(.ant-select-dropdown-hidden) "
                        ".ant-select-item-option-active"
                    ).first
                    try:
                        active_text = (active.inner_text(timeout=500) or "").strip()
                    except Exception:
                        active_text = ""
                    if option_text in active_text:
                        self.page.keyboard.press("Enter")
                        matched = True
                        break
                    self.page.keyboard.press("ArrowDown")
                    self.page.wait_for_timeout(150)

                if not matched:
                    self.page.keyboard.press("Escape")
                    return _fail(
                        "ELEMENT_NOT_FOUND",
                        f"No keyboard option matched: {option_text}",
                    )
                self.page.wait_for_timeout(600)
                labels = [
                    label
                    for label in self._visible_selected_labels()
                    if option_text in label
                ]
                if not labels:
                    return _fail(
                        "ASSERT_FAILED",
                        "Keyboard selection had no matching visible value",
                    )
                return _ok(f"Keyboard-selected store confirmed: {labels[0]}")
            except Exception as exc:
                return _fail(
                    "UNKNOWN_ERROR",
                    f"Keyboard text selection failed: {exc}",
                )

        return self._logged(
            "select_option",
            {
                "semantic": "login_store",
                "mode": "keyboard_text",
                "option_text": option_text,
            },
            operation,
        )

    def _select_next_store(self) -> dict:
        def operation() -> dict:
            try:
                combo = self._store_combobox()
                combo.wait_for(state="visible", timeout=3000)
                combo.click(timeout=3000)
                self.page.wait_for_timeout(600)
                self.page.keyboard.press("ArrowDown")
                self.page.wait_for_timeout(200)
                self.page.keyboard.press("Enter")
                self.page.wait_for_timeout(600)
                labels = self._visible_selected_labels()
                if not labels:
                    return _fail(
                        "ASSERT_FAILED",
                        "Store selection produced no visible value",
                    )
                return _ok(f"Selected store confirmed: {labels[0]}")
            except Exception as exc:
                return _fail("UNKNOWN_ERROR", f"Store selection failed: {exc}")

        return self._logged(
            "select_option",
            {
                "semantic": "login_store",
                "mode": "keyboard_next",
                "option_text": "",
            },
            operation,
        )

    def _visible_selected_labels(self) -> list[str]:
        selectors = (
            self.auth_policy.selected_store_selector,
            ".ant-select-selection-item:visible",
            "[role='option'][aria-selected='true']:visible",
        )
        labels: list[str] = []
        for selector in dict.fromkeys(selectors):
            try:
                selected = self.page.locator(selector)
                for index in range(selected.count()):
                    text = (selected.nth(index).inner_text(timeout=500) or "").strip()
                    if text and text not in labels:
                        labels.append(text)
            except Exception:
                try:
                    labels.extend(
                        text.strip()
                        for text in self.page.locator(selector).all_inner_texts()
                        if text.strip() and text.strip() not in labels
                    )
                except Exception:
                    continue
        return labels

    def _submit_and_wait(self) -> dict:
        def operation() -> dict:
            before = str(self.page.url)
            try:
                # Ant Design select portals can cover the submit button.
                self.page.keyboard.press("Escape")
                self.page.wait_for_timeout(300)

                username = self.page.locator(
                    self.auth_policy.username_selector
                ).first.input_value()
                password = self.page.locator(
                    self.auth_policy.password_selector
                ).first.input_value()
                stores = self._visible_selected_labels()
                if not username or not password or not stores:
                    return _fail(
                        "PRECONDITION_FAILED",
                        "Login submit blocked: required fields are incomplete",
                    )

                submit = self.page.locator(self.auth_policy.submit_selector).first
                submit.wait_for(state="visible", timeout=3000)
                submit.click(timeout=5000)
                try:
                    self.page.wait_for_function(
                        "path => !window.location.pathname.includes(path)",
                        arg=self.auth_policy.login_path,
                        timeout=self.auth_policy.navigation_timeout_ms,
                    )
                except Exception:
                    pass

                after = str(self.page.url)
                if after == before or self.auth_policy.is_login_url(after):
                    errors = self.page.locator(
                        ".ant-message-notice-content:visible, "
                        ".ant-form-item-explain-error:visible, "
                        "[role='alert']:visible"
                    ).all_inner_texts()
                    safe_errors = [
                        self._vault.sanitize_text(text.strip())
                        for text in errors
                        if text.strip()
                    ]
                    suffix = f": {' | '.join(safe_errors)}" if safe_errors else ""
                    return _fail(
                        "POSTCONDITION_FAILED",
                        "Login submit did not leave the login page" + suffix,
                    )

                self.page.wait_for_timeout(self.auth_policy.settle_ms)
                return _ok(
                    "Login navigation confirmed",
                    {
                        "url_changed": True,
                        "old_url": before,
                        "new_url": after,
                    },
                )
            except Exception as exc:
                return _fail("UNKNOWN_ERROR", f"Login submit failed: {exc}")

        return self._logged("click", {"semantic": "login_submit"}, operation)


__all__ = ["PolicyAwareBrowserExecutor"]
