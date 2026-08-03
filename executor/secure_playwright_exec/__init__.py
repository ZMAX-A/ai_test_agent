"""Credential-safe Playwright executor with observable tool results.

The package intentionally shadows the historical module of the same name.  It
keeps sensitive input values out of logs while exposing the success flag,
error code, and a sanitized message so the reasoning loop can distinguish an
attempted action from a verified action.
"""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO

from core.credential_vault import CredentialVault
from executor.playwright_exec import PlaywrightExecutor


class SecurePlaywrightExecutor(PlaywrightExecutor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._credential_vault = CredentialVault()

    def execute(self, action_info: dict) -> dict:
        action = str(action_info.get("action", ""))
        params = self._credential_vault.sanitize(
            dict(action_info.get("parameters", {}))
        )
        if params.get("value") not in (None, ""):
            params["value"] = f"<redacted:{len(str(params['value']))}>"
        print(f"[BOT] {action} | {params}")

        # The legacy executor prints raw parameters, so suppress its output.
        with redirect_stdout(StringIO()):
            result = super().execute(action_info)

        safe_message = self._credential_vault.sanitize_text(
            str(result.get("message", ""))
        )
        error = str(result.get("error", "") or result.get("error_code", ""))
        print(
            f"[TOOL] {action} success={bool(result.get('success'))} "
            f"error={error or '-'} message={safe_message}"
        )
        return result


__all__ = ["SecurePlaywrightExecutor"]
