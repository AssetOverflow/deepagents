# TODO: Unified Configuration Architecture
**Priority:** P0 - Critical  
**Workstream:** WS2 - Unified Configuration Architecture  
**Status:** 🟡 Not Started  
**Blocks:** WS3, WS4

---

## Objective

Create a unified configuration system that seamlessly integrates Redis, Deephaven, and core DeepAgents settings into a cohesive, easy-to-use API.

---

## Current State Analysis

### Existing Config Files:
1. **`src/deepagents/config/__init__.py`** - Deephaven-specific settings
   - `DeephavenSettings`
   - `DeephavenAuthSettings`
   - `DeephavenTableSettings`
   
2. **`src/deepagents/redis/settings.py`** - Redis-specific settings
   - `RedisSettings` (connection, pool, timeouts)

3. **`src/deepagents/graph.py`** - Agent creation with scattered config params
   - Individual parameters: `redis_settings`, `enable_redis_cache`, etc.

### Problems:
- ❌ No single source of truth for configuration
- ❌ Unclear precedence rules (env vars, files, defaults)
- ❌ No validation of interdependencies
- ❌ Hard to configure both Redis + Deephaven simultaneously
- ❌ No workspace/namespace isolation

---

## Design Proposal

### Configuration Hierarchy

```python
@dataclass
class AgentSystemConfig:
    """Unified configuration for all DeepAgents components."""
    
    # Core settings
    workspace: str = "default"
    environment: str = "development"  # development, staging, production
    
    # Redis configuration
    redis: RedisConfig | None = None
    enable_redis_cache: bool = False
    enable_redis_store: bool = False
    redis_cache_ttl_seconds: int = 3600
    
    # Deephaven configuration
    deephaven: DeephavenConfig | None = None
    enable_deephaven_telemetry: bool = False
    enable_deephaven_transport: bool = False
    
    # Feature flags
    features: FeatureFlags = field(default_factory=FeatureFlags)
    
    # Observability
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    
    @classmethod
    def from_env(cls) -> "AgentSystemConfig":
        """Load configuration from environment variables."""
        
    @classmethod
    def from_file(cls, path: Path) -> "AgentSystemConfig":
        """Load configuration from YAML/JSON file."""
        
    @classmethod
    def from_dict(cls, data: dict) -> "AgentSystemConfig":
        """Load configuration from dictionary."""
        
    def validate(self) -> list[str]:
        """Validate configuration and return list of errors."""
        
    def merge(self, other: "AgentSystemConfig") -> "AgentSystemConfig":
        """Merge two configs with other taking precedence."""
```

### Configuration Sources (Precedence Order)

1. **Explicit Parameters** - Passed to `create_deep_agent()`
2. **Environment Variables** - `DEEPAGENTS_*` prefix
3. **Config File** - `~/.deepagents/config.yaml` or `./deepagents.yaml`
4. **Defaults** - Sensible defaults for development

### Environment Variable Mapping

```
DEEPAGENTS_WORKSPACE=my_workspace
DEEPAGENTS_ENVIRONMENT=production

DEEPAGENTS_REDIS_URL=redis://localhost:6379/0
DEEPAGENTS_REDIS_ENABLE_CACHE=true
DEEPAGENTS_REDIS_ENABLE_STORE=true
DEEPAGENTS_REDIS_CACHE_TTL=3600

DEEPAGENTS_DEEPHAVEN_HOST=localhost
DEEPAGENTS_DEEPHAVEN_PORT=10000
DEEPAGENTS_DEEPHAVEN_USE_HTTPS=false
DEEPAGENTS_DEEPHAVEN_ENABLE_TELEMETRY=true
DEEPAGENTS_DEEPHAVEN_ENABLE_TRANSPORT=false

DEEPAGENTS_LOG_LEVEL=INFO
DEEPAGENTS_LOG_FORMAT=json
```

### Config File Format (YAML)

```yaml
# deepagents.yaml
workspace: my_workspace
environment: production

redis:
  url: redis://localhost:6379/0
  pool_size: 10
  timeout_seconds: 5
  enable_cache: true
  enable_store: true
  cache_ttl_seconds: 3600

deephaven:
  host: localhost
  port: 10000
  use_https: false
  auth:
    type: psk  # or username_password
    token: ${DEEPHAVEN_TOKEN}
  tables:
    events: agent_events
    metrics: agent_metrics
    messages: agent_messages
  enable_telemetry: true
  enable_transport: false

features:
  long_term_memory: true
  subagents: true
  filesystem: true
  interrupts: true

logging:
  level: INFO
  format: json
  output: stdout

metrics:
  enabled: true
  provider: prometheus
  port: 9090
```

---

## Implementation Tasks

### TASK-101: Create Core Config Classes
- [ ] Create `deepagents/config/core.py` with `AgentSystemConfig`
- [ ] Create `deepagents/config/redis_config.py` with `RedisConfig`
- [ ] Create `deepagents/config/deephaven_config.py` with `DeephavenConfig`
- [ ] Create `deepagents/config/feature_flags.py` with `FeatureFlags`
- [ ] Create `deepagents/config/logging_config.py` with `LoggingConfig`
- [ ] Create `deepagents/config/metrics_config.py` with `MetricsConfig`
- [ ] Add comprehensive docstrings and type hints

