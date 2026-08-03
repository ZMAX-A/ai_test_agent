"""Backward-compatible import for the consolidated browser executor."""

from web_agent.browser import PolicyAwareBrowserExecutor

KeyboardTextPolicyBrowserExecutor = PolicyAwareBrowserExecutor

__all__ = ["KeyboardTextPolicyBrowserExecutor"]
