"""Memory policy middleware for durable memory paths."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from langchain.agents.middleware.types import AgentMiddleware
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from deepagents.middleware.audit import AuditEvent, AuditEventSink, emit_audit_event

MemoryPolicyMode = Literal["disabled", "proposal_only", "approved"]
_MEMORY_WRITE_TOOLS = frozenset({"write_file", "edit_file"})


@dataclass(frozen=True)
class MemoryProposal:
    """Structured proposal record for a memory write/edit attempt."""

    tool_name: str
    path: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryPolicyDecision:
    """Decision returned by a memory policy check."""

    allowed: bool
    mode: MemoryPolicyMode
    tool_name: str
    path: str | None
    reason: str
    proposal: MemoryProposal | None = None


@dataclass(frozen=True)
class MemoryPolicyEvent:
    """Event emitted when memory policy handles a tool call."""

    mode: MemoryPolicyMode
    tool_name: str
    path: str | None
    reason: str
    action: Literal["allowed", "blocked", "proposed", "ignored"]
    proposal: MemoryProposal | None = None


class MemoryPolicyMiddleware(AgentMiddleware):
    """Policy gate for filesystem-style durable memory paths.

    The middleware only acts on configured memory prefixes and write-like tools.
    Existing behavior is unchanged unless callers pass this middleware explicitly.
    """

    def __init__(
        self,
        *,
        mode: MemoryPolicyMode = "disabled",
        memory_prefixes: tuple[str, ...] = ("/memories/",),
        on_memory_policy_event: Callable[[MemoryPolicyEvent], None] | None = None,
        audit_sink: AuditEventSink | None = None,
    ) -> None:
        """Initialize memory policy middleware."""
        self.mode = _validate_mode(mode)
        self.memory_prefixes = tuple(_normalize_prefix(prefix) for prefix in memory_prefixes)
        self.on_memory_policy_event = on_memory_policy_event
        self.audit_sink = audit_sink

    def decide(self, tool_name: str, arguments: dict[str, Any]) -> MemoryPolicyDecision:
        """Return whether the tool call should continue under memory policy."""
        if tool_name == "upload_files":
            memory_path = _first_memory_upload_path(arguments, self.memory_prefixes)
            if memory_path is None:
                return MemoryPolicyDecision(True, self.mode, tool_name, None, "tool call does not target memory prefixes")
            return self._decision_for_memory_write(tool_name, memory_path, arguments)

        if tool_name not in _MEMORY_WRITE_TOOLS:
            return MemoryPolicyDecision(True, self.mode, tool_name, None, "tool is outside memory policy scope")

        path = _extract_path(arguments)
        if path is None:
            return MemoryPolicyDecision(True, self.mode, tool_name, None, "tool call has no path argument")
        if not _matches_prefix(path, self.memory_prefixes):
            return MemoryPolicyDecision(True, self.mode, tool_name, path, "path does not target memory prefixes")
        return self._decision_for_memory_write(tool_name, path, arguments)

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """Apply memory policy to synchronous tool calls."""
        decision = self.decide(request.tool_call["name"], _tool_args(request))
        if decision.allowed:
            self._emit(MemoryPolicyEvent(self.mode, decision.tool_name, decision.path, decision.reason, "allowed"))
            return handler(request)
        return self._policy_message(request, decision)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        """Apply memory policy to asynchronous tool calls."""
        decision = self.decide(request.tool_call["name"], _tool_args(request))
        if decision.allowed:
            self._emit(MemoryPolicyEvent(self.mode, decision.tool_name, decision.path, decision.reason, "allowed"))
            return await handler(request)
        return self._policy_message(request, decision)

    def _decision_for_memory_write(
        self,
        tool_name: str,
        path: str,
        arguments: dict[str, Any],
    ) -> MemoryPolicyDecision:
        if self.mode == "approved":
            return MemoryPolicyDecision(True, self.mode, tool_name, path, "memory write allowed by approved mode")
        proposal = MemoryProposal(tool_name=tool_name, path=path, arguments=dict(arguments))
        if self.mode == "proposal_only":
            return MemoryPolicyDecision(
                False,
                self.mode,
                tool_name,
                path,
                "memory write converted to proposal",
                proposal,
            )
        return MemoryPolicyDecision(False, self.mode, tool_name, path, "memory write blocked by disabled mode")

    def _policy_message(self, request: ToolCallRequest, decision: MemoryPolicyDecision) -> ToolMessage:
        action: Literal["blocked", "proposed"] = "proposed" if decision.proposal is not None else "blocked"
        self._emit(MemoryPolicyEvent(self.mode, decision.tool_name, decision.path, decision.reason, action, decision.proposal), request)
        if decision.proposal is not None:
            content = _format_proposal_message(decision.proposal, decision.reason)
        else:
            content = f"Memory policy blocked {decision.tool_name}: {decision.reason}."
        return ToolMessage(
            content=content,
            name=decision.tool_name,
            tool_call_id=request.tool_call.get("id", "memory-policy"),
        )

    def _emit(self, event: MemoryPolicyEvent, request: ToolCallRequest | None = None) -> None:
        if self.on_memory_policy_event is not None:
            self.on_memory_policy_event(event)
        emit_audit_event(
            self.audit_sink,
            AuditEvent(
                stage="tool_call_denied" if event.action in {"blocked", "proposed"} else "tool_call_start",
                status="denied" if event.action in {"blocked", "proposed"} else "started",
                tool_name=event.tool_name,
                tool_call_id=_tool_call_id(request),
                reason=event.reason,
                metadata={
                    "memory_policy_mode": event.mode,
                    "memory_policy_action": event.action,
                    "memory_path": event.path,
                },
            ),
        )


def _validate_mode(mode: str) -> MemoryPolicyMode:
    if mode not in {"disabled", "proposal_only", "approved"}:
        msg = "mode must be one of 'disabled', 'proposal_only', or 'approved'"
        raise ValueError(msg)
    return mode  # type: ignore[return-value]


def _normalize_prefix(prefix: str) -> str:
    if not prefix:
        msg = "memory prefixes must be non-empty"
        raise ValueError(msg)
    normalized = prefix if prefix.startswith("/") else f"/{prefix}"
    return normalized if normalized.endswith("/") else f"{normalized}/"


def _matches_prefix(path: str, prefixes: tuple[str, ...]) -> bool:
    normalized = path if path.startswith("/") else f"/{path}"
    return any(normalized == prefix.rstrip("/") or normalized.startswith(prefix) for prefix in prefixes)


def _extract_path(arguments: dict[str, Any]) -> str | None:
    for key in ("file_path", "path"):
        value = arguments.get(key)
        if isinstance(value, str):
            return value
    return None


def _tool_args(request: ToolCallRequest) -> dict[str, Any]:
    args = request.tool_call.get("args", {})
    return args if isinstance(args, dict) else {}


def _tool_call_id(request: ToolCallRequest | None) -> str | None:
    if request is None:
        return None
    tool_call_id = request.tool_call.get("id")
    return tool_call_id if isinstance(tool_call_id, str) else None


def _first_memory_upload_path(arguments: dict[str, Any], prefixes: tuple[str, ...]) -> str | None:
    files = arguments.get("files")
    if not isinstance(files, list):
        return None
    for entry in files:
        path = _upload_entry_path(entry)
        if path is not None and _matches_prefix(path, prefixes):
            return path
    return None


def _upload_entry_path(entry: Any) -> str | None:
    if isinstance(entry, dict):
        path = entry.get("path")
        return path if isinstance(path, str) else None
    if isinstance(entry, tuple) and entry and isinstance(entry[0], str):
        return entry[0]
    return None


def _format_proposal_message(proposal: MemoryProposal, reason: str) -> str:
    return (
        "Memory policy proposal\n"
        f"Reason: {reason}\n"
        f"Tool: {proposal.tool_name}\n"
        f"Path: {proposal.path}\n"
        "Authority: proposal_only; review and approve before persisting."
    )
