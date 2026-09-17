# ADR 0027: Use one investigator path

- **Status:** Accepted
- **Date:** 2026-09-17
- **Supersedes:** ADR 0026
- **Amends:** ADR 0008, ADR 0014, ADR 0020, ADR 0021, ADR 0022, and ADR 0024
- **Consistent with:** ADR 0024 and ADR 0025

## Context

ADR 0026 introduced one shared investigator and temporarily kept the earlier
npm and Python agents for comparison and rollback. That temporary split added
runtime branches, duplicate assets, evaluation variants, provenance fields,
tests, and documentation without changing tools, permissions, output, or final
decision authority.

## Decision

Use one investigator implementation everywhere: offline fixtures, local
evaluation, and live GitHub Enterprise Cloud runs.

Trusted application code selects one versioned ecosystem capability from the task. A
capability chooses the npm or Python skill and analyzer profile. It does not
choose another agent implementation and cannot grant tools, permissions,
evidence authority, or policy outcomes.

Keep one investigator manifest, one common role prompt, the fixed four-tool
allowlist, deny-by-default permissions, strict finding validation, lazy no-tool
judging, and deterministic reconciliation.

Evaluation runs the current investigator once per case. It measures regression
quality; it does not compare legacy and bundled variants.

## Consequences

- Adding an ecosystem extends the closed capability mapping, collector,
  analyzer profile when needed, skill, and evaluation cases.
- There is no runtime fallback, legacy mode, variant flag, or duplicate
  investigator agent.
- Rollback uses source control rather than a second production path.
