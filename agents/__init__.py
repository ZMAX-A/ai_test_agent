"""Agent package initialization and compatibility namespace reservation."""

import sys
import types


sys.modules.setdefault(
    "agents._verifier_agent_source",
    types.ModuleType("agents._verifier_agent_source"),
)
