"""统一凭证保险库实现。

本包优先于历史同名模块加载；默认凭证读取 Settings 当前值，便于运行时注入，
命名凭证仍通过 Settings.get_credential 从环境变量读取。
"""

from __future__ import annotations

import copy
import re
from typing import Any

from config.settings import settings


CREDENTIAL_PATTERN = re.compile(
    r"\{\{credential\.(?:(?P<key>[A-Za-z0-9_-]+)\.)?(?P<field>username|password)\}\}"
)


def _credential(key: str = "") -> dict:
    if key:
        return settings.get_credential(key)
    return {
        "username": settings.LOGIN_USERNAME,
        "password": settings.LOGIN_PASSWORD,
    }


class CredentialVault:
    @staticmethod
    def reference(field: str, key: str = "") -> str:
        prefix = f"{key}." if key else ""
        return f"{{{{credential.{prefix}{field}}}}}"

    def sanitize_text(self, text: str) -> str:
        safe = str(text or "")
        credential = _credential()
        for field in ("username", "password"):
            value = str(credential.get(field, "") or "")
            if value:
                safe = safe.replace(value, self.reference(field))
        return safe

    def sanitize(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.sanitize_text(value)
        if isinstance(value, dict):
            return {key: self.sanitize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.sanitize(item) for item in value]
        return value

    @staticmethod
    def resolve_text(text: str) -> str:
        def replace(match: re.Match) -> str:
            key = match.group("key") or ""
            field = match.group("field")
            value = str(_credential(key).get(field, "") or "")
            if not value:
                target = f"credential.{key + '.' if key else ''}{field}"
                raise RuntimeError(f"凭证引用未配置: {target}")
            return value

        return CREDENTIAL_PATTERN.sub(replace, str(text or ""))

    def tokenize_action(self, action: dict) -> dict:
        return self.sanitize(copy.deepcopy(action))

    def resolve_action(self, action: dict) -> dict:
        resolved = copy.deepcopy(action)
        parameters = resolved.get("parameters", {})
        for field, value in list(parameters.items()):
            if isinstance(value, str) and "{{credential." in value:
                parameters[field] = self.resolve_text(value)
        return resolved


__all__ = ["CREDENTIAL_PATTERN", "CredentialVault"]
