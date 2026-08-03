"""Backward-compatible import for the consolidated browser executor."""

from web_agent.browser import PolicyAwareBrowserExecutor

FinalPolicyBrowserExecutor = PolicyAwareBrowserExecutor

__all__ = ["FinalPolicyBrowserExecutor"]
