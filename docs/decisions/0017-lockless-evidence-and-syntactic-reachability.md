# ADR 0017: Support manifest-only evidence and bounded syntax analysis

- **Status:** Accepted
- **Date:** 2026-09-14
- **Amends:** ADR 0007, ADR 0011, ADR 0014, and ADR 0016
- **Amended by:** ADR 0019

## Context

Selected projects may have `package.json` without a sibling lockfile. Literal
package-name search provides useful reference evidence but is easy to overstate
as semantic reachability. A first structural analyzer was needed without
introducing a generic engine framework or granting negative-proof authority.

## Decision

- Select only the alert manifest's normalized project directory.
- When its lockfile is absent, parse the sibling manifest into typed direct,
  development, optional, and peer declarations.
- Mark manifest-only evidence partial. It cannot prove installed versions,
  installed absence, transitive completeness, consumers, development-only
  installation, or deployment state.
- Give recognized dependency files a separate bounded collection limit while
  retaining the ordinary archive-member and total archive limits.
- Use pinned `ast-grep-cli==0.45.3` through one application-controlled
  `analyze_reachability` tool with fixed operations, staged approved source,
  no shell, no network, no repository configuration, and validated
  digest-bound citations.
- Require each accepted real investigator attempt to invoke the analyzer.
  Cache repeated calls within the attempt.
- Treat positive syntax matches as evidence. Treat no match, partial output,
  failure, or unavailability as uncertainty, never semantic non-reachability.
- Keep deterministic reconciliation as the only decision authority.

ADR 0019 adds Yarn and pnpm evidence and advances format versions. Current
limits and formats live in the workflow contract.

## Consequences

- Lockless projects can complete with useful but explicitly partial evidence.
- Structural evidence improves grounding without enabling unsafe negative
  conclusions.
- A second analyzer requires a concrete adapter and ADR; no registry is added
  in advance.
