# ADR 0001: Practical modular CLI architecture

- **Status:** Accepted
- **Date:** 2026-09-01

## Context

The application runs as one Python CLI process in a sandboxed environment. A
multi-layer service architecture would add directories, interfaces, and
dependency rules without providing a second interface or deployment model.

## Decision

Use purpose-based modules in one package. Keep the CLI and dependency
construction in `main.py`, workflow orchestration outside the CLI, and Copilot
SDK behavior in a focused integration module.

Introduce protocols only for external boundaries that need offline fakes or
multiple implementations. Keep declarative agent assets as package data.
Require deterministic evidence before agent execution and validate agent output
before publication.

## Consequences

- The project remains easy to navigate and change.
- SDK and network behavior remain testable through small boundary fakes.
- Modules are split based on demonstrated responsibility rather than prediction.
- A future major deployment change may require revisiting this decision.
