"""Small import compatibility hooks for dynamically loaded legacy modules.

Python's dataclass decorator looks up the defining module in ``sys.modules``
during class creation.  Compatibility adapters load legacy source into an
isolated namespace, so reserve that namespace before the adapter executes.
No application classes or methods are changed here.
"""

import sys
import types


sys.modules.setdefault(
    "agents._verifier_agent_source",
    types.ModuleType("agents._verifier_agent_source"),
)
