"""Compatibility adapter for callers that extend the old stable executor."""

from __future__ import annotations

from web_agent.browser import PolicyAwareBrowserExecutor


class StablePolicyBrowserExecutor(PolicyAwareBrowserExecutor):
    """Preserve the historical multiple-inheritance continuation contract."""

    def _submit_and_wait(self) -> dict:
        for base in type(self).__bases__[1:]:
            continuation = base.__dict__.get("_submit_and_wait")
            if continuation is not None:
                try:
                    self.page.keyboard.press("Escape")
                    self.page.wait_for_timeout(300)
                except Exception:
                    pass
                return continuation(self)
        return super()._submit_and_wait()


__all__ = ["StablePolicyBrowserExecutor"]
