# Local Development Stack (Deephaven + MCP + Redis)

This guide explains how to launch a fully local environment for developing and testing DeepAgents with:

- Deephaven Community Core (`deephaven` container)
- Deephaven MCP Systems Server (`mcp-systems` container)
- Redis (cache + store integration)

## Prerequisites

- Docker + Docker Compose v2 (`docker compose version`)
- Python 3.11+ with `uv` (recommended) already used to install project dependencies

## One-Time Bootstrap

```bash
python scripts/setup_local_stack.py --random-psk
```

Creates directory layout:
```
local/
  deephaven/
    data/
    cache/
  mcp/
    config/deephaven_mcp.json
  redis/
    data/
  secrets/
    psk.txt
```

`deephaven_mcp.json` example (generated):
```json
{
  "community": {
    "sessions": {
      "local": {
        "host": "deephaven",
        "port": 10000,
        "auth_type": "io.deephaven.authentication.psk.PskAuthenticationHandler",
        "auth_token": "${DEEPHAVEN_PSK}"
      }
    }
  }
}
```

## Recommended Workflow (PowerShell)

Most convenient (persistent via .env):

```powershell
python scripts/setup_local_stack.py --random-psk --write-env
# .env now contains DEEPHAVEN_PSK
docker compose up --build -d
```

One-off (session only):

```powershell
python scripts/setup_local_stack.py --random-psk
$Env:DEEPHAVEN_PSK = (Get-Content -Raw .\local\secrets\psk.txt).Trim()
docker compose up --build -d
```

Inline one-liner:
```powershell
$Env:DEEPHAVEN_PSK = (Get-Content -Raw .\local\secrets\psk.txt).Trim(); docker compose up -d
```

Regenerate / rotate secret:
```powershell
python scripts/setup_local_stack.py --force --random-psk --write-env
docker compose up -d --force-recreate
```

(For Git Bash / WSL):
```bash
python scripts/setup_local_stack.py --random-psk --write-env
source .env
docker compose up --build -d
```

## Start the Stack

```bash
docker compose up --build -d
```

Monitor logs:
```bash
docker compose logs -f deephaven
# In another terminal
docker compose logs -f mcp-systems
```

Health:
- Deephaven UI: http://localhost:10000/ide/
- Redis CLI: `docker exec -it redis redis-cli ping`

## Environment Variables

You can override the default PSK at runtime:
```bash
export DEEPHAVEN_PSK=$(cat local/secrets/psk.txt)
docker compose up -d
```

## Using in DeepAgents

Inside your Python session, enable Deephaven MCP tools:
```python
from deepagents import create_deep_agent

agent = create_deep_agent(
    enable_deephaven_mcp=True,
    deephaven_mcp_settings={"url": "stdio://mcp-systems"},  # future enhancement: stdio proxy
    tools=[]
)
```

Note: Current stub client does not yet establish a real MCP protocol session—replace with real client implementation for end-to-end validation.

## Tear Down

```bash
docker compose down -v
```

## Regenerate Config / Rotate PSK

```bash
python scripts/setup_local_stack.py --force --random-psk
export DEEPHAVEN_PSK=$(cat local/secrets/psk.txt)
docker compose up -d --force-recreate
```

## Next Steps

- Implement real MCP protocol client in `deepagents.integrations.deephaven_mcp`
- Add integration test that shells into `mcp-systems` container or uses a stdio wrapper
- Add subscription test harness
