"""Basic smoke tests for Deephaven MCP tool integration.

These tests exercise that enabling the feature flag augments the tool list
and that the stub client executes without raising exceptions.
"""
from __future__ import annotations

import pytest

from deepagents import create_deep_agent


@pytest.mark.asyncio
async def test_enable_deephaven_mcp_adds_tools() -> None:
    agent = create_deep_agent(
        model="claude-sonnet-4-5-20250929",
        enable_deephaven_mcp=True,
        deephaven_mcp_settings={"url": "ws://localhost:9999"},
        tools=[],
    )
    # Tools are attached to compiled graph config; we can inspect internal attr
    tool_names = {getattr(t, "name", None) for t in agent.tools}  # type: ignore[attr-defined]
    expected = {"deephaven_run_query", "deephaven_materialize_table", "deephaven_subscribe_table"}
    assert expected.issubset(tool_names)


@pytest.mark.asyncio
async def test_run_query_tool_executes() -> None:
    agent = create_deep_agent(
        model="claude-sonnet-4-5-20250929",
        enable_deephaven_mcp=True,
        deephaven_mcp_settings={"url": "ws://localhost:9999"},
        tools=[],
    )
    # Find the query tool
    query_tool = None
    for t in agent.tools:  # type: ignore[attr-defined]
        if getattr(t, "name", None) == "deephaven_run_query":
            query_tool = t
            break
    assert query_tool is not None, "Query tool not found"

    # StructuredTool exposes an async arun or invoke; we use invoke for simplicity
    result = await query_tool.ainvoke({"script": "select 1"})  # type: ignore[attr-defined]
    assert isinstance(result, dict)
    assert "rows" in result
