"""Deephaven MCP integration layer.

This package provides optional tool factories and settings for integrating
with a running `deephaven-mcp` Model Context Protocol server. The integration
is intentionally lightweight: if the dependency is not installed the rest of
DeepAgents continues to function normally.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Sequence

try:  # pragma: no cover - optional dependency
    from langchain_core.tools import StructuredTool
except Exception:  # pragma: no cover - minimal fallback
    StructuredTool = Any  # type: ignore


@dataclass(slots=True)
class DeephavenMCPSettings:
    """Settings controlling the Deephaven MCP tool layer.

    Attributes:
        url: Base URL (ws:// or http[s]://) for the deephaven-mcp server.
        token: Optional bearer / API token for authenticating tool calls.
        timeout_seconds: Request timeout applied to individual tool calls.
        max_rows: Default maximum number of rows to return for query tools.
    """

    url: str
    token: str | None = None
    timeout_seconds: float = 30.0
    max_rows: int = 250

    def validate(self) -> None:
        if not self.url:
            raise ValueError("DeephavenMCPSettings.url must be provided")
        if self.max_rows <= 0:
            raise ValueError("max_rows must be positive")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


def _lazy_import_client() -> Any:  # pragma: no cover - side effect isolation
    """Import the MCP client implementation lazily.

    This indirection keeps import errors isolated so that simply importing
    this package doesn't fail when the optional dependency is absent.
    """
    from .client import DeephavenMCPClient  # type: ignore
    return DeephavenMCPClient


def build_deephaven_mcp_tools(settings: DeephavenMCPSettings | dict | None) -> Sequence[Any]:
    """Build the Deephaven MCP tool suite.

    Args:
        settings: Either a :class:`DeephavenMCPSettings` instance, a mapping of
            settings keyword arguments, or ``None`` (in which case an empty
            sequence is returned).

    Returns:
        A sequence of LangChain tool objects.
    """
    if settings is None:
        return []
    if isinstance(settings, dict):
        settings = DeephavenMCPSettings(**settings)
    if not isinstance(settings, DeephavenMCPSettings):  # pragma: no cover - defensive
        raise TypeError("settings must be DeephavenMCPSettings, dict, or None")
    settings.validate()
    DeephavenMCPClient = _lazy_import_client()
    client = DeephavenMCPClient(settings)
    from .tools import build_tools  # type: ignore

    return build_tools(client)

__all__ = [
    "DeephavenMCPSettings",
    "build_deephaven_mcp_tools",
]

