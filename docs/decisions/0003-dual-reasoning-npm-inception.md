# ADR 0003: Separate deterministic and model-assisted reasoning

- **Status:** Accepted
- **Date:** 2026-09-02
- **Supersedes:** ADR 0002's tool-less analyst
- **Amended by:** ADR 0005, ADR 0007, ADR 0019, and ADR 0021

## Context

Exact dependency and policy facts can be evaluated deterministically, while
repository usage and configuration may require bounded investigation. Mixing
those responsibilities in prompts would make policy difficult to test and
model output too authoritative.

## Decision

- Implement the npm ecosystem first.
- Keep versioned policy data, a pure deterministic engine, and a bounded
  investigator as separate responsibilities.
- Give the investigator only read-only tools over an immutable snapshot.
- Let deterministic code create typed tasks, validate findings, re-prove
  permitted outcomes, and publish the final result.
- Keep live GitHub and Copilot credentials on separate construction paths.
- Support dismissal review and alert triage over the same evidence pipeline.
- Keep policy declarative; executable rules remain in typed Python.

Later ADRs refine proof authority, supported package managers, and agent
permissions.

## Consequences

- Model reasoning can assist without becoming the decision authority.
- Policy and evidence behavior remain testable offline.
- New ecosystems require concrete collectors and proof capabilities rather than
  a speculative plugin framework.
