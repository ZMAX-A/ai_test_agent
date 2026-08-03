"""Compatibility package for the viewport-aware unified runner.

The historical runner is loaded in an isolated module namespace and receives
the concrete browser-executor dependency there.  No executor class or method
is mutated globally, so other runners remain unaffected.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from executor.viewport_secure_playwright_exec import ViewportSecurePlaywrightExecutor


_SOURCE = Path(__file__).resolve().parent.parent / "unified_smart_runner.py"
_SPEC = importlib.util.spec_from_file_location(
    "runner._unified_smart_runner_source", _SOURCE
)
_SOURCE_MODULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_SOURCE_MODULE)

# Dependency binding is local to the isolated source module.
_SOURCE_MODULE.SecurePlaywrightExecutor = ViewportSecurePlaywrightExecutor

FORMAL_AGENTS = _SOURCE_MODULE.FORMAL_AGENTS
filter_login_setup_trace = _SOURCE_MODULE.filter_login_setup_trace
UnifiedSmartRunner = _SOURCE_MODULE.UnifiedSmartRunner

__all__ = ["FORMAL_AGENTS", "UnifiedSmartRunner", "filter_login_setup_trace"]
