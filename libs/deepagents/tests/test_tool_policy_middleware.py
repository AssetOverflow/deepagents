import asyncio
from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool

from deepagents.middleware import ToolPolicyEvent, ToolPolicyMiddleware


class FakeModelRequest:
    def __init__(self, tools: list[Any]) -> None:
        self.tools = tools

    def override(self, *, tools: list[Any]) -> "FakeModelRequest":
        return FakeModelRequest(tools)


class FakeToolCallRequest:
    def __init__(self, name: str, tool_call_id: str = "call-1") -> None:
        self.tool_call = {"name": name, "id": tool_call_id}


@tool
def read_file() -> str:
    """Read a file."""
    return "read"


@tool
def write_file() -> str:
    """Write a file."""
    return "write"


def _tool_names(tools: list[Any]) -> list[str]:
    return [tool.name if hasattr(tool, "name") else tool["name"] for tool in tools]


def test_filter_tools_is_deny_by_default() -> None:
    middleware = ToolPolicyMiddleware(allow_tools={"read_file"})

    filtered = middleware.filter_tools([read_file, write_file, {"name": "github.list_prs"}])

    assert _tool_names(filtered) == ["read_file"]


def test_deny_tools_override_allow_tools() -> None:
    middleware = ToolPolicyMiddleware(allow_tools={"*"}, deny_tools={"write_file"})

    assert middleware.decide("read_file").allowed is True
    write_decision = middleware.decide("write_file")
    assert write_decision.allowed is False
    assert "explicitly denied" in write_decision.reason


def test_namespace_wildcards_are_supported() -> None:
    middleware = ToolPolicyMiddleware(allow_tools={"github.*"}, deny_by_default=True)

    assert middleware.decide("github.list_pull_requests").allowed is True
    assert middleware.decide("filesystem.read_file").allowed is False


def test_model_call_filters_request_tools_and_emits_events() -> None:
    events: list[ToolPolicyEvent] = []
    middleware = ToolPolicyMiddleware(allow_tools={"read_file"}, on_denied_tool_call=events.append)
    request = FakeModelRequest([read_file, write_file, {"name": "github.list_prs"}, object()])

    def handler(next_request: FakeModelRequest) -> FakeModelRequest:
        return next_request

    result = middleware.wrap_model_call(request, handler)  # type: ignore[arg-type]

    assert _tool_names(result.tools) == ["read_file"]
    assert [(event.tool_name, event.stage) for event in events] == [
        ("write_file", "model_filter"),
        ("github.list_prs", "model_filter"),
        ("<unknown>", "model_filter"),
    ]


def test_tool_call_guard_returns_denial_message() -> None:
    events: list[ToolPolicyEvent] = []
    middleware = ToolPolicyMiddleware(allow_tools={"read_file"}, on_denied_tool_call=events.append)
    request = FakeToolCallRequest("write_file", "call-denied")

    def handler(_: FakeToolCallRequest) -> ToolMessage:
        raise AssertionError("handler should not run for denied tool")

    result = middleware.wrap_tool_call(request, handler)  # type: ignore[arg-type]

    assert isinstance(result, ToolMessage)
    assert result.tool_call_id == "call-denied"
    assert result.name == "write_file"
    assert "not in allow_tools" in str(result.content)
    assert events[-1] == ToolPolicyEvent("write_file", "tool 'write_file' is not in allow_tools", "tool_call")


def test_tool_call_guard_allows_permitted_tool() -> None:
    middleware = ToolPolicyMiddleware(allow_tools={"read_file"})
    request = FakeToolCallRequest("read_file", "call-allowed")

    def handler(next_request: FakeToolCallRequest) -> ToolMessage:
        return ToolMessage(content="ok", name=next_request.tool_call["name"], tool_call_id=next_request.tool_call["id"])

    result = middleware.wrap_tool_call(request, handler)  # type: ignore[arg-type]

    assert isinstance(result, ToolMessage)
    assert result.content == "ok"
    assert result.tool_call_id == "call-allowed"


def test_async_tool_call_guard() -> None:
    async def run() -> ToolMessage:
        middleware = ToolPolicyMiddleware(allow_tools={"read_file"})
        request = FakeToolCallRequest("read_file", "call-async")

        async def handler(next_request: FakeToolCallRequest) -> ToolMessage:
            return ToolMessage(content="ok", name=next_request.tool_call["name"], tool_call_id=next_request.tool_call["id"])

        result = await middleware.awrap_tool_call(request, handler)  # type: ignore[arg-type]
        assert isinstance(result, ToolMessage)
        return result

    result = asyncio.run(run())

    assert result.content == "ok"
    assert result.tool_call_id == "call-async"
