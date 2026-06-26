import inspect

import pytest

import deepagents
from deepagents import graph as graph_module


def test_public_import_exposes_create_deep_agent():
    assert deepagents.create_deep_agent is graph_module.create_deep_agent


def test_create_deep_agent_signature_includes_readiness_parameters():
    signature = inspect.signature(deepagents.create_deep_agent)

    assert "backend" in signature.parameters
    assert "store" in signature.parameters
    assert "redis_settings" in signature.parameters


def test_create_deep_agent_wires_explicit_store_into_create_agent(monkeypatch):
    captured = {}
    explicit_store = object()

    class DummyGraph:
        def __init__(self):
            self.config = None

        def with_config(self, config):
            self.config = config
            return self

    class DummySubAgentMiddleware:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    def fake_create_agent(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return DummyGraph()

    monkeypatch.setattr(graph_module, "create_agent", fake_create_agent)
    monkeypatch.setattr(graph_module, "SubAgentMiddleware", DummySubAgentMiddleware)
    monkeypatch.setattr(graph_module, "_create_core_middleware", lambda model, trigger, keep: [])

    result = graph_module.create_deep_agent(
        model="test-model",
        tools=[],
        store=explicit_store,  # type: ignore[arg-type]
    )

    assert captured["args"] == ("test-model",)
    assert captured["kwargs"]["store"] is explicit_store
    assert captured["kwargs"]["tools"] == []
    assert result.config == {"recursion_limit": 1000}


def test_use_longterm_memory_without_store_raises_value_error():
    with pytest.raises(ValueError, match="store"):
        graph_module.create_deep_agent(
            model="test-model",
            tools=[],
            use_longterm_memory=True,
        )


def test_redis_settings_raise_not_implemented_error():
    with pytest.raises(NotImplementedError, match="Redis"):
        graph_module.create_deep_agent(
            model="test-model",
            tools=[],
            redis_settings="redis://localhost:6379/0",
        )


def test_backend_raises_not_implemented_error():
    with pytest.raises(NotImplementedError, match="Backend wiring"):
        graph_module.create_deep_agent(
            model="test-model",
            tools=[],
            backend=object(),  # type: ignore[arg-type]
        )


def test_enable_redis_store_false_is_allowed(monkeypatch):
    class DummySubAgentMiddleware:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class DummyGraph:
        def with_config(self, config):
            return self

    monkeypatch.setattr(graph_module, "create_agent", lambda *args, **kwargs: DummyGraph())
    monkeypatch.setattr(graph_module, "SubAgentMiddleware", DummySubAgentMiddleware)
    monkeypatch.setattr(graph_module, "_create_core_middleware", lambda model, trigger, keep: [])

    graph_module.create_deep_agent(
        model="anthropic:claude-sonnet-4-5",
        tools=[],
        enable_redis_store=False,
    )
