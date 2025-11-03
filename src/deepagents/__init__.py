"""DeepAgents package."""

from deepagents.config import (
    DEFAULT_EVENT_TABLE,
    DEFAULT_MESSAGE_TABLE,
    DEFAULT_METRIC_TABLE,
    DEFAULT_UPDATE_GRAPH,
    DeephavenAuthSettings,
    DeephavenSettings,
    DeephavenTableSettings,
    load_deephaven_settings,
)
from deepagents.graph import create_deep_agent
from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.middleware.subagents import CompiledSubAgent, SubAgent, SubAgentMiddleware
from deepagents.telemetry import ColumnSpec, DeephavenTelemetryEmitter, DEFAULT_EVENT_SCHEMA, DEFAULT_METRIC_SCHEMA

# Optional Deephaven MCP re-exports
try:  # pragma: no cover
    from deepagents.integrations.deephaven_mcp import (
        DeephavenMCPSettings,
        build_deephaven_mcp_tools,
    )
except Exception:  # pragma: no cover - keep import failures isolated
    DeephavenMCPSettings = None  # type: ignore
    build_deephaven_mcp_tools = None  # type: ignore

__all__ = [
    "ColumnSpec",
    "CompiledSubAgent",
    "DEFAULT_EVENT_SCHEMA",
    "DEFAULT_METRIC_SCHEMA",
    "DeephavenTelemetryEmitter",
    "FilesystemMiddleware",
    "SubAgent",
    "SubAgentMiddleware",
    "create_deep_agent",
    "DeephavenMCPSettings",
    "build_deephaven_mcp_tools",
]
