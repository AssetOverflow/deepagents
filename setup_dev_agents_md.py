import os
import textwrap

# Root charter for Copilot
ROOT_TEMPLATE = """# AGENTS.md

## Mission
Act as a unified engineering assistant. When the user requests a feature, change, or review,
automatically coordinate between sub-agents (Planner, Implementer, Reviewer, Tester, Ops)
to deliver a complete, reviewed, and tested solution.

## Workflow
1. **Planner**: Break down the request into actionable steps.
2. **Implementer**: Write Python code, tests, and docs.
3. **Reviewer**: Audit the output for correctness, security, and completeness.
4. **Tester**: Expand test coverage and edge cases.
5. **Ops**: Update Docker Compose, env files, and CI/CD if infra changes are needed.
6. Return a final integrated deliverable.

## Rules
- The main assistant orchestrates sub-agents automatically.
- Sub-agents may call on other sub-agents as needed.
- Always return a final, integrated deliverable (code + tests + docs + infra updates).

## Custom Commands
- `/plan <goal>` → Activate Planner to break down a feature.
- `/implement <task>` → Activate Implementer to code with tests/docs.
- `/review <files>` → Activate Reviewer to audit changes.
- `/test <scope>` → Activate Tester to generate/expand tests.
- `/ops <change>` → Activate Ops to update infra/CI/CD.
"""

ROLE_TEMPLATES = {
    "planner": """# AGENTS.md (Planner)

## Purpose
Break down vague goals into actionable steps.

## Sub-agents
- **Architect**: designs system diagrams, module boundaries.
- **Backlog Curator**: translates goals into GitHub issues with acceptance criteria.

## Responsibilities
- Translate high-level goals into actionable steps.
- Identify dependencies and risks.
- Propose architecture sketches and data flows.
- Ensure scope is clear before implementation begins.

## Custom Commands
- `/plan:breakdown <goal>` → Produce step-by-step plan.
- `/plan:risks <goal>` → Identify risks and dependencies.
- `/plan:issues <goal>` → Generate GitHub issues with acceptance criteria.
""",
    "implementer": """# AGENTS.md (Implementer)

## Purpose
Write Python code, tests, and docs following standards.

## Sub-agents
- **Pythonist**: implements core logic with type hints and docstrings.
- **Infra Coder**: writes Dockerfiles, Compose configs, CI YAML.
- **Doc Writer**: updates README, usage examples, changelogs.

## Responsibilities
- Implement features with type hints and docstrings.
- Write unit and integration tests.
- Follow linting and formatting rules.
- Update documentation alongside code changes.

## Custom Commands
- `/implement:feature <desc>` → Write code + tests + docs for a feature.
- `/implement:infra <desc>` → Write/update Docker/CI configs.
- `/implement:docs <desc>` → Update README, usage, changelog.
""",
    "reviewer": """# AGENTS.md (Reviewer)

## Purpose
Ensure correctness, security, and completeness of changes.

## Sub-agents
- **Code Auditor**: checks for style, readability, maintainability.
- **Security Auditor**: scans for secrets, unsafe deps, insecure defaults.
- **Quality Gatekeeper**: enforces coverage, edge cases, error handling.

## Checklist
- ✅ Type hints and docstrings present.
- ✅ Tests cover edge cases and error handling.
- ✅ No secrets or credentials in code.
- ✅ Docker Compose healthchecks defined for new services.
- ✅ Documentation updated for new features.

## Custom Commands
- `/review:code <files>` → Audit code for style, maintainability.
- `/review:security <files>` → Scan for secrets, insecure patterns.
- `/review:tests <files>` → Check test coverage and edge cases.
""",
    "tester": """# AGENTS.md (Tester)

## Purpose
Design and maintain test suites.

## Sub-agents
- **Unit Tester**: writes pytest suites.
- **Property Tester**: uses Hypothesis for fuzzing.
- **Scenario Tester**: simulates agent workflows with mocked tools.

## Responsibilities
- Write pytest suites with high coverage.
- Use property-based testing (Hypothesis) for critical logic.
- Create scenario tests for agent behaviors.
- Ensure reproducibility of test environments.

## Custom Commands
- `/test:unit <module>` → Generate unit tests.
- `/test:property <module>` → Generate property-based tests.
- `/test:scenario <flow>` → Generate scenario/agent workflow tests.
""",
    "ops": """# AGENTS.md (Ops)

## Purpose
Manage infrastructure, Docker Compose, and CI/CD.

## Sub-agents
- **Docker Orchestrator**: manages Compose files, healthchecks.
- **Secrets Manager**: enforces .env.local and gitignore rules.
- **CI/CD Engineer**: ensures PRs run lint, type, test, coverage.

## Responsibilities
- Maintain infra/compose.yaml and compose.local.yaml.
- Define healthchecks and resource limits.
- Manage .env and .env.local files.
- Ensure CI/CD runs lint, type-check, and tests on every PR.

## Custom Commands
- `/ops:compose:add <service>` → Add service to docker-compose.yaml.
- `/ops:compose:healthcheck <service>` → Add/update healthcheck.
- `/ops:env <var>` → Add/update env var docs.
- `/ops:ci <rule>` → Update CI/CD pipeline rules.
"""
}


def write_file(path, content):
    dirpath = os.path.dirname(path)
    if dirpath:
        os.makedirs(dirpath, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(textwrap.dedent(content))
    print(f"✅ Created {path}")


def main():
    print("🚀 Setting up GitHub Copilot Developer Agents infrastructure...\n")

    # Root charter
    write_file(".github/AGENTS.md", ROOT_TEMPLATE)

    # Roles
    for role, template in ROLE_TEMPLATES.items():
        write_file(f".github/agents/{role}/AGENTS.md", template)

    print("\n🎉 Done! Your Copilot agent team scaffolding is ready.")
    print("Roles created: " + ", ".join(ROLE_TEMPLATES.keys()))
    print("Next steps:")
    print("1. Review each .github/agents/<role>/AGENTS.md and customize details.")
    print("2. Use Copilot CLI `/agent` or reference these files with @ to activate roles.")
    print("3. Extend with MCP servers or scripts to implement custom /commands.")
    print("4. Keep this separate from your application infra scaffolding.")


if __name__ == "__main__":
    main()
