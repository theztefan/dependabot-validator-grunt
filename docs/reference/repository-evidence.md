# Repository evidence reference

This page explains how the application reads repository files. The normative
permission and decision rules remain in
[`../workflow-contract.md`](../workflow-contract.md).

## Immutable snapshot

Offline runs use the fixture repository directory and bind evidence to a digest
of normalized paths and file contents. Live runs resolve the default branch to
one commit SHA and extract the tarball for that SHA into a temporary read-only
directory.

The extractor rejects path traversal, absolute paths, selected dependency
inputs beneath normalized path collisions, links, devices, FIFOs, and root
escapes. Ordinary oversized files and every descendant of a case-insensitive
Unicode-normalized path collision are excluded and recorded as incomplete
coverage. Credential-like files and repository-provided agent, instruction,
hook, plugin, and MCP controls are also excluded. `.github/workflows/**` and
`.github/actions/**` remain readable because they can affect dependency
execution.

Coverage exclusions cannot invalidate positive observations from included
files, but they prevent repository-wide sufficient-absence proof.

## Agent reads

The investigator can list, read, and search only files that passed snapshot
controls. Trusted handlers reject:

- absolute paths and `..`;
- paths outside the snapshot;
- symlinks and special files;
- known binary files;
- credential-like files;
- denied repository control files;
- files above the per-file limit.

One immutable file is charged only once per attempt. Repeated reads use an
attempt-local cache. Each retry receives a fresh cache and content budget.

## Repository reference evidence

When a task may propose `vulnerable_symbol_unused`, trusted application code performs a
bounded package-identifier scan before model dispatch.

The scan considers readable UTF-8 repository text without relying on a source
file extension allowlist. It excludes lockfiles and dependency declaration
noise. For `package.json`, it removes top-level dependency identity fields but
keeps scripts and tool configuration searchable.

The result is one of:

- `reference_found`: at least one package reference exists;
- `sufficient_absence`: every candidate was processed and no reference exists;
- `insufficient`: coverage was incomplete or unsafe.

A positive reference remains useful even if the scan later reaches a limit.
Absence is sufficient only when every candidate was processed and at least one
usage-bearing text file was scanned.

Unreadable text, NUL data, invalid manifests, file drift, read failures, and
budget exhaustion make absence insufficient. Model prose or citations cannot
replace this trusted aggregate proof.

## Relevant limits

Default limits are:

| Limit | Default |
|---|---:|
| One agent-readable file | 2 MiB |
| Distinct file content per model attempt | 32 MiB |
| Deterministic reference scan | 64 MiB |
| Results from one list or search call | 200 |

Archive and dependency-file limits are documented in
[`github-api.md`](github-api.md), [`npm-evidence.md`](npm-evidence.md), and
[`python-evidence.md`](python-evidence.md).
