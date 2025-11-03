import os

# Templates for AGENTS.md files
ROOT_TEMPLATE = """# AGENTS.md

## Mission Build high-quality Python agentic systems with reproducible local environments, strong tests, safe secrets 
handling, and consistent review standards.

## Languages and stack
- Python 3.11+
- Agent frameworks: CrewAI / LangGraph / custom MCP tools
- Packaging: uv or pip, pyproject.toml
- Runtime: Docker Compose for local builds

## Coding standards
- Type hints everywhere; mypy strict modes for core libraries.
- Docstrings: Google style; public functions must have examples.
- Lint: ruff + black; enforce pre-commit.
- Structure: src/<package>, tests/, tools/, services/, infra/

## Testing
- Use pytest with coverage > 90% for core utilities and tools.
- Property-based tests for tool adapters (Hypothesis).
- Agent behaviors need scenario tests (deterministic tool stubs).

## Security and secrets
- Do not access real secrets in code. Use environment variables via .env.local.
- Access tokens must be read only through configuration providers.
- Never write secrets to logs; mask known keys.

## Documentation
- Update README and relevant docs with setup, run, and test steps.
- Each new tool must include a usage example and error modes.

## Tasks Copilot may perform
- Implement feature: write code + tests + docs; ensure lint/format pass.
- Create PR: include summary, risk analysis, test coverage report.
- Refactor: keep behavior identical; provide before/after rationale.
- Infra updates: update Compose and env docs; do not break local dev.

## Git etiquette
- Branch naming: feature/<slug>, fix/<slug>, chore/<slug>.
- Atomic commits with clear messages; link to issues if applicable.
- PR checklist: tests pass, coverage unchanged or improved, docs updated.
"""

AGENTS_TEMPLATE = """# AGENTS.md (agents/)

## Purpose Define agent orchestration patterns, tool contracts, and MCP integration. Keep agents composable, 
observable, and testable.

## Agent patterns
- Stateless planners + stateful executors (persist only task state).
- Tool adapters expose deterministic schemas and clear error codes.
- Subagents specialize: data ingest, retrieval, planning, execution.

## Tools registry requirements
- Each tool documented with: input schema, output schema, expected latency, idempotency notes, and example usage.
- Tools must implement retries with backoff and structured errors.

## Observability
- Logging with structlog; trace tool calls, durations, and result summaries.
- Redact sensitive fields; trace IDs propagated from request to tool.
"""

SERVICE_TEMPLATE = """# AGENTS.md (services/{name}/)

## Purpose Define API, env, and tests for this service. Copilot should only change code within this service unless 
explicitly instructed.

## API contracts
- Document request/response schemas; include example payloads.
- Strict versioning: bump minor for compatible changes; major for breaking.

## Configuration
- Read env via pydantic Settings; validate on startup.
- Fail fast if required env vars missing; never default to insecure values.

## Tests
- Unit tests for business logic; integration tests with mocked dependencies.
- Contract tests against shared schemas in /agents/contracts.
"""

INFRA_TEMPLATE = """# AGENTS.md (infra/)

## Purpose
Define how local environments are built and run, how secrets are handled, and how networking is designed.

## Docker Compose rules
- Use compose.yaml for base; compose.local.yaml overlays developer settings.
- Always include healthchecks and resource limits to prevent runaway containers.
- Standard networks: internal for services, public only for explicitly exposed ports.

## Environment files
- .env contains non-secret defaults; .env.local is developer-specific and gitignore(d).
- Secrets injected via docker secrets or env files outside VCS.
"""

GITHUB_TEMPLATE = """# AGENTS.md (.github/)

## Purpose
Define CI/CD etiquette, PR checks, labeling, and issue triage.

## CI/CD
- Run lint, type-check, and tests on every PR.
- Require coverage report and docs build.
- Auto-label PRs by branch prefix (feature/, fix/, chore/).
"""

EXAMPLES_TEMPLATE = """# AGENTS.md (examples/)

## Purpose
Define simplified rules for example apps and demos.

## Constraints
- Keep dependencies minimal.
- Provide clear README instructions.
- Use mock data instead of real services.
"""


def write_file(path, content):
    """
    Write content to a file, creating directories as needed.
    """
    dirpath = os.path.dirname(path)
    if dirpath:  # only create if not empty
        os.makedirs(dirpath, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"✅ Created {path}")


def main():
    print("🚀 Setting up AGENTS.md infrastructure for your project...\n")

    # Root AGENTS.md
    write_file("AGENTS.md", ROOT_TEMPLATE)

    # Agents directory
    write_file("agents/AGENTS.md", AGENTS_TEMPLATE)

    # Services (interactive)
    services = []
    while True:
        name = input("Enter a service name to scaffold (or press Enter to finish): ").strip()
        if not name:
            break
        services.append(name)
        write_file(f"services/{name}/AGENTS.md", SERVICE_TEMPLATE.format(name=name))

    # Infra
    write_file("infra/AGENTS.md", INFRA_TEMPLATE)

    # GitHub
    write_file(".github/AGENTS.md", GITHUB_TEMPLATE)

    # Examples
    write_file("examples/AGENTS.md", EXAMPLES_TEMPLATE)

    print("\n🎉 Done! Your AGENTS.md scaffolding is ready.")
    print("Next steps:")
    print("1. Review each AGENTS.md and customize details for your project.")
    print("2. Add Docker Compose files under infra/ and link them in infra/AGENTS.md.")
    print("3. Start coding agents in agents/ and services/ following the conventions.")


if __name__ == "__main__":
    main()
