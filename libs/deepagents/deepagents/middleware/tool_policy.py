"""Tool policy middleware for filtering and blocking tool calls."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, ModelRequest, ModelResponse
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from deepagents.middleware.audit import AuditEvent, AuditEventSink, emit_audit_event


@dataclass(frozen=True)
class ToolPolicyDecision:
    """Decision returned by a tool policy check."""

    allowed: bool
    tool_name: str
    reason: str


@dataclass(frozen=True)
class ToolPolicyEvent:
    """Event emitted when a tool is filtered or denied."""

    tool_name: str
    reason: str
    stage: str


class ToolPolicyMiddleware(AgentMiddleware):
    """Deny-by-default tool filtering middleware.

    The middleware has two layers:

    - model-call filtering removes disallowed tools from the model request;
    - tool-call guarding returns a ToolMessage if a disallowed call reaches the
      tool invocation layer anyway.

    ``allow_tools`` and ``deny_tools`` accept exact names, namespace wildcards
    such as ``github.*``, and the global wildcard ``*``.
    """

    def __init__(
        self,
        *,
        allow_tools: set[str] | frozenset[str] | None = None,
        deny_tools: set[str] | frozenset[str] | None = None,
        deny_by_default: bool = True,
        denial_message: str | None = None,
        on_denied_tool_call: Callable[[ToolPolicyEvent], None] | None = None,
        audit_sink: AuditEventSink | None = None,
    ) -> None:
        """Initialize the tool policy middleware."""
        self.allow_tools = frozenset(allow_tools or set())
        self.deny_tools = frozenset(deny_tools or set())
        self.deny_by_default = deny_by_default
        self.denial_message = denial_message or "Tool call denied by ToolPolicyMiddleware"
        self.on_denied_tool_call = on_denied_tool_call
        self.audit_sink = audit_sink

    def decide(self, tool_name: str) -> ToolPolicyDecision:
        """Return whether ``tool_name`` is allowed by this policy."""
        if self._matches_any(tool_name, self.deny_tools):
            return ToolPolicyDecision(False, tool_name, f"tool '{tool_name}' is explicitly denied")
        if self._matches_any(tool_name, self.allow_tools):
            return ToolPolicyDecision(True, tool_name, f"tool '{tool_name}' is explicitly allowed")
        if self.deny_by_default:
            return ToolPolicyDecision(False, tool_name, f"tool '{tool_name}' is not in allow_tools")
        return ToolPolicyDecision(True, tool_name, f"tool '{tool_name}' allowed by default")

    def filter_tools(self, tools: list[Any]) -> list[Any]:
        """Filter a tool list according to this policy."""
        filtered: list[Any] = []
        for candidate in tools:
            name = _tool_name(candidate)
            if name is None:
                if self.deny_by_default:
                    self._emit(ToolPolicyEvent("<unknown>", "tool has no discoverable name", "model_filter"))
                    continue
                filtered.append(candidate)
                continue
            decision = self.decide(name)
            if decision.allowed:
                filtered.append(candidate)
            else:
                self._emit(ToolPolicyEvent(name, decision.reason, "model_filter"))
        return filtered

    def wrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]) -> ModelResponse:
        """Remove disallowed tools before the model is called."""
        request = request.override(tools=self.filter_tools(list(request.tools)))
        return handler(request)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """Remove disallowed tools before the model is called."""
        request = request.override(tools=self.filter_tools(list(request.tools)))
        return await handler(request)

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """Block disallowed tool invocations."""
        decision = self.decide(request.tool_call["name"])
        if not decision.allowed:
            return self._denial_message(request, decision, stage="tool_call")
        return handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        """Block disallowed tool invocations."""
        decision = self.decide(request.tool_call["name"])
        if not decision.allowed:
            return self._denial_message(request, decision, stage="tool_call")
        return await handler(request)

    def _denial_message(self, request: ToolCallRequest, decision: ToolPolicyDecision, *, stage: str) -> ToolMessage:
        event = ToolPolicyEvent(decision.tool_name, decision.reason, stage)
        self._emit(event, tool_call_id=request.tool_call.get("id"))
        return ToolMessage(
            content=f"{self.denial_message}: {decision.reason}.",
            name=decision.tool_name,
            tool_call_id=request.tool_call.get("id", "tool-policy-denial"),
        )

    def _emit(self, event: ToolPolicyEvent, tool_call_id: str | None = None) -> None:
        if self.on_denied_tool_call is not None:
            self.on_denied_tool_call(event)
        emit_audit_event(
            self.audit_sink,
            AuditEvent(
                stage="tool_call_denied" if event.stage == "tool_call" else "model_filter",
                status="denied" if event.stage == "tool_call" else "filtered",
                tool_name=event.tool_name,
                tool_call_id=tool_call_id,
                reason=event.reason,
                metadata={"tool_policy_stage": event.stage},
            ),
        )

    def _matches_any(self, tool_name: str, patterns: frozenset[str]) -> bool:
        return any(_pattern_matches(tool_name, pattern) for pattern in patterns)


def _tool_name(tool: Any) -> str | None:
    if hasattr(tool, "name"):
        name = getattr(tool, "name")
        return name if isinstance(name, str) else None
    if isinstance(tool, dict):
        name = tool.get("name")
        return name if isinstance(name, str) else None
    return None


def _pattern_matches(tool_name: str, pattern: str) -> bool:
    if pattern == "*":
        return True
    if pattern.endswith(".*"):
        return tool_name.startswith(pattern[:-1])
    return tool_name == pattern
