"""Configuration-driven authentication policy."""

from __future__ import annotations

from dataclasses import dataclass
import os

from config.settings import settings


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


@dataclass(frozen=True)
class AuthenticationPolicy:
    """Semantic locators and completion rules for a login form.

    The default values describe the current Ant Design application, while all
    selectors and the store-selection rule can be replaced by environment
    variables without changing the executor or reasoning loop.
    """

    login_path: str = "/login"
    username_selector: str = "input[type='text']"
    password_selector: str = "input[type='password']"
    store_selector: str = ".ant-select-selector"
    selected_store_selector: str = ".ant-select-selection-item:visible"
    submit_selector: str = "button[type='submit']"
    store_option_text: str = ""
    store_selection_mode: str = "keyboard_next"
    navigation_timeout_ms: int = 15000
    settle_ms: int = 2000

    @classmethod
    def from_environment(cls) -> "AuthenticationPolicy":
        return cls(
            login_path=os.getenv("LOGIN_PATH", "/login"),
            username_selector=os.getenv(
                "LOGIN_USERNAME_SELECTOR", "input[type='text']"
            ),
            password_selector=os.getenv(
                "LOGIN_PASSWORD_SELECTOR", "input[type='password']"
            ),
            store_selector=os.getenv(
                "LOGIN_STORE_SELECTOR", ".ant-select-selector"
            ),
            selected_store_selector=os.getenv(
                "LOGIN_SELECTED_STORE_SELECTOR",
                ".ant-select-selection-item:visible",
            ),
            submit_selector=os.getenv(
                "LOGIN_SUBMIT_SELECTOR", "button[type='submit']"
            ),
            store_option_text=os.getenv("LOGIN_STORE_OPTION_TEXT", "").strip(),
            store_selection_mode=os.getenv(
                "LOGIN_STORE_SELECTION_MODE", "keyboard_next"
            ).strip().lower(),
            navigation_timeout_ms=_positive_int(
                "LOGIN_NAVIGATION_TIMEOUT_MS", 15000
            ),
            settle_ms=_positive_int(
                "LOGIN_SETTLE_MS", settings.NAVIGATION_SETTLE_MS
            ),
        )

    def is_login_url(self, url: str) -> bool:
        return self.login_path in str(url or "")

    def validate(self) -> None:
        required = {
            "login_path": self.login_path,
            "username_selector": self.username_selector,
            "password_selector": self.password_selector,
            "store_selector": self.store_selector,
            "selected_store_selector": self.selected_store_selector,
            "submit_selector": self.submit_selector,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(
                "Authentication policy is missing: " + ", ".join(missing)
            )
        if self.store_selection_mode not in {"keyboard_next", "text"}:
            raise ValueError(
                "LOGIN_STORE_SELECTION_MODE must be keyboard_next or text"
            )
        if self.store_selection_mode == "text" and not self.store_option_text:
            raise ValueError(
                "LOGIN_STORE_OPTION_TEXT is required when selection mode is text"
            )


__all__ = ["AuthenticationPolicy"]
