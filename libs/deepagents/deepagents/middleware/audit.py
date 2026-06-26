"""Generic audit event middleware hooks."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from langchain.agents.middleware.types import AgentMiddleware
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

AuditEventStage = Literal[
    "tool_call_start",
    "tool_call_end",
    "tool_call_error",
    "tool_call_denied",
    "model_filter",
]
AuditEventStatus = Literal["started", "success", "error", "denied", "filtered"]
AuditEventSink = Callable[["AuditEvent"], None]


@dataclass(frozen=True)
class AuditEvent:
    """Generic event emitted by opt-in audit hooks."""

    stage: AuditEventStage
    status: AuditEventStatus
    tool_name: str
    tool_call_id: str | None = None
    reason: str | None = None
    result_type: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


class AuditEventMiddleware(AgentMiddleware):
    """Emit generic audit events around tool calls.

    This middleware observes tool calls without changing their behavior. It is
    opt-in and emits structured records to the supplied sink.
    """

    def __init__(self, sink: AuditEventSink) -> None:
        """Initialize the middleware with an event sink."""
        self.sink = sink

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """Emit start/end/error events around a synchronous tool call."""
        tool_name = _request_tool_name(request)
        tool_call_id = _request_tool_call_id(request)
        emit_audit_event(self.sink, AuditEvent("tool_call_start", "started", tool_name, tool_call_id))
        try:
            result = handler(request)
        except Exception as exc:
            emit_audit_event(
                self.sink,
                AuditEvent("tool_call_error", "error", tool_name, tool_call_id, reason=exc.__class__.__name__),
            )
            raise
        emit_audit_event(
            self.sink,
            AuditEvent("tool_call_end", "success", tool_name, tool_call_id, result_type=type(result).__name__),
        )
        return result

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        """Emit start/end/error events around an asynchronous tool call."""
        tool_name = _request_tool_name(request)
        tool_call_id = _request_tool_call_id(request)
        emit_audit_event(self.sink, AuditEvent("tool_call_start", "started", tool_name, tool_call_id))
        try:
            result = await handler(request)
        except Exception as exc:
            emit_audit_event(
                self.sink,
                AuditEvent("tool_call_error", "error", tool_name, tool_call_id, reason=exc.__class__.__name__),
            )
            raise
        emit_audit_event(
            self.sink,
            AuditEvent("tool_call_end", "success", tool_name, tool_call_id, result_type=type(result).__name__),
        )
        return result


def emit_audit_event(sink: AuditEventSink | None, event: AuditEvent) -> None:
    """Emit ``event`` to ``sink`` if one is configured."""
    if sink is not None:
        sink(event)


def _request_tool_name(request: ToolCallRequest) -> str:
    name = request.tool_call.get("name")
    return name if isinstance(name, str) else "<unknown>"


def _request_tool_call_id(request: ToolCallRequest) -> str | None:
    tool_call_id = request.tool_call.get("id")
    return tool_call_id if isinstance(tool_call_id, str) else None
