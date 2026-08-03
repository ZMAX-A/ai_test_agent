"""Clean production namespace for the Web testing agent.

Legacy entry points remain available for compatibility.  New development
belongs here so imports have one unambiguous source of truth.
"""

from web_agent.auth import AuthenticationPolicy
from web_agent.browser import PolicyAwareBrowserExecutor

__all__ = ["AuthenticationPolicy", "PolicyAwareBrowserExecutor"]
