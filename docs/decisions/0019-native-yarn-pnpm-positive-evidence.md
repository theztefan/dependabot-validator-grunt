# ADR 0019: Add Yarn and pnpm with positive-only proof authority

- **Status:** Accepted
- **Date:** 2026-09-14
- **Amends:** ADR 0003, ADR 0009, ADR 0010, ADR 0017, and ADR 0018

## Context

Live npm-ecosystem alerts also use Yarn Classic v1 and pnpm v9 lockfiles.
Executing package-manager CLIs would admit repository-selected code,
configuration, plugins, downloads, and unstable output. Native parsers preserve
the offline trust boundary, but incomplete graph support must not authorize
negative security conclusions.

## Decision

- Keep collection in trusted Python; never execute npm, Yarn, pnpm, Corepack,
  lifecycle scripts, repository configuration, or network requests.
- Dispatch by the selected manifest basename and normalize supported managers
  into one dependency graph with explicit provenance and proof capabilities.
- Parse pnpm through a restricted resource-bounded YAML loader and Yarn Classic
  through a bounded application-owned grammar.
- Use stable logical locators for Yarn and pnpm instances.
- Grant initial adapters only resolved-instance authority. A concrete,
  registry-backed, comparable vulnerable instance may prove applicability.
- Do not grant complete inventory, complete consumer, or development-scope
  authority. These adapters cannot prove absence, unaffected versions,
  vulnerable-symbol non-use, or development-only installation.
- Reject unsupported versions and ambiguous syntax rather than parsing
  optimistically.

## Consequences

- Supported Yarn and pnpm alerts can produce deterministic positive triage
  without a Node runtime or unnecessary model call.
- Negative and scope-based outcomes remain conservative until separately
  certified capabilities exist.
- Official package-manager parsers may serve as differential-test oracles
  outside the runtime boundary, not as repository-executed production tools.
