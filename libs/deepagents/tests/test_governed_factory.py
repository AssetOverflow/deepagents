from pathlib import Path
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware

import deepagents.governed as governed
from deepagents.backends import ReadOnlyFilesystemBackend
from deepagents.middleware import AuditEventMiddleware, MemoryPolicyMiddleware, SubAgentMiddleware, ToolPolicyMiddleware


class FakeCompiledGraph:
    def __init__(self) -> None:
        self.config: dict[str, Any] | None = None

    def with_config(self, config: dict[str, Any]) -> "FakeCompiledGraph":
        self.config = config
        return self


def test_governed_factory_wires_default_stack(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, Any] = {}

    def fake_create_agent(*args: Any, **kwargs: Any) -> FakeCompiledGraph:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeCompiledGraph()

    monkeypatch.setattr(governed, "create_agent", fake_create_agent)

    graph = governed.create_governed_deep_agent(model="fake-model", root_dir=tmp_path)

    assert isinstance(graph, FakeCompiledGraph)
    assert graph.config == {"recursion_limit": 1000}
    assert captured["args"][0] == "fake-model"
    middleware = captured["kwargs"]["middleware"]
    assert any(isinstance(item, ToolPolicyMiddleware) for item in middleware)
    assert any(isinstance(item, MemoryPolicyMiddleware) for item in middleware)
    assert not any(isinstance(item, AuditEventMiddleware) for item in middleware)

    subagent_middleware = next(item for item in middleware if isinstance(item, SubAgentMiddleware))
    assert "proposal_only" in subagent_middleware.tools[0].description

    tool_policy = next(item for item in middleware if isinstance(item, ToolPolicyMiddleware))
    assert tool_policy.allow_tools == governed.DEFAULT_GOVERNED_ALLOW_TOOLS
    assert tool_policy.deny_by_default is True

    memory_policy = next(item for item in middleware if isinstance(item, MemoryPolicyMiddleware))
    assert memory_policy.mode == "proposal_only"


def test_governed_factory_uses_read_only_backend_for_core_and_subagents(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, Any] = {}

    def fake_create_agent(*args: Any, **kwargs: Any) -> FakeCompiledGraph:
        captured["kwargs"] = kwargs
        return FakeCompiledGraph()

    monkeypatch.setattr(governed, "create_agent", fake_create_agent)

    governed.create_governed_deep_agent(model="fake-model", root_dir=tmp_path)

    middleware = captured["kwargs"]["middleware"]
    filesystem_middlewares = [item for item in middleware if item.__class__.__name__ == "FilesystemMiddleware"]
    assert filesystem_middlewares
    for item in filesystem_middlewares:
        assert isinstance(item.backend, ReadOnlyFilesystemBackend)

    subagent_middleware = next(item for item in middleware if isinstance(item, SubAgentMiddleware))
    subagent_filesystem_middlewares = [item for item in subagent_middleware.tools[0].metadata.get("default_middleware", []) if item.__class__.__name__ == "FilesystemMiddleware"]
    assert subagent_filesystem_middlewares == []


def test_governed_factory_accepts_overrides(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, Any] = {}
    extra_middleware = AgentMiddleware()
    audit_events: list[Any] = []

    def fake_create_agent(*args: Any, **kwargs: Any) -> FakeCompiledGraph:
        captured["kwargs"] = kwargs
        return FakeCompiledGraph()

    monkeypatch.setattr(governed, "create_agent", fake_create_agent)

    governed.create_governed_deep_agent(
        model="fake-model",
        root_dir=tmp_path,
        system_prompt="custom",
        allow_tools={"read_file"},
        deny_tools={"task"},
        memory_mode="disabled",
        memory_prefixes=("/profile/",),
        subagent_result_mode="trusted",
        audit_sink=audit_events.append,
        middleware=[extra_middleware],
        name="governed",
    )

    kwargs = captured["kwargs"]
    assert kwargs["name"] == "governed"
    assert kwargs["system_prompt"].startswith("custom\n\n")
    middleware = kwargs["middleware"]
    assert middleware[-1] is extra_middleware
    assert any(isinstance(item, AuditEventMiddleware) for item in middleware)

    tool_policy = next(item for item in middleware if isinstance(item, ToolPolicyMiddleware))
    assert tool_policy.allow_tools == frozenset({"read_file"})
    assert tool_policy.deny_tools == frozenset({"task"})

    memory_policy = next(item for item in middleware if isinstance(item, MemoryPolicyMiddleware))
    assert memory_policy.mode == "disabled"
    assert memory_policy.memory_prefixes == ("/profile/",)

    subagent_middleware = next(item for item in middleware if isinstance(item, SubAgentMiddleware))
    assert "proposal_only" not in subagent_middleware.tools[0].description
