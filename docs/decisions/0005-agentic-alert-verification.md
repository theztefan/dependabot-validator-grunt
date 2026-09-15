# ADR 0005: Use bounded repository investigation for unresolved cases

- **Status:** Accepted
- **Date:** 2026-09-03
- **Amended by:** ADR 0006, ADR 0007, ADR 0009, and ADR 0011

## Context

Some dismissal and triage outcomes require repository usage or configuration
evidence that dependency metadata alone cannot provide. Identity-only tasks and
deterministic-only triage could not evaluate those cases.

## Decision

- Keep closed lifecycle and policy outcomes deterministic.
- For unresolved cases, give the investigator bounded request, advisory,
  dependency, and immutable snapshot context.
- Permit only typed recommendation/code pairs and validate all cited repository
  observations before deterministic reconciliation.
- Reuse the same agent boundary for alert triage, while keeping triage and
  dismissal result types distinct.
- Include ordinary application and GitHub Actions source, but exclude
  repository-provided agent controls, credentials, links, and special files.

ADR 0007 removes outcomes whose predicates cannot be independently proved. ADR
0011 defines repository-wide reference evidence. ADR 0009 and ADR 0010 define
when the boundary runs.

## Consequences

- Both workflows can use repository-backed evidence without granting shell,
  network, write, or GitHub tools.
- Agent findings remain proposals; Python owns final authority.
- Path controls and immutable snapshots are part of the feature, not optional
  hardening.
