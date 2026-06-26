import asyncio
from typing import Any

import pytest
from langchain_core.messages import ToolMessage

from deepagents.middleware import AuditEvent, AuditEventMiddleware, ToolPolicyMiddleware


class FakeToolCallRequest:
    def __init__(self, name: str, tool_call_id: str = "call-1") -> None:
        self.tool_call = {"name": name, "id": tool_call_id}


class FakeModelRequest:
    def __init__(self, tools: list[Any]) -> None:
        self.tools = tools

    def override(self, *, tools: list[Any]) -> "FakeModelRequest":
        return FakeModelRequest(tools)


def test_audit_event_middleware_emits_sync_start_and_end() -> None:
    events: list[AuditEvent] = []
    middleware = AuditEventMiddleware(events.append)
    request = FakeToolCallRequest("read_file", "call-read")

    def handler(next_request: FakeToolCallRequest) -> ToolMessage:
        return ToolMessage(content="ok", name=next_request.tool_call["name"], tool_call_id=next_request.tool_call["id"])

    result = middleware.wrap_tool_call(request, handler)  # type: ignore[arg-type]

    assert isinstance(result, ToolMessage)
    assert [(event.stage, event.status, event.tool_name, event.tool_call_id) for event in events] == [
        ("tool_call_start", "started", "read_file", "call-read"),
        ("tool_call_end", "success", "read_file", "call-read"),
    ]
    assert events[-1].result_type == "ToolMessage"


def test_audit_event_middleware_emits_sync_error_then_reraises() -> None:
    events: list[AuditEvent] = []
    middleware = AuditEventMiddleware(events.append)
    request = FakeToolCallRequest("explode", "call-error")

    def handler(_: FakeToolCallRequest) -> ToolMessage:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        middleware.wrap_tool_call(request, handler)  # type: ignore[arg-type]

    assert [(event.stage, event.status, event.tool_name, event.tool_call_id, event.reason) for event in events] == [
        ("tool_call_start", "started", "explode", "call-error", None),
        ("tool_call_error", "error", "explode", "call-error", "RuntimeError"),
    ]


def test_audit_event_middleware_emits_async_start_and_end() -> None:
    async def run() -> list[AuditEvent]:
        events: list[AuditEvent] = []
        middleware = AuditEventMiddleware(events.append)
        request = FakeToolCallRequest("read_file", "call-async")

        async def handler(next_request: FakeToolCallRequest) -> ToolMessage:
            return ToolMessage(content="ok", name=next_request.tool_call["name"], tool_call_id=next_request.tool_call["id"])

        result = await middleware.awrap_tool_call(request, handler)  # type: ignore[arg-type]
        assert isinstance(result, ToolMessage)
        return events

    events = asyncio.run(run())

    assert [(event.stage, event.status, event.tool_name, event.tool_call_id) for event in events] == [
        ("tool_call_start", "started", "read_file", "call-async"),
        ("tool_call_end", "success", "read_file", "call-async"),
    ]


def test_tool_policy_emits_generic_audit_events_for_filter_and_denial() -> None:
    events: list[AuditEvent] = []
    middleware = ToolPolicyMiddleware(allow_tools={"read_file"}, audit_sink=events.append)
    request = FakeModelRequest([{"name": "read_file"}, {"name": "write_file"}])

    def model_handler(next_request: FakeModelRequest) -> FakeModelRequest:
        return next_request

    filtered_request = middleware.wrap_model_call(request, model_handler)  # type: ignore[arg-type]
    assert filtered_request.tools == [{"name": "read_file"}]

    tool_request = FakeToolCallRequest("write_file", "call-denied")

    def tool_handler(_: FakeToolCallRequest) -> ToolMessage:
        raise AssertionError("handler should not run for denied calls")

    denied_result = middleware.wrap_tool_call(tool_request, tool_handler)  # type: ignore[arg-type]

    assert isinstance(denied_result, ToolMessage)
    assert [(event.stage, event.status, event.tool_name, event.tool_call_id, event.metadata) for event in events] == [
        ("model_filter", "filtered", "write_file", None, {"tool_policy_stage": "model_filter"}),
        ("tool_call_denied", "denied", "write_file", "call-denied", {"tool_policy_stage": "tool_call"}),
    ]
