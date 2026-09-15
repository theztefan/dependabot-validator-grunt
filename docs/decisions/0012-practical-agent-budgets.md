# ADR 0012: Budget distinct repository coverage per attempt

- **Status:** Accepted
- **Date:** 2026-09-10
- **Amends:** ADR 0008 and ADR 0011
- **Amended by:** ADR 0016

## Context

Charging every repository search for bytes already read caused repeated bounded
queries to exhaust small sessions. Retries also need isolated mutable state
without gaining unbounded total time.

## Decision

- Charge successful decoded file content once per immutable path in each model
  attempt and cache it for repeated reads and searches.
- Give each retry a fresh cache and tool budget, but keep one shared wall-clock
  deadline across setup and all attempts.
- Enforce `max_read_bytes <= max_session_bytes` and bounded `limit + 1` reads.
- Bound attempts, per-file reads, distinct content, result counts, deterministic
  proof scans, and aggregate static model-facing text independently.
- Keep path denial, permissions, citations, snapshot identity, and
  reconciliation unchanged.

Current default values live in the workflow contract and versioned policy, not
in this ADR.

## Consequences

- Agents can compare package use and configuration without paying repeatedly
  for the same immutable files.
- Retries remain isolated but cannot multiply the workflow deadline.
- Large repositories still stop at explicit, testable limits.
