"""Opt-in governed factory for deepagents."""

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware, InterruptOnConfig
from langchain.agents.middleware.types import AgentMiddleware
from langchain.agents.structured_output import ResponseFormat
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.cache.base import BaseCache
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.base import BaseStore
from langgraph.types import Checkpointer

from deepagents.backends import ReadOnlyFilesystemBackend
from deepagents.graph import BASE_AGENT_PROMPT, _create_core_middleware, get_default_model
from deepagents.middleware import (
    AuditEventMiddleware,
    AuditEventSink,
    MemoryPolicyMiddleware,
    MemoryPolicyMode,
    SubAgentMiddleware,
    SubagentResultMode,
    ToolPolicyMiddleware,
)
from deepagents.middleware.subagents import CompiledSubAgent, SubAgent

DEFAULT_GOVERNED_ALLOW_TOOLS = frozenset({"read_todos", "write_todos", "ls", "read_file", "glob", "grep", "task"})


def create_governed_deep_agent(
    model: str | BaseChatModel | None = None,
    tools: Sequence[BaseTool | Callable | dict[str, Any]] | None = None,
    *,
    root_dir: str | Path,
    system_prompt: str | None = None,
    middleware: Sequence[AgentMiddleware] = (),
    subagents: list[SubAgent | CompiledSubAgent] | None = None,
    response_format: ResponseFormat | None = None,
    context_schema: type[Any] | None = None,
    checkpointer: Checkpointer | None = None,
    store: BaseStore | None = None,
    interrupt_on: dict[str, bool | InterruptOnConfig] | None = None,
    allow_tools: set[str] | frozenset[str] | None = None,
    deny_tools: set[str] | frozenset[str] | None = None,
    memory_mode: MemoryPolicyMode = "proposal_only",
    memory_prefixes: tuple[str, ...] = ("/memories/",),
    subagent_result_mode: SubagentResultMode = "proposal_only",
    audit_sink: AuditEventSink | None = None,
    debug: bool = False,
    name: str | None = None,
    cache: BaseCache | None = None,
) -> CompiledStateGraph:
    """Create a deep agent with governed seams enabled.

    This factory is opt-in. It does not change ``create_deep_agent`` defaults.
    """
    if model is None:
        model = get_default_model()

    backend = ReadOnlyFilesystemBackend(root_dir=root_dir)
    core_middleware_stack = _create_core_middleware(model, backend=backend)
    subagent_middleware_stack = _create_core_middleware(model, backend=backend)

    governed_middleware: list[AgentMiddleware] = [
        ToolPolicyMiddleware(
            allow_tools=allow_tools if allow_tools is not None else DEFAULT_GOVERNED_ALLOW_TOOLS,
            deny_tools=deny_tools,
            deny_by_default=True,
            audit_sink=audit_sink,
        ),
        MemoryPolicyMiddleware(
            mode=memory_mode,
            memory_prefixes=memory_prefixes,
            audit_sink=audit_sink,
        ),
    ]
    if audit_sink is not None:
        governed_middleware.append(AuditEventMiddleware(audit_sink))

    deepagent_middleware: list[AgentMiddleware] = [
        *core_middleware_stack,
        *governed_middleware,
        SubAgentMiddleware(
            default_model=model,
            default_tools=tools,
            subagents=subagents if subagents is not None else [],
            default_middleware=[*subagent_middleware_stack, *governed_middleware],
            default_interrupt_on=interrupt_on,
            general_purpose_agent=True,
            result_mode=subagent_result_mode,
        ),
    ]
    if interrupt_on is not None:
        deepagent_middleware.append(HumanInTheLoopMiddleware(interrupt_on=interrupt_on))
    deepagent_middleware.extend(middleware)

    return create_agent(
        model,
        system_prompt=system_prompt + "\n\n" + BASE_AGENT_PROMPT if system_prompt else BASE_AGENT_PROMPT,
        tools=tools,
        middleware=deepagent_middleware,
        response_format=response_format,
        context_schema=context_schema,
        checkpointer=checkpointer,
        store=store,
        debug=debug,
        name=name,
        cache=cache,
    ).with_config({"recursion_limit": 1000})
