# Memory policy middleware

Status: opt-in middleware surface.

`MemoryPolicyMiddleware` gates filesystem-style durable memory paths, such as `/memories/`, without changing default deepagents behavior.

## Why it exists

Deepagents can route durable memory through backend paths. Governed consumers may need to prevent persistent memory from becoming a hidden authority path.

This middleware gives consumers a small policy seam for write-like tool calls targeting configured memory prefixes.

## Modes

### `disabled`

Default for this middleware. Write-like calls targeting memory prefixes are blocked.

```python
MemoryPolicyMiddleware(mode="disabled")
```

### `proposal_only`

Write-like calls targeting memory prefixes are converted into proposal messages instead of being executed.

```python
MemoryPolicyMiddleware(mode="proposal_only")
```

The returned tool message includes:

```text
Memory policy proposal
Reason: memory write converted to proposal
Tool: write_file
Path: /memories/user.md
Authority: proposal_only; review and approve before persisting.
```

### `approved`

Write-like calls targeting memory prefixes are allowed to continue. Use this only when an external approval boundary has already decided that persistence is permitted.

```python
MemoryPolicyMiddleware(mode="approved")
```

## Scope

The middleware watches:

- `write_file`;
- `edit_file`;
- `upload_files` entries targeting configured memory prefixes.

It does not block reads. It does not affect non-memory paths.

## Prefixes

Default:

```python
MemoryPolicyMiddleware(memory_prefixes=("/memories/",))
```

Custom:

```python
MemoryPolicyMiddleware(memory_prefixes=("/memory/", "/profile/"))
```

## Events

The middleware can emit `MemoryPolicyEvent` records:

```python
records = []

policy = MemoryPolicyMiddleware(
    mode="proposal_only",
    on_memory_policy_event=records.append,
)
```

It can also emit generic `AuditEvent` records through `audit_sink`:

```python
audit_records = []

policy = MemoryPolicyMiddleware(
    mode="disabled",
    audit_sink=audit_records.append,
)
```

## Example with governed stack

```python
from deepagents.backends import ReadOnlyFilesystemBackend
from deepagents.middleware import AuditEventMiddleware, MemoryPolicyMiddleware, ToolPolicyMiddleware

records = []

middleware = [
    ToolPolicyMiddleware(
        allow_tools={"read_file", "ls", "glob", "grep", "write_file", "edit_file"},
        audit_sink=records.append,
    ),
    MemoryPolicyMiddleware(
        mode="proposal_only",
        audit_sink=records.append,
    ),
    AuditEventMiddleware(records.append),
]
```

## Non-goals

This middleware does not:

- replace backend storage;
- approve memory writes by itself;
- persist proposals;
- inspect model reasoning;
- validate proposal quality;
- rewrite long-term memory architecture;
- change default `create_deep_agent` behavior.

## Compatibility

Existing callers see no behavior change unless they explicitly pass `MemoryPolicyMiddleware`.
