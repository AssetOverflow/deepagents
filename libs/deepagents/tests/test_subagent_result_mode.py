import asyncio
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from langgraph.types import Command

from deepagents.middleware import SubAgentMiddleware
from deepagents.middleware.subagents import _create_task_tool


class FakeRuntime:
    state = {"context": "kept", "messages": ["excluded"], "todos": ["excluded"]}
    tool_call_id = "task-call-1"


class FakeRunnable:
    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        assert state["context"] == "kept"
        assert state["messages"][0].content == "inspect repository"
        assert "todos" not in state
        return {"messages": [AIMessage(content="candidate report")], "todos": ["excluded"], "extra": "preserved"}

    async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
        assert state["context"] == "kept"
        assert state["messages"][0].content == "inspect repository"
        assert "todos" not in state
        return {"messages": [AIMessage(content="async candidate report")], "todos": ["excluded"], "extra": "preserved"}


def _task_tool(result_mode: str = "trusted"):
    return _create_task_tool(
        default_model="fake-model",
        default_tools=[],
        default_middleware=[],
        default_interrupt_on=None,
        subagents=[{"name": "reviewer", "description": "Reviews results", "runnable": FakeRunnable()}],
        general_purpose_agent=False,
        result_mode=result_mode,  # type: ignore[arg-type]
    )


def test_subagent_middleware_defaults_to_trusted_mode() -> None:
    middleware = SubAgentMiddleware(default_model="fake-model", general_purpose_agent=False, subagents=[])

    assert "proposal_only" not in middleware.tools[0].description
    assert "outputs should generally be trusted" in middleware.tools[0].description


def test_subagent_middleware_rejects_invalid_result_mode() -> None:
    with pytest.raises(ValueError, match="result_mode"):
        SubAgentMiddleware(default_model="fake-model", result_mode="invalid")  # type: ignore[arg-type]


def test_proposal_only_mode_updates_task_description() -> None:
    middleware = SubAgentMiddleware(default_model="fake-model", result_mode="proposal_only", general_purpose_agent=False, subagents=[])

    description = middleware.tools[0].description
    assert "proposal-only" in description
    assert "outputs should generally be trusted" not in description
    assert "reconcile and validate" in description


def test_proposal_only_mode_wraps_sync_result_content() -> None:
    tool = _task_tool(result_mode="proposal_only")

    result = tool.func(description="inspect repository", subagent_type="reviewer", runtime=FakeRuntime())

    assert isinstance(result, Command)
    message = result.update["messages"][0]
    assert message.tool_call_id == "task-call-1"
    assert "Subagent result mode: proposal_only" in message.content
    assert "Subagent type: reviewer" in message.content
    assert "Authority: proposal_only" in message.content
    assert "candidate report" in message.content
    assert result.update["extra"] == "preserved"
    assert "todos" not in result.update


def test_trusted_mode_preserves_sync_result_content() -> None:
    tool = _task_tool(result_mode="trusted")

    result = tool.func(description="inspect repository", subagent_type="reviewer", runtime=FakeRuntime())

    assert isinstance(result, Command)
    message = result.update["messages"][0]
    assert message.content == "candidate report"
    assert "proposal_only" not in message.content


def test_proposal_only_mode_wraps_async_result_content() -> None:
    async def run() -> Command:
        tool = _task_tool(result_mode="proposal_only")
        result = await tool.coroutine(description="inspect repository", subagent_type="reviewer", runtime=FakeRuntime())
        assert isinstance(result, Command)
        return result

    result = asyncio.run(run())

    message = result.update["messages"][0]
    assert "Subagent result mode: proposal_only" in message.content
    assert "async candidate report" in message.content
