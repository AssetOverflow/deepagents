"""Tool factory helpers for Deephaven MCP integration."""
from __future__ import annotations

from typing import Any, Sequence

try:  # pragma: no cover - optional dependency at runtime
    from langchain_core.tools import StructuredTool
except Exception:  # pragma: no cover
    StructuredTool = None  # type: ignore

from .client import DeephavenMCPClient


def build_tools(client: DeephavenMCPClient) -> Sequence[Any]:
    tools: list[Any] = []
    if StructuredTool is None:  # pragma: no cover - degraded mode
        return tools

    async def _run_query(script: str, max_rows: int | None = None) -> dict[str, Any]:
        result = await client.run_query(script, max_rows=max_rows)
        return result.model_dump()

    async def _materialize(table: str, format: str = "parquet") -> dict[str, Any]:
        return await client.materialize(table, format=format)

    async def _subscribe(table: str) -> dict[str, Any]:
        token = await client.subscribe(table)
        return {"subscription": token}

    tools.append(
        StructuredTool.from_function(
            _run_query,
            name="deephaven_run_query",
            description="Execute a Deephaven script via MCP and return a summary of the results.",
        )
    )
    tools.append(
        StructuredTool.from_function(
            _materialize,
            name="deephaven_materialize_table",
            description="Materialize a Deephaven table to an artifact and return its descriptor.",
        )
    )
    tools.append(
        StructuredTool.from_function(
            _subscribe,
            name="deephaven_subscribe_table",
            description="Subscribe to a Deephaven table and return a subscription token.",
        )
    )
    return tools


__all__ = ["build_tools"]

