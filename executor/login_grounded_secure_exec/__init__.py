"""Compatibility name for the canonical grounded verified executor."""

from config.settings import settings
from executor.keyboard_verified_secure_playwright_exec import (
    KeyboardVerifiedSecurePlaywrightExecutor,
)


LoginGroundedSecureExecutor = KeyboardVerifiedSecurePlaywrightExecutor

__all__ = ["LoginGroundedSecureExecutor", "settings"]
