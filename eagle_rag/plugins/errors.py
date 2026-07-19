"""Plugin and hook error types."""

from __future__ import annotations

__all__ = ["HookInvocationError", "PluginLoadError"]


class PluginLoadError(RuntimeError):
    """Raised when plugin discovery, validation, or on_load fails."""


class HookInvocationError(RuntimeError):
    """Raised when a fail-fast hook subscriber raises (G13)."""

    def __init__(
        self,
        message: str,
        *,
        hook: str,
        plugin: str | None = None,
        namespace: str | None = None,
    ) -> None:
        super().__init__(message)
        self.hook = hook
        self.plugin = plugin
        self.namespace = namespace
