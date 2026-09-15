# ADR 0009: Application-controlled live triage routing

- **Status:** Accepted
- **Date:** 2026-09-08
- **Amends:** ADR 0005's optional live alert verification
- **Amended by:** ADR 0010 and ADR 0019

## Context

Live alert triage exposed `--real-copilot` as an operator switch. Without the
flag, a vulnerable or inconclusive deterministic baseline was published
without the repository-backed verification that the workflow contract
otherwise required. The same alert and policy could therefore produce a
different reasoning depth based on invocation syntax.

Dismissal review already follows the safer pattern: trusted deterministic
routing decides whether a model turn is required, and a missing Copilot
boundary fails explicitly only when the selected route needs it.

Offline fixtures have a separate evaluation purpose. They must continue to run
deterministically without credentials, use scripted findings when present, and
use the real SDK only when explicitly requested.

## Decision

- Treat deterministic `does_not_apply` as the only terminal live triage
  baseline.
- Require bounded agent verification for every other live triage baseline.
- Derive this requirement from the trusted workflow run mode and deterministic
  result, not from a command-line enablement flag.
- Allow deterministic `does_not_apply` live runs to complete without a Copilot
  credential.
- Fail with a configuration error after deterministic evidence collection when
  a live non-terminal route requires agent verification and no Copilot
  boundary is available.
- Keep `--real-copilot` only for offline fixtures. Live triage automatically
  constructs the Copilot boundary when `COPILOT_GITHUB_TOKEN` is available.
- Keep `--model` as model selection rather than agent enablement. Defer its
  credential and availability validation until trusted routing selects an
  agentic route, so deterministic `does_not_apply` remains terminal.
- Preserve current offline fixture behavior when no scripted or explicitly
  requested real model turn is available.

ADR 0019 later makes positive Yarn and pnpm applicability terminal because
those adapters cannot authorize an agentic non-applicability exception.

## Consequences

- Live reasoning depth is determined by application logic and evidence rather
  than operator invocation choices.
- An exported `COPILOT_GITHUB_TOKEN` causes every live triage result other than
  deterministic `does_not_apply` to send the bounded task and repository
  observations through the Copilot boundary, with the associated egress and
  model cost.
- Missing Copilot credentials do not block conclusive live non-applicability,
  but they do block publication of vulnerable or inconclusive live baselines.
- An explicit model is ignored when live triage terminates deterministically;
  it is validated by the Copilot boundary only when agent verification runs.
- Offline evaluations remain credential-free and can isolate deterministic
  behavior.
- A future policy-controlled triage routing model requires a separate contract
  and ADR change; the current policy controls permitted findings, not whether
  live verification occurs.
