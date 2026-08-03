"""Production browser execution boundary.

The package exposes one canonical executor. Historical class names remain in
small compatibility modules, but all production composition imports this
implementation directly.
"""

from web_agent.browser.executor import PolicyAwareBrowserExecutor

__all__ = ["PolicyAwareBrowserExecutor"]
