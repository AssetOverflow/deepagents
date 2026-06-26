"""Deepagents come with planning, filesystem, and subagents."""

from collections.abc import Callable, Sequence
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware, InterruptOnConfig, TodoListMiddleware
from langchain.agents.middleware.summarization import SummarizationMiddleware
from langchain.agents.middleware.types import AgentMiddleware
from langchain.agents.structured_output import ResponseFormat
from langchain_anthropic import ChatAnthropic
from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.cache.base import BaseCache
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.base import BaseStore
from langgraph.types import Checkpointer

from deepagents.backends.protocol import BackendFactory, BackendProtocol
from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
from deepagents.middleware.subagents import CompiledSubAgent, SubAgent, SubAgentMiddleware

BASE_AGENT_PROMPT = "In order to complete the objective that the user asks of you, you have access to a number of standard tools."

# Proactive summarization threshold for cost/performance efficiency.
# This triggers summarization earlier than the model's context limit to keep prompts lean.
PROACTIVE_SUMMARY_THRESHOLD = 45000

# Default number of recent messages to keep after summarization.
DEFAULT_CONTEXT_MESSAGES_TO_KEEP = 6


def get_default_model() -> ChatAnthropic:
    """Get the default model for deep agents.

    Returns:
        ChatAnthropic instance configured with Claude Sonnet 4.
    """
    return ChatAnthropic(
        model_name="claude-sonnet-4-5-20250929",
        max_tokens=20000,
    )


def _create_core_middleware(
    model: str | BaseChatModel,
    trigger: tuple[str, float | int] | None = None,
    keep: tuple[str, float | int] | None = None,
    *,
    backend: "BackendProtocol | BackendFactory | None" = None,
) -> list[AgentMiddleware]:
    """Create the reusable middleware shared by the main agent and subagents.

    Args:
        model: The language model to use for summarization.
        trigger: Tuple of (mode, threshold) for when to trigger summarization.
            Mode is either "fraction" or "tokens". Defaults to the proactive
            token-based threshold.
        keep: Tuple of (mode, count) for how many messages to keep.
            Mode is either "fraction" or "messages". Defaults to the standard
            message-count setting.
        backend: Optional backend instance or factory for FilesystemMiddleware.

    Returns:
        A list of configured core middleware instances in order:
        [TodoListMiddleware, FilesystemMiddleware, SummarizationMiddleware,
        AnthropicPromptCachingMiddleware, PatchToolCallsMiddleware]
    """
    resolved_trigger: tuple[str, float | int] = trigger or ("tokens", PROACTIVE_SUMMARY_THRESHOLD)
    resolved_keep: tuple[str, float | int] = keep or ("messages", DEFAULT_CONTEXT_MESSAGES_TO_KEEP)
    return [
        TodoListMiddleware(),
        FilesystemMiddleware(backend=backend),
        SummarizationMiddleware(
            model=model,
            trigger=resolved_trigger,  # type: ignore[arg-type]
            keep=resolved_keep,  # type: ignore[arg-type]
            trim_tokens_to_summarize=None,
        ),
        AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore"),
        PatchToolCallsMiddleware(),
    ]


def _resolve_store(store: BaseStore | None, use_longterm_memory: bool) -> BaseStore | None:
    """Resolve the store used for agent construction.

    Long-term memory requires an explicit store until Redis-backed store
    construction is restored behind a tested integration.
    """
    if use_longterm_memory and store is None:
        msg = "use_longterm_memory=True requires an explicit store."
        raise ValueError(msg)
    return store


def _reject_unwired_options(
    *,
    redis_settings: Any | str | None,
    enable_redis_cache: bool,
    enable_redis_store: bool | None,
    redis_cache_default_ttl_seconds: int | None,
) -> None:
    """Fail closed for options whose runtime adapters are not wired.

    The ``backend`` parameter is now fully wired (FilesystemMiddleware accepts
    it), so it is intentionally omitted from this guard.
    """
    if redis_settings is not None or enable_redis_cache or enable_redis_store is True or redis_cache_default_ttl_seconds is not None:
        msg = (
            "Redis-backed cache/store construction is not available in this package build. "
            "Pass an explicit cache/store, or wire Redis adapters before enabling Redis options."
        )
        raise NotImplementedError(msg)