### TASK-102: Implement Config Loaders
- [ ] Implement `from_env()` class method
  - Parse all `DEEPAGENTS_*` environment variables
  - Handle nested config (e.g., `DEEPAGENTS_REDIS_URL`)
  - Type coercion (bool, int, etc.)
- [ ] Implement `from_file()` class method
  - Support YAML format (via `pyyaml`)
  - Support JSON format
  - Support environment variable substitution (e.g., `${VAR}`)
- [ ] Implement `from_dict()` class method
  - Nested dictionary parsing
  - Type validation
- [ ] Implement config merging logic
  - Deep merge strategy for nested configs
  - Explicit override semantics

### TASK-103: Add Validation Logic
- [ ] Implement `validate()` method
  - Check Redis URL format if Redis enabled
  - Check Deephaven host/port if Deephaven enabled
  - Check interdependencies (e.g., cache requires Redis)
  - Return user-friendly error messages
- [ ] Add validation decorators for individual fields
- [ ] Add custom validators for complex rules

### TASK-104: Wire Into `create_deep_agent()`
- [ ] Update `create_deep_agent()` signature:
  ```python
  def create_deep_agent(
      model: ...,
      tools: ...,
      *,
      config: AgentSystemConfig | None = None,
      # Legacy params for backward compatibility
      redis_settings: RedisSettings | str | None = None,
      enable_redis_cache: bool = False,
      ...
  ) -> CompiledStateGraph:
  ```
- [ ] Add backward compatibility shim
  - Convert legacy params to `AgentSystemConfig`
  - Emit deprecation warnings
- [ ] Auto-initialize services based on config
  - Create Redis client if `config.redis` provided
  - Create Deephaven session if `config.deephaven` provided
  - Pass config to all middleware

### TASK-105: Add CLI Support
- [ ] Create `deepagents config validate` command
- [ ] Create `deepagents config show` command (with secrets masked)
- [ ] Create `deepagents config init` wizard
  - Interactive prompts for common setups
  - Generate config file
- [ ] Add `--config` flag to all CLI commands

### TASK-106: Write Tests
- [ ] Unit tests for each config class
- [ ] Tests for env variable parsing
- [ ] Tests for file loading (YAML/JSON)
- [ ] Tests for validation logic
- [ ] Tests for merging logic
- [ ] Integration tests with `create_deep_agent()`

### TASK-107: Documentation
- [ ] Configuration guide with all options documented
- [ ] Environment variable reference
- [ ] Config file examples for common scenarios:
  - Local development
  - Redis-only deployment
  - Deephaven-only deployment
  - Full-stack deployment
- [ ] Migration guide from old to new config API
- [ ] Troubleshooting guide for common config errors

---

## Example Usage

### Simple (All Defaults)
```python
from deepagents import create_deep_agent

agent = create_deep_agent(
    model="claude-sonnet-4",
    tools=[...]
)
```

### With Config Object
```python
from deepagents import create_deep_agent, AgentSystemConfig
from deepagents.config import RedisConfig, DeephavenConfig

config = AgentSystemConfig(
    workspace="my_project",
    redis=RedisConfig(
        url="redis://localhost:6379/0",
        enable_cache=True,
        enable_store=True
    ),
    deephaven=DeephavenConfig(
        host="localhost",
        port=10000,
        enable_telemetry=True
    )
)

agent = create_deep_agent(
    model="claude-sonnet-4",
    tools=[...],
    config=config
)
```

### With Config File
```python
from deepagents import create_deep_agent, AgentSystemConfig

config = AgentSystemConfig.from_file("./deepagents.yaml")
agent = create_deep_agent(
    model="claude-sonnet-4",
    tools=[...],
    config=config
)
```

### With Environment Variables
```python
import os
from deepagents import create_deep_agent, AgentSystemConfig

# Set env vars
os.environ["DEEPAGENTS_REDIS_URL"] = "redis://localhost:6379/0"
os.environ["DEEPAGENTS_REDIS_ENABLE_CACHE"] = "true"

config = AgentSystemConfig.from_env()
agent = create_deep_agent(
    model="claude-sonnet-4",
    tools=[...],
    config=config
)
```

---

## Testing Checklist

- [ ] Config loads from environment variables correctly
- [ ] Config loads from YAML file correctly
- [ ] Config loads from JSON file correctly
- [ ] Environment variable substitution works (e.g., `${TOKEN}`)
- [ ] Config merging works (env > file > defaults)
- [ ] Validation catches invalid Redis URLs
- [ ] Validation catches missing required fields
- [ ] Backward compatibility with old API works
- [ ] Deprecation warnings are emitted
- [ ] Config serialization works (for debugging)
- [ ] Secrets are masked in string representation

---

## Success Criteria

✅ Single `AgentSystemConfig` class for all configuration  
✅ Clear precedence rules documented and tested  
✅ Zero-config development experience (sensible defaults)  
✅ Production-ready config templates provided  
✅ All existing tests pass with new config system  
✅ Documentation is comprehensive and clear  
✅ Migration guide helps users upgrade from 0.2.x  

---

**Created:** 2025-11-02  
**Assigned:** Unassigned  
**Due:** 2025-11-04  
**Estimated Effort:** 2 days

