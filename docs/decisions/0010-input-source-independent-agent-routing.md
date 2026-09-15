# ADR 0010: Input-source-independent agent routing

- **Status:** Accepted
- **Date:** 2026-09-08
- **Amends:** ADR 0009's offline routing exception
- **Amended by:** ADR 0019

## Context

ADR 0009 moved live triage agent selection from `--real-copilot` into trusted
workflow routing, but preserved different behavior for offline fixtures.
Offline triage could still publish a vulnerable or inconclusive deterministic
baseline when neither a scripted response nor real model turn was supplied.
The fixture source therefore changed product reasoning rather than only
changing where evidence and model output came from.

The `--real-copilot` flag also duplicated responsibility. Deterministic routing
already decides whether analysis is required, while `--model` can explicitly
select the real Copilot boundary for an offline evaluation.

Ambient credentials must not silently replace scripted fixtures. Default
offline evaluation must remain reproducible, credential-free, and free from
unexpected model egress or cost.

## Decision

- Treat live GitHub collection and offline fixtures as input sources, not
  different reasoning modes.
- Require an agent boundary whenever dismissal routing returns an `AgentTask`
  or triage does not deterministically establish `does_not_apply`.
- Fail configuration rather than publish a non-terminal deterministic baseline
  when no required boundary exists.
- Remove `--real-copilot` from both CLI commands.
- Use fixture `agent-response.json` as the default offline boundary.
- Use `--model <runtime-model-id>` as the explicit offline CLI selection of
  real Copilot. It requires `COPILOT_GITHUB_TOKEN` and overrides the scripted
  response.
- Ignore ambient Copilot credentials for offline CLI runs without `--model`.
- Preserve explicit programmatic `model_turn` precedence over fixture scripts.
- Do not invoke a supplied real or scripted boundary when deterministic routing
  is terminal.

ADR 0019 adds a terminal positive-applicability route for initial Yarn and pnpm
adapters. Input-source independence remains unchanged.

## Consequences

- Workflow results no longer depend on whether evidence came from GitHub or a
  fixture.
- Deterministic tests remain deterministic and should test the pure decision
  engine directly when no agent result is relevant.
- Full offline workflow tests must provide a scripted or explicitly supplied
  boundary for agent-required routes.
- Real offline CLI evaluation requires an explicit model ID; runtime-default
  model integration tests may still construct `CopilotModelTurn`
  programmatically.
- Scripted fixtures remain stable even when the developer shell exports a
  Copilot credential.
