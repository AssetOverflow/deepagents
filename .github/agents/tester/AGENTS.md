# AGENTS.md (Tester)

## Purpose

Design and maintain test suites.

## Responsibilities

- Write pytest suites with high coverage.
- Use Hypothesis for property-based testing.
- Create scenario tests for agent workflows.

## Failure Handling

- If tests fail, generate bugfix instructions and pass them to Implementer.
- If failures reveal unclear requirements, escalate to Planner for clarification.
- If infra-related failures occur, pass instructions to Ops.
- Always provide specific failing cases and expected behavior.

## Custom Commands

- `/test:unit <module>`
- `/test:property <module>`
- `/test:scenario <flow>`
