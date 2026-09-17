# ADR 0029: Scope and batch profile-aware import analysis

- **Status:** Accepted
- **Date:** 2026-09-17
- **Amends:** ADR 0024 and ADR 0025
- **Consistent with:** ADR 0012, ADR 0016, ADR 0027, and ADR 0028

## Context

The first multi-language analyzer staged every readable repository file and
ran each fixed operation over the complete staged set. Live evaluation showed
operation deadlines and partial coverage at 7.2 MiB and 10.8 MiB, well below
the aggregate 64 MiB and 10,000-file limits. Increasing those aggregate limits
alone would expand work without addressing irrelevant profile input.

The analyzer also operated over the whole repository snapshot. In a monorepo,
an import in an unrelated sibling project must not establish positive
applicability for the alert-selected manifest.

Python distribution identity also differs from import identity for common
packages. ADR 0024 reserved authority for a separately reviewed source of
truth rather than allowing model or heuristic guesses.

## Decision

- Derive one trusted analysis root from the parent of the alert-selected
  manifest and bind it into the task, analyzer evidence, validation, and
  citations.
- Analyze only pinned-engine profile paths under that root. npm uses the
  supported JavaScript and TypeScript path forms; Python uses `.py` and `.pyi`.
  This selection is execution mechanics, not a path-security boundary or
  negative-proof authority.
- Process profile paths in deterministic bounded batches under one shared
  deadline and aggregate file, byte, output, stderr, and finding limits.
- Bind application-owned import rules to the complete assigned target set so
  unrelated imports are discarded before consuming stdout. Run generic call
  collection only on files containing a target literal or target import match,
  preserving supported runtime imports and bound calls without scanning every
  unrelated call expression.
- Increase the aggregate analyzer defaults to 20,000 files, 128 MiB, and 120
  seconds, with batches of at most 1,000 files and 16 MiB.
- Preserve positive findings from completed batches. Any missing profile file,
  batch, or operation keeps no-match evidence incomplete.
- Add a small versioned application-owned mapping for reviewed Python
  distribution-to-import differences. Curated mappings replace canonical
  same-name inference for that distribution and may contain multiple explicit
  top-level targets. Broad shared namespace roots, unknown mappings, and known
  competing distributions for the same top-level import remain
  non-authoritative for every involved distribution.
- Keep ordinary list, read, and search tools available across the bounded
  snapshot. Project scoping applies to decision-changing structural evidence,
  not to contextual investigation.

## Rejected alternatives

- **Only increase file, byte, and time limits:** rejected because observed
  incomplete runs were dominated by operation time over irrelevant input.
- **Use runtime or network package metadata:** rejected because it is
  environment-dependent, mutable, and outside the read-only offline boundary.
- **Let the model propose import names or project roots:** rejected because
  both values are load-bearing evidence identity.
- **Treat a curated list as complete:** rejected because package import
  surfaces evolve and namespace packages can be shared.
- **Analyze the whole monorepo and ask the model to infer ownership:** rejected
  because deterministic validation must prevent cross-project positive proof.

## Consequences

- Large selected projects spend analyzer resources on supported source rather
  than lockfiles, documentation, unrelated sibling projects, and unrelated
  structural output.
- Aggregate limits increase without weakening bounded execution or incomplete
  semantics.
- Common Python packages with different import names can produce authoritative
  positive structural findings.
- Shared code outside a nested selected project can be missed by structural
  analysis, but the result remains human review rather than false
  non-applicability.
- Adding or changing an authoritative import mapping requires reviewed source,
  fixtures, and evaluation evidence.
- Known namespace collisions retain useful analyzer coverage but cannot
  independently authorize a final decision.
