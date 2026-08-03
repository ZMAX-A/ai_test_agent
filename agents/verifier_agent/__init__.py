"""Verifier contracts with normalized navigation evidence labels."""

from __future__ import annotations

import importlib.util
from pathlib import Path


_SOURCE_PATH = Path(__file__).resolve().parent.parent / "verifier_agent.py"
_SPEC = importlib.util.spec_from_file_location(
    "agents._verifier_agent_source", _SOURCE_PATH
)
_SOURCE = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_SOURCE)

ASSERT_ACTIONS = _SOURCE.ASSERT_ACTIONS


class VerificationResult(_SOURCE.VerificationResult):
    def __init__(self, passed: bool, confidence: float, evidence=None,
                 reason: str = "", recoverable: bool = True,
                 next_action: str = "收集更多页面证据"):
        normalized = []
        for item in list(evidence or []):
            text = str(item)
            if "离开登录页" in text and "URL" not in text:
                text = f"URL {text}"
            normalized.append(text)
        super().__init__(
            passed,
            confidence,
            normalized,
            reason,
            recoverable,
            next_action,
        )


class VerifierAgent(_SOURCE.VerifierAgent):
    pass


__all__ = ["ASSERT_ACTIONS", "VerificationResult", "VerifierAgent"]
