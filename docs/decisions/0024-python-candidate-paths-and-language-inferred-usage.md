# ADR 0024: Record Python dependency paths and infer analyzer languages

- **Status:** Accepted
- **Date:** 2026-09-16
- **Amends:** ADR 0017, ADR 0021, and ADR 0022
- **Amended by:** ADR 0025, ADR 0027, ADR 0028, and ADR 0029

## Context

The first Python adapters matched only the alerted lock record. They could call
an undeclared record transitive but could not identify the dependency that
introduced it or provide a root-to-target path. Poetry and uv lockfiles already
contain bounded dependency relationships that can improve investigation
without executing package managers.

The first ast-grep integration staged a fixed JavaScript/TypeScript suffix
allowlist and embedded JavaScript-specific AST kinds and binding rules. The
suffix list was not a security boundary and required central code changes for
every additional language. Python still needs explicit import semantics and
distribution-to-import provenance.

## Decision

- Extract bounded recorded candidate graphs from supported Poetry and uv locks.
  Preserve markers, groups, optional state, sources, forks, ambiguity, cycles,
  edge requirements, and truncation. Propagate package-node and ancestor
  conditions through each path. Conditional ancestry or target-relevant graph
  or path truncation withholds positive target authority. Do not describe a
  recorded candidate path or requirement as the active environment or grant
  complete-consumer authority.
- Keep requirements includes, constraints, inventories, and `# via` comments
  as separate pip provenance. They do not become dependency graph edges.
- Retain GitHub's alert relationship as attested corroborating context.
- Advance evidence, agent-task, and report formats to `3.0`.
- Remove the ast-grep source-extension allowlist. Stage bounded readable text
  under the existing immutable-file and denied-path controls, and let the
  pinned engine infer language from paths.
- Keep operations and interpretation application-controlled. Add concrete
  Python import and dynamic-load operations without creating an analyzer
  plugin framework.
- Treat structural findings as positive syntax evidence only. No-match,
  unsupported syntax, partial input, and failure cannot prove non-reachability.
- Authorize a Python import target only when the canonical distribution
  identity is itself one valid top-level Python identifier. Other mappings
  remain advisory until a separately reviewed source of truth exists.
- Keep Python decisions positive-only and deny approval permission.

## Rejected alternatives

- **Resolve lockless manifests:** rejected because transitive resolution needs
  package metadata, an environment, and often build execution or network
  access.
- **Treat all lock paths as active:** rejected because universal locks encode
  conditional environments, extras, groups, sources, and variants.
- **Replace the suffix allowlist with an extension denylist:** rejected because
  extensions are neither the security boundary nor a reliable statement of
  analyzer language support.
- **Assume normalized distribution names are import names:** rejected because
  common packages intentionally expose different top-level modules.
- **Build an analyzer registry:** rejected because two concrete syntax families
  need only a small application-owned operation profile.

## Consequences

- Transitive Python alerts can include immediate consumers and bounded
  root-to-target candidate paths.
- The investigator's Python capability can receive validated structural import
  evidence while remaining unable to approve or infer non-use.
- Future languages do not require changing a staging suffix list, but they
  still require explicit reviewed package-usage semantics.
- Plain pip and lockless projects remain honestly partial unless a separately
  attested resolution artifact is supplied in a future increment.
