# Audit event hooks

Status: opt-in middleware surface.

`AuditEventMiddleware` provides a small generic event stream around tool calls without changing tool behavior. It is intended for downstream systems that need to convert deepagents activity into their own audit records.

## What it observes

The middleware emits:

- `tool_call_start` before a tool handler runs;
- `tool_call_end` after a tool handler succeeds;
- `tool_call_error` before re-raising a tool handler exception.

`ToolPolicyMiddleware` can also emit the same `AuditEvent` shape when configured with `audit_sink`:

- `model_filter` when a tool is removed before model calls;
- `tool_call_denied` when an invocation is blocked by policy.

## Example

```python
from deepagents.middleware import AuditEvent, AuditEventMiddleware, ToolPolicyMiddleware

records: list[AuditEvent] = []

audit = AuditEventMiddleware(records.append)
policy = ToolPolicyMiddleware(
    allow_tools={"read_file", "ls", "glob", "grep"},
    audit_sink=records.append,
)
```

Pass the middleware explicitly when constructing an agent:

```python
agent = create_deep_agent(
    middleware=[policy, audit],
)
```

## Event shape

```python
AuditEvent(
    stage="tool_call_start",
    status="started",
    tool_name="read_file",
    tool_call_id="call-123",
    reason=None,
    result_type=None,
    metadata={},
)
```

## Intent

The event records are deliberately generic. deepagents should not emit builder-II artifacts directly. Instead, governed consumers can translate `AuditEvent` records into their own artifact or log formats.

## Non-goals

Audit hooks do not:

- persist events by themselves;
- authorize tool calls;
- approve denied tools;
- replace human-in-the-loop middleware;
- change default `create_deep_agent` behavior;
- make tool results authoritative.

## Compatibility

This is an opt-in surface. Existing callers that do not pass `AuditEventMiddleware` or `audit_sink` see no behavior change.
