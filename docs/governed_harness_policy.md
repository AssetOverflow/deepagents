# Governed harness policy plan

Status: design-only plan.

This document defines how this deepagents fork should expose safer seams for governed agent platforms without becoming coupled to any one platform.

builder-II is the immediate consumer motivating this plan, but the changes described here should remain generic deepagents capabilities.

## Purpose

`create_deep_agent` is intentionally powerful. It assembles a LangGraph-based agent harness with planning, filesystem access, summarization, prompt caching, patch-tool-call repair, subagent delegation, optional HITL, and pluggable backend/store/cache surfaces.

That power is useful, but downstream governed platforms need more precise control over:

- which tools exist;
- which tools are denied;
- which backend is mounted;
- whether writes are allowed;
- whether shell execution is possible;
- whether subagents may spawn;
- whether memory may persist;
- whether MCP tools may be exposed;
- how every action is audited.

The goal is not to weaken deepagents. The goal is to make it easier to embed deepagents inside systems that require explicit policy, approval, verification, and audit boundaries.

## Non-goals

This plan does not implement:

- a builder-II dependency;
- a Goose dependency;
- MCP integration;
- a new runtime;
- command execution policy;
- write approval flow;
- memory mutation approval flow;
- source control automation;
- remote sandbox integrations;
- autonomous file writes;
- hidden model calls.

## Design principle

```text
Deepagents should expose generic governance seams.
Consumers should supply policy.
No consumer should need to fork core runtime behavior just to deny tools, capture audit events, or use a read-only backend.
```

## Desired seams

### 1. Governed construction surface

Add a policy-aware factory or configuration layer without replacing `create_deep_agent`.

Possible shape:

```python
create_governed_deep_agent(
    model=..., 
    tools=..., 
    policy=DeepAgentPolicy(...),
    audit_sink=..., 
)
```

Alternative shape:

```python
create_deep_agent(
    ..., 
    tool_policy=ToolPolicy(...),
    memory_policy=MemoryPolicy(...),
    subagent_policy=SubagentPolicy(...),
    audit_sink=..., 
)
```

The first form is safer for initial rollout because it avoids changing the semantics of existing callers.

### 2. Tool policy middleware

Add a deny-by-default middleware that can filter or block tools by name, source, risk class, or namespace.

Possible shape:

```python
ToolPolicyMiddleware(
    allow_tools={"ls", "read_file", "glob", "grep"},
    deny_tools={"write_file", "edit_file", "execute", "task"},
    deny_by_default=True,
)
```

Required behavior:

- block denied tools before model execution if possible;
- block denied tool calls at invocation time as defense in depth;
- return structured denial messages;
- emit audit events for denied attempts;
- fail closed on unknown tools when `deny_by_default=True`.

### 3. Read-only filesystem backend

Add a backend for target-repo or workspace inspection that cannot write or execute.

Possible shape:

```python
ReadOnlyFilesystemBackend(
    root_dir=Path(...),
    allowed_prefixes=("/",),
    deny_git=True,
    max_file_size_mb=..., 
)
```

Required behavior:

- `root_dir` required;
- virtual paths only;
- host absolute paths denied;
- root containment enforced;
- `.git` denied by default;
- symlink traversal denied where practical;
- `ls`, `read`, `glob`, and `grep_raw` allowed;
- `write`, `edit`, `upload_files`, and `execute` denied;
- errors structured enough for agents and audit sinks.

### 4. Audit event hooks

Add generic hooks around important actions:

- before tool call;
- after tool call;
- denied tool call;
- filesystem read/list/search;
- filesystem write/edit attempt;
- subagent spawn;
- subagent result;
- summarization created;
- memory write attempt;
- backend route selection;
- MCP tool exposure or invocation if MCP is later wired.

Events should be generic dictionaries or typed records. They should not emit builder-II-specific artifacts directly.

### 5. Subagent trust boundary

Current subagent behavior is optimized for productivity. Governed consumers need a mode where subagent output is explicitly proposal-only.

Possible shape:

```python
SubagentPolicy(
    enabled=True,
    allowed_subagents={"repo-mapper", "reviewer"},
    result_mode="proposal_only",
    allow_parallel=True,
    max_parallel=3,
)
```

Required behavior:

- subagent result can be marked proposal-only;
- result metadata includes subagent name and task;
- hidden intermediate steps remain hidden unless event/audit streaming is explicitly enabled;
- parent agent prompt must not claim subagent output is authoritative;
- denied subagent calls produce structured audit events.

### 6. Memory policy

Persistent memory should be controllable independently from state/checkpointing.

Possible shape:

```python
MemoryPolicy(
    persistent_memory="disabled" | "proposal_only" | "approved",
    state_files="allowed" | "read_only" | "disabled",
)
```

Required behavior:

- persistent memory writes denied by default in governed mode;
- proposal-only mode emits memory update proposals rather than writing;
- approved mode requires external approval mechanism supplied by consumer;
- raw credentials or secrets are never serialized into memory proposals.

### 7. MCP-ready namespace support

MCP should not be built into this policy plan, but the design should leave room for namespaced tools.

Suggested convention:

```text
server_id.tool_name
```

Examples:

```text
github.list_pull_requests
filesystem.read_file
research.search
```

Tool policy should be able to filter by namespace, original name, source, and risk classification.

## Policy object sketch

A generic policy object could look like:

```python
@dataclass(frozen=True)
class DeepAgentPolicy:
    mode: Literal["artifact_only", "read_only", "hitl_write", "approved_runtime"]
    allow_shell: bool = False
    allow_write: bool = False
    allow_edit: bool = False
    allow_subagents: bool = False
    allow_longterm_memory: bool = False
    allow_mcp: bool = False
    allowed_tools: frozenset[str] = frozenset()
    denied_tools: frozenset[str] = frozenset()
    deny_by_default: bool = True
```

This is only a sketch. The implementation should avoid over-coupling policy fields to one downstream platform.

## Compatibility with builder-II

builder-II wants to use deepagents as an optional inner harness beneath builder-II governance and, eventually, Goose runtime mediation.

That implies these requirements:

- deepagents can be used without granting write/shell/MCP authority;
- deepagents can be constructed with read-only backends;
- subagent outputs can be marked proposal-only;
- persistent memory writes can be disabled or converted to proposals;
- tool calls can emit events for builder-II audit artifacts;
- unknown tools fail closed in governed mode;
- existing non-governed deepagents behavior remains available for ordinary users.

## Proposed implementation order

### PR 1: docs only

This document.

### PR 2: read-only filesystem backend

Implement `ReadOnlyFilesystemBackend` with tests.

### PR 3: tool policy middleware

Implement deny-by-default tool filtering with tests.

### PR 4: audit event hooks

Add generic event sink hooks around tool calls and denial points.

### PR 5: proposal-only subagent result mode

Make subagent result trust boundary configurable.

### PR 6: memory proposal policy

Allow persistent memory writes to be disabled or emitted as proposals.

### PR 7: governed factory

Add a convenience factory that wires the above safely.

## Test expectations

Future implementation tests should verify:

- read-only backend rejects writes, edits, uploads, and execute;
- read-only backend denies host absolute paths;
- read-only backend enforces root containment;
- tool policy blocks denied tools;
- unknown tools fail closed in deny-by-default mode;
- denied calls emit audit events;
- subagent outputs can be proposal-only;
- memory writes can be denied or emitted as proposals;
- default `create_deep_agent` behavior remains backward compatible.

## Governing sentence

Deepagents should become easier to embed inside governed systems by exposing policy, backend, trust-boundary, memory, and audit seams while preserving its general-purpose agent harness for existing users.
