# ADR 0007: Fail closed on unverifiable agent semantics

- **Status:** Accepted
- **Date:** 2026-09-04
- **Supersedes:** ADR 0006's temporary trust in agent-assessed
  `tolerable_risk` specificity and citation-only reachable denials
- **Amended by:** ADR 0011 and ADR 0017

## Context

Critical review found three agent semantics that deterministic reconciliation
could not independently verify:

- whether a free-text `tolerable_risk` justification is a sufficiently
  specific risk argument;
- whether an arbitrary cited repository line proves that a vulnerable surface
  is reachable and exploitable;
- which reason code belongs to which recommendation when tasks expose flat,
  independent outcome and code allowlists.

The task builder also removed control characters from requester justification,
which could concatenate words and alter the text being assessed.

## Decision

- Replace flat permitted outcomes and reason codes with typed
  recommendation/code permission groups in `AgentTask`.
- After input normalization trims outer whitespace from live requester
  comments, preserve the exact first 4,000 characters of the normalized
  justification. Do not remove or rewrite internal controls. JSON escaping
  provides transport safety; content remains untrusted data.
- Remove agent approval from the default `tolerable_risk` route until the
  workflow has project-owned structured evidence for justification
  specificity. Agent analysis may still deny or escalate.
- Keep deterministic non-applicability approval for `not_used` and
  `inaccurate`; requester text cannot influence those typed npm proofs and is
  not sent to a model on terminal paths.
- Remove `reachable_and_exploitable` from permitted agent denial codes until a
  typed reachability/exploitability proof model exists. Verified package usage
  may support `advisory_applies`; unsupported reachability proposals fail
  closed.
- Scope `injection_detected` to agentic analysis. Deterministic terminal
  decisions do not interpret or execute requester text and therefore do not
  require prompt-injection classification.
- Validate triage policy configuration with the same fail-closed principles:
  `human_review` is mandatory and approval codes must come from the canonical
  triage allowlist.

## Consequences

- The default policy prefers safe human review over approvals or denials whose
  load-bearing semantic predicate cannot be re-proven.
- Some previously approved `tolerable_risk` fixtures now escalate.
- `reachable_and_exploitable`, `preconditions_not_met`, and
  `false_positive_confirmed` remain documented decision-tree targets with
  explicit fail-closed coverage.
- A future ADR may enable them only after adding project-owned typed evidence
  and direct counterfactual tests.
