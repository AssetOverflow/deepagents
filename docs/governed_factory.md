# Governed deep agent factory

Status: opt-in construction surface.

`create_governed_deep_agent` wires the governed seams added in this fork into one convenience factory. It does not change the default `create_deep_agent` behavior.

## What it composes

The factory configures:

- `ReadOnlyFilesystemBackend` rooted at an explicit `root_dir`;
- `ToolPolicyMiddleware` with deny-by-default filtering;
- `MemoryPolicyMiddleware` with `proposal_only` as the default memory mode;
- `AuditEventMiddleware` when an `audit_sink` is supplied;
- `SubAgentMiddleware(result_mode="proposal_only")` by default.

## Example

```python
from deepagents import create_governed_deep_agent

records = []

agent = create_governed_deep_agent(
    model="openai:gpt-4o",
    root_dir="/path/to/project",
    audit_sink=records.append,
)
```

## Defaults

Default allowed tool names:

```python
{
    "read_todos",
    "write_todos",
    "ls",
    "read_file",
    "glob",
    "grep",
    "task",
}
```

Unknown tools are filtered by default. Callers may override `allow_tools` and `deny_tools` explicitly.

Default policy settings:

```python
memory_mode="proposal_only"
subagent_result_mode="proposal_only"
memory_prefixes=("/memories/",)
```

## Why the backend is read-only

The governed factory starts from inspection and proposal semantics. The read-only backend gives filesystem tools a real project root while keeping persistence and mutation under separate policy seams.

## Non-goals

This factory does not:

- replace `create_deep_agent`;
- change default deepagents behavior;
- approve memory persistence by itself;
- persist audit events by itself;
- turn subagent reports into authority;
- add an MCP client;
- add a builder-II dependency.

## Compatibility

Existing callers should continue using `create_deep_agent`. Governed consumers can opt into `create_governed_deep_agent` when they want a prewired conservative stack.
