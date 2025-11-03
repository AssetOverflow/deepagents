"""Minimal Deephaven MCP client stub.

This is a placeholder implementation that should be expanded to speak the
actual MCP protocol used by the external `deephaven-mcp` server. For now it
exposes asynchronous method signatures that can be wired into LangChain tools
without breaking environments lacking the dependency.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import asyncio
import time

from . import DeephavenMCPSettings


@dataclass(slots=True)
class _QueryResult:
    columns: list[dict[str, Any]]
    rows: list[dict[str, Any]]
    truncated: bool
    elapsed_ms: float

    def model_dump(self) -> dict[str, Any]:  # pydantic compatibility shim
        return {
            "columns": self.columns,
            "rows": self.rows,
            "truncated": self.truncated,
            "elapsed_ms": self.elapsed_ms,
        }


class DeephavenMCPClient:
    """Lightweight stub client for Deephaven MCP server.

    Real implementation TODOs:
      * Establish persistent MCP transport (WebSocket / stdio) per protocol spec.
      * Implement auth handshake using settings.token.
      * Map tool names -> structured invocation requests.
      * Stream subscription updates back to callers.
    """

    def __init__(self, settings: DeephavenMCPSettings) -> None:
        self._settings = settings

    async def run_query(self, script: str, *, max_rows: int | None = None) -> _QueryResult:
        start = time.perf_counter()
        # Placeholder: simulate query parsing/execution latency.
        await asyncio.sleep(0.01)
        data_rows = [
            {"col": 1, "preview": script[:40]},
        ]
        elapsed = (time.perf_counter() - start) * 1000.0
        return _QueryResult(
            columns=[{"name": "col", "type": "int"}, {"name": "preview", "type": "string"}],
            rows=data_rows[: max_rows or self._settings.max_rows],
            truncated=len(data_rows) > (max_rows or self._settings.max_rows),
            elapsed_ms=elapsed,
        )

    async def materialize(self, table: str, *, format: str = "parquet") -> dict[str, Any]:
        await asyncio.sleep(0.01)
        return {
            "table": table,
            "format": format,
            "artifact_path": f"deephaven/materializations/{table}.{format}",
        }

    async def subscribe(self, table: str) -> str:
        # In a real implementation this would register a streaming subscription.
        await asyncio.sleep(0.01)
        return f"subscription:{table}"

    async def close(self) -> None:  # pragma: no cover - future expansion
        pass


__all__ = ["DeephavenMCPClient"]
