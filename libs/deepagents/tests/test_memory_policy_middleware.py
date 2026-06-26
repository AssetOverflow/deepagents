import asyncio
from typing import Any

import pytest
from langchain_core.messages import ToolMessage

from deepagents.middleware import AuditEvent, MemoryPolicyEvent, MemoryPolicyMiddleware, MemoryProposal


class FakeToolCallRequest:
    def __init__(self, name: str, args: dict[str, Any], tool_call_id: str = "call-1") -> None:
        self.tool_call = {"name": name, "args": args, "id": tool_call_id}


def test_disabled_mode_blocks_memory_write_and_emits_events() -> None:
    policy_events: list[MemoryPolicyEvent] = []
    audit_events: list[AuditEvent] = []
    middleware = MemoryPolicyMiddleware(
        mode="disabled",
        on_memory_policy_event=policy_events.append,
        audit_sink=audit_events.append,
    )
    request = FakeToolCallRequest("write_file", {"file_path": "/memories/user.md", "content": "remember"}, "call-memory")

    def handler(_: FakeToolCallRequest) -> ToolMessage:
        raise AssertionError("handler should not run")

    result = middleware.wrap_tool_call(request, handler)  # type: ignore[arg-type]

    assert isinstance(result, ToolMessage)
    assert result.tool_call_id == "call-memory"
    assert "blocked" in str(result.content)
    assert policy_events == [
        MemoryPolicyEvent("disabled", "write_file", "/memories/user.md", "memory write blocked by disabled mode", "blocked", None)
    ]
    assert audit_events[-1].stage == "tool_call_denied"
    assert audit_events[-1].status == "denied"
    assert audit_events[-1].metadata["memory_policy_mode"] == "disabled"


def test_proposal_only_mode_converts_memory_write_to_proposal() -> None:
    policy_events: list[MemoryPolicyEvent] = []
    middleware = MemoryPolicyMiddleware(mode="proposal_only", on_memory_policy_event=policy_events.append)
    request = FakeToolCallRequest("edit_file", {"file_path": "/memories/user.md", "old_string": "a", "new_string": "b"})

    def handler(_: FakeToolCallRequest) -> ToolMessage:
        raise AssertionError("handler should not run")

    result = middleware.wrap_tool_call(request, handler)  # type: ignore[arg-type]

    assert isinstance(result, ToolMessage)
    assert "Memory policy proposal" in str(result.content)
    assert "Authority: proposal_only" in str(result.content)
    assert isinstance(policy_events[0].proposal, MemoryProposal)
    assert policy_events[0].proposal.path == "/memories/user.md"
    assert policy_events[0].action == "proposed"


def test_approved_mode_allows_memory_write() -> None:
    policy_events: list[MemoryPolicyEvent] = []
    middleware = MemoryPolicyMiddleware(mode="approved", on_memory_policy_event=policy_events.append)
    request = FakeToolCallRequest("write_file", {"file_path": "/memories/user.md", "content": "remember"})

    def handler(next_request: FakeToolCallRequest) -> ToolMessage:
        return ToolMessage(content="ok", name=next_request.tool_call["name"], tool_call_id=next_request.tool_call["id"])

    result = middleware.wrap_tool_call(request, handler)  # type: ignore[arg-type]

    assert isinstance(result, ToolMessage)
    assert result.content == "ok"
    assert policy_events == [
        MemoryPolicyEvent("approved", "write_file", "/memories/user.md", "memory write allowed by approved mode", "allowed", None)
    ]


def test_non_memory_write_passes_through() -> None:
    policy_events: list[MemoryPolicyEvent] = []
    middleware = MemoryPolicyMiddleware(mode="disabled", on_memory_policy_event=policy_events.append)
    request = FakeToolCallRequest("write_file", {"file_path": "/workspace/report.md", "content": "draft"})

    def handler(next_request: FakeToolCallRequest) -> ToolMessage:
        return ToolMessage(content="ok", name=next_request.tool_call["name"], tool_call_id=next_request.tool_call["id"])

    result = middleware.wrap_tool_call(request, handler)  # type: ignore[arg-type]

    assert isinstance(result, ToolMessage)
    assert result.content == "ok"
    assert policy_events == [
        MemoryPolicyEvent("disabled", "write_file", "/workspace/report.md", "path does not target memory prefixes", "allowed", None)
    ]


def test_upload_files_targeting_memory_prefix_is_blocked() -> None:
    middleware = MemoryPolicyMiddleware(mode="disabled")
    request = FakeToolCallRequest(
        "upload_files",
        {"files": [{"path": "/tmp/file.txt"}, {"path": "/memories/upload.txt"}]},
    )

    def handler(_: FakeToolCallRequest) -> ToolMessage:
        raise AssertionError("handler should not run")

    result = middleware.wrap_tool_call(request, handler)  # type: ignore[arg-type]

    assert isinstance(result, ToolMessage)
    assert "upload_files" in str(result.content)
    assert "blocked" in str(result.content)


def test_custom_memory_prefixes() -> None:
    middleware = MemoryPolicyMiddleware(mode="proposal_only", memory_prefixes=("memory",))
    request = FakeToolCallRequest("write_file", {"file_path": "/memory/project.md", "content": "remember"})

    decision = middleware.decide("write_file", request.tool_call["args"])

    assert decision.allowed is False
    assert decision.proposal is not None
    assert decision.proposal.path == "/memory/project.md"


def test_invalid_mode_rejected() -> None:
    with pytest.raises(ValueError, match="mode"):
        MemoryPolicyMiddleware(mode="invalid")  # type: ignore[arg-type]


def test_async_memory_policy_allows_non_memory_tool() -> None:
    async def run() -> ToolMessage:
        middleware = MemoryPolicyMiddleware(mode="disabled")
        request = FakeToolCallRequest("read_file", {"file_path": "/memories/user.md"}, "call-read")

        async def handler(next_request: FakeToolCallRequest) -> ToolMessage:
            return ToolMessage(content="read", name=next_request.tool_call["name"], tool_call_id=next_request.tool_call["id"])

        result = await middleware.awrap_tool_call(request, handler)  # type: ignore[arg-type]
        assert isinstance(result, ToolMessage)
        return result

    result = asyncio.run(run())

    assert result.content == "read"
    assert result.tool_call_id == "call-read"
