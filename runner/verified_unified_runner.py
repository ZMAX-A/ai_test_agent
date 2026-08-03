"""Production unified runner bound to the verified keyboard executor."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

from executor.keyboard_verified_secure_playwright_exec import (
    KeyboardVerifiedSecurePlaywrightExecutor,
)


_SOURCE_PATH = Path(__file__).resolve().parent / "unified_smart_runner.py"
_SOURCE_NAME = "runner._verified_unified_runner_source"
_SPEC = importlib.util.spec_from_file_location(_SOURCE_NAME, _SOURCE_PATH)
_SOURCE = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
sys.modules[_SOURCE_NAME] = _SOURCE
_SPEC.loader.exec_module(_SOURCE)

# Bind the concrete dependency only inside this runner module's namespace.
_SOURCE.SecurePlaywrightExecutor = KeyboardVerifiedSecurePlaywrightExecutor

FORMAL_AGENTS = _SOURCE.FORMAL_AGENTS
filter_login_setup_trace = _SOURCE.filter_login_setup_trace
VerifiedUnifiedSmartRunner = _SOURCE.UnifiedSmartRunner

__all__ = [
    "FORMAL_AGENTS",
    "VerifiedUnifiedSmartRunner",
    "filter_login_setup_trace",
]
