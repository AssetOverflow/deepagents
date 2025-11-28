"""Unit tests for graph.py middleware factory and configuration."""

from collections.abc import Callable, Sequence
from typing import Any

from langchain.agents.middleware import TodoListMiddleware
from langchain.agents.middleware.summarization import SummarizationMiddleware
from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
from langchain_core.language_models import LanguageModelInput
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool

from deepagents.graph import (
    DEFAULT_CONTEXT_MESSAGES_TO_KEEP,
    PROACTIVE_SUMMARY_THRESHOLD,
    _create_core_middleware,
)
from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware

EXPECTED_PROACTIVE_SUMMARY_THRESHOLD = 45000
EXPECTED_DEFAULT_CONTEXT_MESSAGES_TO_KEEP = 6
EXPECTED_CORE_MIDDLEWARE_COUNT = 5


class FixedGenericFakeChatModel(GenericFakeChatModel):
    """Fixed version of GenericFakeChatModel that properly handles bind_tools."""

    def bind_tools(
        self,
        _tools: Sequence[dict[str, Any] | type | Callable | BaseTool],
        *,
        _tool_choice: str | None = None,
        **_kwargs: Any,
    ) -> Runnable[LanguageModelInput, AIMessage]:
        """Override bind_tools to return self."""
        return self


class TestContextManagementConstants:
    """Tests for context management constants."""

    def test_proactive_summary_threshold_value(self) -> None:
        """Test that PROACTIVE_SUMMARY_THRESHOLD is set to 45000."""
        assert PROACTIVE_SUMMARY_THRESHOLD == EXPECTED_PROACTIVE_SUMMARY_THRESHOLD

    def test_default_context_messages_to_keep_value(self) -> None:
        """Test that DEFAULT_CONTEXT_MESSAGES_TO_KEEP is set to 6."""
        assert DEFAULT_CONTEXT_MESSAGES_TO_KEEP == EXPECTED_DEFAULT_CONTEXT_MESSAGES_TO_KEEP


class TestCreateCoreMiddleware:
    """Tests for _create_core_middleware factory function."""

    def test_returns_list_of_middleware(self) -> None:
        """Test that _create_core_middleware returns a list of middleware."""
        model = FixedGenericFakeChatModel(messages=iter([]))
        middleware = _create_core_middleware(model)
        assert isinstance(middleware, list)
        assert len(middleware) == EXPECTED_CORE_MIDDLEWARE_COUNT

    def test_contains_todo_list_middleware(self) -> None:
        """Test that the core middleware stack includes TodoListMiddleware."""
        model = FixedGenericFakeChatModel(messages=iter([]))
        middleware = _create_core_middleware(model)
        assert isinstance(middleware[0], TodoListMiddleware)

    def test_contains_filesystem_middleware(self) -> None:
        """Test that the core middleware stack includes FilesystemMiddleware."""
        model = FixedGenericFakeChatModel(messages=iter([]))
        middleware = _create_core_middleware(model)
        assert isinstance(middleware[1], FilesystemMiddleware)

    def test_contains_summarization_middleware(self) -> None:
        """Test that the core middleware stack includes SummarizationMiddleware."""
        model = FixedGenericFakeChatModel(messages=iter([]))
        middleware = _create_core_middleware(model)
        assert isinstance(middleware[2], SummarizationMiddleware)

    def test_contains_anthropic_caching_middleware(self) -> None:
        """Test that the core middleware stack includes AnthropicPromptCachingMiddleware."""
        model = FixedGenericFakeChatModel(messages=iter([]))
        middleware = _create_core_middleware(model)
        assert isinstance(middleware[3], AnthropicPromptCachingMiddleware)

    def test_contains_patch_tool_calls_middleware(self) -> None:
        """Test that the core middleware stack includes PatchToolCallsMiddleware."""
        model = FixedGenericFakeChatModel(messages=iter([]))
        middleware = _create_core_middleware(model)
        assert isinstance(middleware[4], PatchToolCallsMiddleware)

    def test_summarization_uses_proactive_threshold(self) -> None:
        """Test that SummarizationMiddleware uses the proactive threshold."""
        model = FixedGenericFakeChatModel(messages=iter([]))
        middleware = _create_core_middleware(model)
        summarization = middleware[2]
        assert isinstance(summarization, SummarizationMiddleware)
        # Check that trigger is configured with the proactive threshold
        assert summarization.trigger == ("tokens", PROACTIVE_SUMMARY_THRESHOLD)

    def test_summarization_uses_default_messages_to_keep(self) -> None:
        """Test that SummarizationMiddleware uses the default messages to keep."""
        model = FixedGenericFakeChatModel(messages=iter([]))
        middleware = _create_core_middleware(model)
        summarization = middleware[2]
        assert isinstance(summarization, SummarizationMiddleware)
        # Check that keep is configured with the default messages to keep
        assert summarization.keep == ("messages", DEFAULT_CONTEXT_MESSAGES_TO_KEEP)

    def test_middleware_order_is_consistent(self) -> None:
        """Test that middleware order is consistent across multiple calls."""
        model = FixedGenericFakeChatModel(messages=iter([]))

        middleware1 = _create_core_middleware(model)
        middleware2 = _create_core_middleware(model)

        # Verify both have same types in same order
        for m1, m2 in zip(middleware1, middleware2, strict=True):
            assert type(m1) is type(m2)
