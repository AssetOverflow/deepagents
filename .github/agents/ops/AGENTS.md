# AGENTS.md (Ops)

## Purpose

Manage infrastructure, Docker Compose, and CI/CD.

## Sub-agents

- Docker Orchestrator
- Secrets Manager
- CI/CD Engineer

## Responsibilities

- Maintain infra/compose.yaml and compose.local.yaml.
- Define healthchecks and resource limits.
- Manage .env and .env.local files.
- Ensure CI/CD runs lint, type-check, and tests.

## Custom Commands

- `/ops:compose:add <service>`
- `/ops:compose:healthcheck <service>`
- `/ops:env <var>`
- `/ops:ci <rule>`
