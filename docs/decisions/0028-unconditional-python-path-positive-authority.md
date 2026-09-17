# ADR 0028: Preserve positive authority from an unconditional Python path

- **Status:** Accepted
- **Date:** 2026-09-17
- **Amends:** ADR 0023 and ADR 0024
- **Consistent with:** ADR 0021, ADR 0025, and ADR 0027

## Context

Poetry and uv locks can record several paths to one unique package record.
Some paths may be conditional while another path selects the same record
unconditionally from the selected project. The initial graph rule withheld
`resolved_instances` when any explored ancestry was conditional. Live
evaluation showed that this converted known vulnerable instances into
investigator-driven human review even when a complete unconditional runtime
path was present.

The condition belongs to the affected path. It does not negate a separate
unconditional path to the same unique supported record.

## Decision

Grant positive `resolved_instances` authority when all existing record,
source, version, ambiguity, and truncation checks pass and at least one
complete importer-to-target path is unconditional, non-development, and
cycle-free.

Retain conditional alternatives as explicit candidate-path context. They do
not remove authority established by the qualifying path.

Continue withholding authority when all known paths are conditional, optional,
development-only, cyclic, ambiguous, unsupported, or when target-relevant
graph or path context is truncated. This decision grants no inventory,
consumer-completeness, scope, absence, non-use, or exploitability authority.

## Consequences

- Supported vulnerable Poetry and uv instances can remain deterministic when
  one unconditional selected-project path proves positive presence.
- Conditional-only environments still require investigator or human review.
- Investigator prompts and Python denial requirements remain unchanged.
- Candidate paths continue to expose every retained condition for review.
