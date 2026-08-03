"""Production runner with verified select and grounded login semantics."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

from executor.login_grounded_secure_exec import LoginGroundedSecureExecutor


_SOURCE_PATH = Path(__file__).resolve().parent.parent / "unified_smart_runner.py"
_SOURCE_NAME = "runner._production_unified_runner_source"
_SPEC = importlib.util.spec_from_file_location(_SOURCE_NAME, _SOURCE_PATH)
_SOURCE = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
sys.modules[_SOURCE_NAME] = _SOURCE
_SPEC.loader.exec_module(_SOURCE)

_SOURCE.SecurePlaywrightExecutor = LoginGroundedSecureExecutor

FORMAL_AGENTS = _SOURCE.FORMAL_AGENTS
filter_login_setup_trace = _SOURCE.filter_login_setup_trace
VerifiedUnifiedSmartRunner = _SOURCE.UnifiedSmartRunner

__all__ = [
    "FORMAL_AGENTS",
    "VerifiedUnifiedSmartRunner",
    "filter_login_setup_trace",
]
