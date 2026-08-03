"""Canonical verified executor including deterministic login grounding."""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import copy
import importlib.util
from pathlib import Path

from config.settings import settings


_SOURCE_PATH = (
    Path(__file__).resolve().parent.parent / "keyboard_verified_secure_playwright_exec.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "executor._keyboard_verified_secure_source", _SOURCE_PATH
)
_SOURCE = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_SOURCE)


class KeyboardVerifiedSecurePlaywrightExecutor(
    _SOURCE.KeyboardVerifiedSecurePlaywrightExecutor
):
    """Keyboard-verified select plus semantic login field grounding."""

    def execute(self, action_info: dict) -> dict:
        if "/login" not in str(self.page.url):
            return super().execute(action_info)

        action = str(action_info.get("action", ""))
        params = action_info.get("parameters", {})
        if action == "fill":
            value = str(params.get("value", ""))
            if value and value == settings.LOGIN_USERNAME:
                grounded = copy.deepcopy(action_info)
                grounded_params = grounded.setdefault("parameters", {})
                grounded_params.clear()
                grounded_params.update({
                    "role": "textbox", "index": 0, "value": value,
                })
                return super().execute(grounded)
            if value and value == settings.LOGIN_PASSWORD:
                return self._fill_login_password(value)

        if action == "click" and self._is_login_submit(params):
            return self._submit_login()
        return super().execute(action_info)

    @staticmethod
    def _is_login_submit(params: dict) -> bool:
        name = str(params.get("name", "")).replace(" ", "")
        return params.get("role") == "button" and (
            "登录" in name or "login" in name.lower()
        )

    def _fill_login_password(self, value: str) -> dict:
        print("[BOT] fill | {'semantic': 'login_password', 'value': '<redacted>'}")
        try:
            with redirect_stdout(StringIO()):
                target = self.page.locator("input[type='password']").first
                target.wait_for(state="visible", timeout=3000)
                target.fill(value, timeout=3000)
            result = {
                "success": True,
                "error_type": "",
                "message": "Login password field filled",
                "page_change": self._snapshot_page_change(),
                "context": {},
            }
        except Exception as exc:
            result = {
                "success": False,
                "error_type": "UNKNOWN_ERROR",
                "message": f"Login password fill failed: {exc}",
                "page_change": {},
                "context": {},
            }
        print(
            f"[TOOL] fill success={result['success']} "
            f"error={result['error_type'] or '-'} message={result['message']}"
        )
        return result

    def _submit_login(self) -> dict:
        print("[BOT] click | {'semantic': 'login_submit'}")
        try:
            target = self.page.locator("button[type='submit']").first
            target.wait_for(state="visible", timeout=3000)
            target.click(timeout=5000)
            result = {
                "success": True,
                "error_type": "",
                "message": "Login form submitted",
                "page_change": self._snapshot_page_change(),
                "context": {},
            }
        except Exception as exc:
            result = {
                "success": False,
                "error_type": "UNKNOWN_ERROR",
                "message": f"Login submit failed: {exc}",
                "page_change": {},
                "context": {},
            }
        print(
            f"[TOOL] click success={result['success']} "
            f"error={result['error_type'] or '-'} message={result['message']}"
        )
        return result


__all__ = ["KeyboardVerifiedSecurePlaywrightExecutor"]
