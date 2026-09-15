# ADR 0018: Review agent findings with one two-lens judge turn

- **Status:** Accepted
- **Date:** 2026-09-14
- **Amended by:** ADR 0019 and ADR 0020

## Context

A single investigator can anchor on its first interpretation or overstate
partial evidence. Separate critic, repair, and judge sessions would add
disproportionate latency and model cost to a short structured finding.

## Decision

After a real investigator finding validates, run one no-tool judge turn with:

- an evidence critic for grounding, contradictions, and evidence scope;
- an applicability critic for consumers, practical reachability, mitigations,
  and exploitability overclaims.

The judge may accept the original finding unchanged or replace it with another
complete permitted finding using only the primary attempt's validated
observations. Trusted Python validates judge identity, critic consistency,
permissions, citations, and the selected finding. Deterministic reconciliation
remains final authority.

Judge failure is explicit and non-blocking: retain the valid primary finding and
write the judge failure artifact. Lifecycle and terminal deterministic routes
invoke neither model.

## Consequences

- Agentic routes gain two adversarial perspectives with one compact model call.
- The judge cannot create repository evidence or become a publication gate.
- Primary and replacement findings remain separately inspectable.
