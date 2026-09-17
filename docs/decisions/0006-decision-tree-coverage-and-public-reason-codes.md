# ADR 0006: Separate internal rules from public decision codes

- **Status:** Accepted
- **Date:** 2026-09-04
- **Amends:** ADR 0005
- **Superseded by:** ADR 0007's temporary trust in agent-assessed semantics

## Context

Internal deterministic rule IDs leaked into reports, fixture coverage did not
represent every decision-tree leaf, and some public outcomes lacked a typed
predicate that Python could re-prove.

## Decision

- Keep policy rule IDs internal and map final results to stable public reason
  codes.
- Bind each dismissal reason to explicit permitted recommendation/code pairs.
- Keep fail-closed `human_review` available for every investigator route.
- Use a committed test manifest to distinguish decision criteria from scripted
  fixture scenarios.
- Reject external policy that introduces noncanonical reasons, removes required
  fail-closed outcomes, or omits enabled deterministic denials.

ADR 0007 supersedes temporary support for agent-assessed
`tolerable_risk` specificity and citation-only
`reachable_and_exploitable` conclusions. Current codes and predicates are
defined in [`../workflow-contract.md`](../workflow-contract.md).

## Consequences

- Reports use stable product terminology without coupling it to Python function
  names.
- Fixture coverage can include unsupported leaves without enabling unsafe
  outcomes.
- New automated codes require a project-owned predicate and focused tests.
