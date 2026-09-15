# ADR 0002: Start with report-only dismissal review

- **Status:** Accepted
- **Date:** 2026-09-01
- **Amended by:** ADR 0003

## Context

The live request contract, evidence availability, evaluation volume, and
operator ownership were not proven. Starting with GitHub writes,
organization-scale orchestration, or remediation would have required service
infrastructure and authorization rules before the review workflow was known to
be useful.

## Decision

Start as a local CLI that reviews one GitHub Enterprise Cloud Dependabot
dismissal request and publishes local artifacts only. GitHub access is
read-only. Deterministic code owns routing, proof eligibility, validation, and
publication.

GitHub mutations require a later ADR covering identity, credential separation,
race handling, action limits, audit storage, and rollback.

ADR 0003 replaced the original tool-less analyst with bounded repository
investigation.

## Consequences

- The product can validate evidence and report quality before adding autonomy.
- Offline tests can exercise the workflow through boundary fakes.
- Direct actions and organization-scale operation remain deliberate future
  decisions, not incremental permission changes.