def create_deep_agent(
    model: str | BaseChatModel | None = None,
    tools: Sequence[BaseTool | Callable | dict[str, Any]] | None = None,
    *,
    system_prompt: str | None = None,
    middleware: Sequence[AgentMiddleware] = (),
    subagents: list[SubAgent | CompiledSubAgent] | None = None,
    response_format: ResponseFormat | None = None,
    context_schema: type[Any] | None = None,
    checkpointer: Checkpointer | None = None,
    store: BaseStore | None = None,
    use_longterm_memory: bool = False,
    backend: BackendProtocol | BackendFactory | None = None,
    interrupt_on: dict[str, bool | InterruptOnConfig] | None = None,
    debug: bool = False,
    name: str | None = None,
    cache: BaseCache | None = None,
    redis_settings: Any | str | None = None,
    enable_redis_cache: bool = False,
    enable_redis_store: bool | None = None,
    redis_cache_default_ttl_seconds: int | None = None,
) -> CompiledStateGraph:
    """Create a deep agent.

    This agent will by default have access to a tool to write todos
    (write_todos), seven file and execution tools: ls, read_file, write_file,
    edit_file, glob, grep, execute, and a tool to call subagents.

    The execute tool allows running shell commands only when the supplied
    backend implements SandboxBackendProtocol. For non-sandbox backends, the
    execute tool returns an error message.

    Redis-backed cache/store construction is intentionally fail-closed in this
    package build because the Redis adapters are not present. Callers may pass
    explicit ``cache`` and ``store`` objects directly.

    Args:
        model: The model to use.
        tools: The tools the agent should have access to.
        system_prompt: Additional instructions for the agent.
        middleware: Additional middleware to apply after standard middleware.
        subagents: Subagents available to the main agent.
        response_format: A structured output response format to use for the agent.
        context_schema: The schema of the deep agent.
        checkpointer: Optional checkpointer for persisting agent state between runs.
        store: Optional store for persistent storage.
        use_longterm_memory: Whether to use long-term memory. Requires ``store``.
        backend: Optional backend for file storage and execution. Pass either a
            Backend instance or a callable factory like ``lambda rt: StateBackend(rt)``.
        interrupt_on: Optional mapping of tool names to interrupt configs.
        debug: Whether to enable debug mode. Passed through to create_agent.
        name: The name of the agent. Passed through to create_agent.
        cache: The cache to use for the agent. Passed through to create_agent.
        redis_settings: Reserved for future Redis-backed capabilities. Raises
            NotImplementedError when supplied until Redis adapters are restored.
        enable_redis_cache: Reserved for future Redis-backed cache construction.
        enable_redis_store: Reserved for future Redis-backed store construction.
        redis_cache_default_ttl_seconds: Reserved for future Redis cache TTLs.

    Returns:
        A configured deep agent.
    """
    _reject_unwired_options(
        redis_settings=redis_settings,
        enable_redis_cache=enable_redis_cache,
        enable_redis_store=enable_redis_store,
        redis_cache_default_ttl_seconds=redis_cache_default_ttl_seconds,
    )
    store_to_use = _resolve_store(store, use_longterm_memory)

    if model is None:
        model = get_default_model()

    if (
        hasattr(model, "profile")
        and model.profile is not None
        and isinstance(model.profile, dict)
        and "max_input_tokens" in model.profile
        and isinstance(model.profile["max_input_tokens"], int)
    ):
        trigger: tuple[str, float | int] = ("fraction", 0.85)
        keep: tuple[str, float | int] = ("fraction", 0.10)
    else:
        trigger = ("tokens", PROACTIVE_SUMMARY_THRESHOLD)
        keep = ("messages", DEFAULT_CONTEXT_MESSAGES_TO_KEEP)

    core_middleware_stack = _create_core_middleware(model, trigger, keep, backend=backend)

    subagent_middleware_stack: list[AgentMiddleware] = [
        *_create_core_middleware(model, trigger, keep, backend=backend),
    ]

    deepagent_middleware: list[AgentMiddleware] = [
        *core_middleware_stack,
        SubAgentMiddleware(
            default_model=model,
            default_tools=tools,
            subagents=subagents if subagents is not None else [],
            default_middleware=subagent_middleware_stack,
            default_interrupt_on=interrupt_on,
            general_purpose_agent=True,
        ),
    ]
    if interrupt_on is not None:
        deepagent_middleware.append(HumanInTheLoopMiddleware(interrupt_on=interrupt_on))
    if middleware is not None:
        deepagent_middleware.extend(middleware)

    return create_agent(
        model,
        system_prompt=system_prompt + "\n\n" + BASE_AGENT_PROMPT if system_prompt else BASE_AGENT_PROMPT,
        tools=tools,
        middleware=deepagent_middleware,
        response_format=response_format,
        context_schema=context_schema,
        checkpointer=checkpointer,
        store=store_to_use,
        debug=debug,
        name=name,
        cache=cache,
    ).with_config({"recursion_limit": 1000})
