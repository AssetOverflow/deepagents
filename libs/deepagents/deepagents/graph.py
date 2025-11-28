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

from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
from deepagents.middleware.subagents import CompiledSubAgent, SubAgent, SubAgentMiddleware
from deepagents.redis import RedisCache, RedisSettings, RedisStore, create_redis_client

BASE_AGENT_PROMPT = "In order to complete the objective that the user asks of you, you have access to a number of standard tools."

# Proactive summarization threshold for cost/performance efficiency.
# This triggers summarization earlier than the model's context limit to keep prompts lean.
PROACTIVE_SUMMARY_THRESHOLD = 45000

# Default number of recent messages to keep after summarization.
DEFAULT_CONTEXT_MESSAGES_TO_KEEP = 6


def _create_core_middleware(
    model: str | BaseChatModel,
    trigger: tuple[str, float | int],
    keep: tuple[str, float | int],
) -> list[AgentMiddleware]:
    """Factory function for reusable, core middleware components.

    These are middleware that should be consistently applied across both
    the main agent and subagents for uniform context management.

    Args:
        model: The language model to use for summarization.
        trigger: Tuple of (mode, threshold) for when to trigger summarization.
            Mode is either "fraction" or "tokens".
        keep: Tuple of (mode, count) for how many messages to keep.
            Mode is either "fraction" or "messages".

    Returns:
        List of core middleware instances for summarization, caching, and tool patching.
    """
    return [
        SummarizationMiddleware(
            model=model,
            trigger=trigger,  # type: ignore[arg-type]
            keep=keep,  # type: ignore[arg-type]
            trim_tokens_to_summarize=None,
        ),
        AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore"),
        PatchToolCallsMiddleware(),
    ]


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
    backend: BackendProtocol | BackendFactory | None = None,
) -> list[AgentMiddleware]:
    """Create the core, reusable middleware stack for agents.

    This factory function creates a consistent middleware configuration that can be
    shared between the main agent and subagents. It includes:
    - TodoListMiddleware for task planning and progress tracking
    - FilesystemMiddleware for file operations
    - SummarizationMiddleware with proactive summarization threshold
    - AnthropicPromptCachingMiddleware for caching system prompts
    - PatchToolCallsMiddleware for fixing dangling tool calls

    Args:
        model: The language model to use for summarization.
        backend: Optional backend for file storage and execution.

    Returns:
        A list of configured AgentMiddleware instances.
    """
    return [
        TodoListMiddleware(),
        FilesystemMiddleware(backend=backend),
        SummarizationMiddleware(
            model=model,
            trigger=("tokens", PROACTIVE_SUMMARY_THRESHOLD),
            keep=("messages", DEFAULT_CONTEXT_MESSAGES_TO_KEEP),
            trim_tokens_to_summarize=None,
        ),
        AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore"),
        PatchToolCallsMiddleware(),
    ]


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
    interrupt_on: dict[str, bool | InterruptOnConfig] | None = None,
    debug: bool = False,
    name: str | None = None,
    cache: BaseCache | None = None,
    redis_settings: RedisSettings | str | None = None,
    enable_redis_cache: bool = False,
    enable_redis_store: bool | None = None,
    redis_cache_default_ttl_seconds: int | None = None,
) -> CompiledStateGraph:
    """Create a deep agent.

    This agent will by default have access to a tool to write todos (write_todos),
    seven file and execution tools: ls, read_file, write_file, edit_file, glob, grep, execute,
    and a tool to call subagents.

    The execute tool allows running shell commands if the backend implements SandboxBackendProtocol.
    For non-sandbox backends, the execute tool will return an error message.

    Redis integration is optional and configured via ``redis_settings``.  When
    provided, callers can opt into Redis-backed caching and/or the Redis-backed
    long-term store without manually instantiating the adapters.

    Args:
        tools: The tools the agent should have access to.
        system_prompt: The additional instructions the agent should have. Will go in
            the system prompt.
        middleware: Additional middleware to apply after standard middleware.
        model: The model to use.
        subagents: The subagents to use. Each subagent should be a dictionary with the
            following keys:
                - `name`
                - `description` (used by the main agent to decide whether to call the
                  sub agent)
                - `prompt` (used as the system prompt in the subagent)
                - (optional) `tools`
                - (optional) `model` (either a LanguageModelLike instance or dict
                  settings)
                - (optional) `middleware` (list of AgentMiddleware)
        response_format: A structured output response format to use for the agent.
        context_schema: The schema of the deep agent.
        checkpointer: Optional checkpointer for persisting agent state between runs.
        store: Optional store for persistent storage (required if backend uses StoreBackend).
        use_longterm_memory: Whether to use longterm memory - you must provide a store
            in order to use longterm memory.
        backend: Optional backend for file storage and execution. Pass either a Backend instance
            or a callable factory like `lambda rt: StateBackend(rt)`. For execution support,
            use a backend that implements SandboxBackendProtocol.
        interrupt_on: Optional Dict[str, bool | InterruptOnConfig] mapping tool names to
            interrupt configs.
        debug: Whether to enable debug mode. Passed through to create_agent.
        name: The name of the agent. Passed through to create_agent.
        cache: The cache to use for the agent. Passed through to create_agent.
        redis_settings: Connection settings or URL for Redis-backed capabilities.
            When a string is supplied it is interpreted as a Redis connection URL;
            otherwise provide an instance of :class:`~deepagents.redis.RedisSettings`.
        enable_redis_cache: Whether to automatically configure a Redis cache when
            ``redis_settings`` are provided and ``cache`` is not supplied.
        enable_redis_store: Whether to create a Redis-backed store when
            ``redis_settings`` are provided and ``store`` is not supplied. Defaults
            to ``use_longterm_memory`` when ``None``.
        redis_cache_default_ttl_seconds: Default TTL in seconds for Redis cache
            entries when a TTL is not specified by the caller.

    Returns:
        A configured deep agent.
    """
    if model is None:
        model = get_default_model()

    # Determine summarization trigger and keep settings
    # Use proactive threshold for token-based triggering
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
        # Use proactive summarization threshold for early context management
        trigger = ("tokens", PROACTIVE_SUMMARY_THRESHOLD)
        keep = ("messages", DEFAULT_CONTEXT_MESSAGES_TO_KEEP)

    # Create the core, reusable middleware stack for summarization/caching/patching
    core_middleware_stack = _create_core_middleware(model, trigger, keep)

    # Build the default middleware stack for subagents
    # Subagents get TodoList + Filesystem + core stack for consistent context management
    subagent_middleware_stack: list[AgentMiddleware] = [
        TodoListMiddleware(),
        FilesystemMiddleware(backend=backend),
        *core_middleware_stack,
    ]

    deepagent_middleware: list[AgentMiddleware] = [
        TodoListMiddleware(),
        FilesystemMiddleware(backend=backend),
        SubAgentMiddleware(
            default_model=model,
            default_tools=tools,
            subagents=subagents if subagents is not None else [],
            default_middleware=subagent_middleware_stack,
            default_interrupt_on=interrupt_on,
            general_purpose_agent=True,
        ),
        *core_middleware_stack,  # Include Summarization, Caching, Patching for main agent
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
