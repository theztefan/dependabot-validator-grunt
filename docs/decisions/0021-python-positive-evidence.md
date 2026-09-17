# ADR 0021: Add Python with positive-only dependency evidence

- **Status:** Accepted
- **Date:** 2026-09-15
- **Amends:** ADR 0001, ADR 0003, ADR 0010, ADR 0017, and ADR 0019
- **Amended by:** ADR 0022, ADR 0023, ADR 0024, and ADR 0027

## Context

Dependabot alerts use the `pip` ecosystem for pip requirements and Poetry and a
separate `uv` ecosystem for uv projects. The workflow's shared evidence and
artifact contracts were named for npm, while Python distribution identity,
PEP 440 versions, project selection, markers, groups, sources, and universal
locks have different semantics.

Executing pip, Poetry, or uv would admit repository-selected configuration,
plugins, build backends, project code, downloads, and mutable resolver output.
Static parsers can safely identify selected exact versions, but incomplete
profile and environment semantics must not become negative security proof.
The existing structural analyzer is JavaScript/TypeScript-specific, and ADR
0017 requires a concrete reviewed adapter before another ecosystem can use it.

## Decision

ADR 0027 supersedes only this ADR's initial requirement that inconclusive
Python results stop before investigation. The positive-only evidence,
collection, and decision-authority rules remain current.

- Generalize shared alert, dependency evidence, agent-task, and report
  contracts, while keeping npm and Python parsers in concrete purpose-based
  modules.
- Select collectors with explicit ecosystem and path branches. Do not add a
  registry, plugin protocol, factory, or package-manager abstraction framework.
- Preserve the attested package spelling and add ecosystem-specific canonical
  identity. Python uses PyPA distribution-name normalization.
- Evaluate npm ranges with npm SemVer and Python ranges with PEP 440 through
  explicit version dispatch.
- Parse repository files only. Never execute pip, Poetry, uv, build backends,
  project code, plugins, lifecycle hooks, or network resolution.
- Initially support exact unmarked pins in the selected pip requirements input,
  direct-main Poetry 2.1 records, and direct-main non-workspace uv v1 records
  under the source and ambiguity rules in the workflow contract.
- Grant initial Python adapters only conditional `resolved_instances`
  authority. They cannot prove complete inventory, absence, universal
  unaffected versions, complete consumers, development scope, or non-use.
- Make positive vulnerable Python triage terminal. Make every inconclusive
  Python result terminal `human_review` with no investigator, judge,
  repository-reference scan, or structural analyzer call.
- Keep the existing JavaScript/TypeScript analyzer unchanged. Python
  structural analysis requires a later ADR with a concrete package-to-import
  identity and proof design.
- Advance serialized formats because ecosystem identity and npm-shaped field
  names change. Existing artifacts remain immutable and are not reinterpreted
  as the new schema.

## Rejected alternatives

- **Execute native package managers:** rejected because it crosses the
  repository-code, plugin, network, and mutable-resolution trust boundaries.
- **Treat lockfile presence as applicability:** rejected because Poetry and uv
  locks can contain inactive groups, extras, environments, members, and source
  variants.
- **Duplicate an independent Python workflow:** rejected because policy,
  lifecycle, validation, reconciliation, and publication remain shared.
- **Add a collector or analyzer registry:** rejected because there are only two
  explicit ecosystems and no dynamic deployment need.
- **Route Python through the then-current investigator unchanged:** rejected
  because its mandatory analyzer was JavaScript/TypeScript-specific and Python
  package names do not reliably identify import modules. ADR 0027 later
  introduced one investigator with an explicitly selected Python capability.

## Consequences

- Common direct Python projects gain useful deterministic positive
  applicability without executing repository code.
- Unsupported Python syntax, profiles, sources, workspaces, and environments
  fail closed as partial evidence or collection errors.
- npm behavior remains available through the generalized contracts.
- Transitive Python graphs, environment-aware selection, lock freshness
  certification, Python reachability, and negative conclusions require later
  independently reviewed increments.
