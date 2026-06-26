# Subagent result modes

Status: opt-in middleware surface.

`SubAgentMiddleware` supports a `result_mode` setting that controls how returned subagent results are framed for the parent agent.

## Modes

### `trusted`

Default. Preserves existing behavior.

```python
SubAgentMiddleware(
    default_model="openai:gpt-4o",
    result_mode="trusted",
)
```

The task tool forwards the subagent's final message as the tool result.

### `proposal_only`

Opt-in. The task tool description tells the parent agent to treat subagent outputs as candidate reports, not authoritative conclusions. Returned tool results are wrapped with an explicit proposal envelope.

```python
SubAgentMiddleware(
    default_model="openai:gpt-4o",
    result_mode="proposal_only",
)
```

Returned content is framed like:

```text
Subagent result mode: proposal_only
Subagent type: reviewer
Authority: proposal_only; reconcile and validate this result before relying on it.

<subagent final message>
```

## Intent

`proposal_only` is intended for governed consumers that want subagent delegation without treating subagent output as final authority.

Typical uses:

- code review reports;
- repository mapping reports;
- research summaries;
- candidate findings;
- multi-agent decomposition where the parent reconciles several reports.

## Non-goals

This setting does not:

- prevent subagent execution;
- change subagent tools;
- approve or deny tool calls;
- inspect hidden subagent intermediate steps;
- validate the result;
- persist an audit artifact by itself.

Use it with `ToolPolicyMiddleware`, `ReadOnlyFilesystemBackend`, and `AuditEventMiddleware` when building governed harnesses.

## Compatibility

The default remains `trusted`, so existing callers see no behavior change unless they opt in.
