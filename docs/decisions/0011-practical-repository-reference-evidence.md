# ADR 0011: Practical repository reference evidence

- **Status:** Accepted
- **Date:** 2026-09-09
- **Amends:** ADR 0005 and ADR 0007
- **Amended by:** ADR 0012 and ADR 0017

## Context

Agent approval for `vulnerable_symbol_unused` required a complete literal scan
of files whose suffix appeared in a fixed code allowlist. The scan treated any
unknown extension, denied code-like path, oversized file, undecodable file,
symlink, or aggregate budget overrun as incomplete, while silently ignoring
JSON, YAML, TOML, text, and documentation.

That design was conservative but not practical. Common configuration formats
can execute or load npm dependencies, while harmless unfamiliar files could
prevent every approval. Adding more language suffixes would remain brittle and
would not prepare the workflow for another ecosystem.

A literal package-identifier search also does not prove semantic symbol
non-use. It provides bounded negative repository evidence that must be combined
with npm relationships, dependency consumers, and agent reasoning.

## Decision

- Replace the code-suffix allowlist with format-agnostic, bounded repository
  reference evidence.
- Build frozen reference evidence before the model turn, persist it, and include
  its safe aggregate summary in the assigned task.
- Attempt every agent-readable regular repository file as UTF-8 text regardless
  of extension, except exact dependency-lock metadata and a documented set of
  known binary asset formats.
- Parse each `package.json` and search retained content after removing package
  self-identification and top-level dependency declaration fields. Scripts and
  other configuration remain searchable.
- Exclude `package-lock.json` and `npm-shrinkwrap.json` from reference matching.
- Keep agent-denied files unavailable to Copilot and outside the reference
  candidate set. Narrow the `.github` rule so local action source under
  `.github/actions/**`, like workflow source, remains analyzable.
- Ignore symlinks, special files, and known binary assets without invalidating
  coverage. Treat unknown undecodable files, NUL-containing text candidates,
  read failures, invalid npm manifests, file-size drift, and proof-budget
  exhaustion as insufficient evidence.
- Keep `max_read_bytes` and `max_session_bytes` as agent-tool limits.
  `max_proof_scan_bytes` independently bounds deterministic reference scanning.
- Preflight candidate sizes with `lstat`; equality with the proof budget is
  allowed and overflow is insufficient.
- A positive reference blocks approval even if the scan stops early. Sufficient
  absence requires every candidate to be processed, no references, and at least
  one scanned usage-bearing text file.
- Retain the public `vulnerable_symbol_unused` reason code for compatibility,
  but define its trusted predicate as high-confidence agent assessment combined
  with sufficient zero-reference repository evidence. It does not claim formal
  semantic proof that every vulnerable symbol is unreachable.
- Do not require a citation as proof of absence. Citations remain validated
  positive observations and cannot substitute for repository-wide coverage.
- Keep complete npm evidence, first-party relationships, no dependency
  consumers, confidence, uncertainty, and injection gates unchanged.
- Keep npm-specific manifest filtering as one explicit helper. Add an ecosystem
  abstraction only when a second implementation exists.

## Consequences

- Unknown text formats, extensionless scripts, templates, styles, and ordinary
  configuration can contribute meaningful evidence without a language registry.
- Common harmless repository contents no longer force human review solely
  because their suffix is unfamiliar.
- Configuration-only dependency use can block approval.
- Binary and denied content remains outside the model boundary.
- Large repositories still fail closed when the deterministic total scan budget
  is exceeded.
- The default policy version changes because approval semantics change. The
  report schema remains unchanged because no report field or result type changes.
