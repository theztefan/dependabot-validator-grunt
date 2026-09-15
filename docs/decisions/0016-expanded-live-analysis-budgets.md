# ADR 0016: Increase proven-small live analysis limits

- **Status:** Accepted
- **Date:** 2026-09-11
- **Amends:** ADR 0012
- **Amended by:** ADR 0017

## Context

Live acceptance showed that the original shared deadline and one-file read
limit blocked otherwise normal investigations, including generated lockfiles.
The distinct-content and deterministic proof-scan limits were not the observed
bottlenecks.

## Decision

Increase the shared workflow deadline and one-file agent read limit while
retaining:

- two attempts under one shared deadline;
- the per-attempt distinct-content budget;
- per-call result limits;
- the deterministic reference-scan budget;
- all archive, path, permission, citation, reconciliation, and publication
  controls.

Current values belong in the workflow contract and versioned policy.

## Consequences

- Normal generated dependency files can be inspected without broadening the
  repository-wide budget.
- Retries receive more completion time but no independent deadline.
- Future budget changes require evidence that the named boundary, rather than
  an unrelated limitation, was exercised.
