# ADR 0022: Normalize live uv alerts and add a Python investigator

- **Status:** Accepted
- **Date:** 2026-09-15
- **Amends:** ADR 0017, ADR 0020, and ADR 0021
- **Amended by:** ADR 0023, ADR 0024, ADR 0026, and ADR 0027

## Context

Live acceptance showed that GitHub currently reports uv project alerts with
the `pip` package ecosystem while selecting `uv.lock` or an adjacent
`pyproject.toml`. Treating `uv` as the only valid uv alert ecosystem caused
safe, supported repository inputs to fail dependency collection.

The first Python increment also made every inconclusive result terminal human
review. That avoided routing Python through the mandatory JavaScript/TypeScript
analyzer, but it prevented bounded model investigation of readable PEP 621,
Pipenv, setup, range, workspace, and other unsupported shapes.

Python distribution names and import names are not reliably one-to-one.
Static absence therefore cannot prove non-use. Positive repository use can
still be useful when it is anchored to trusted dependency provenance.

## Decision

ADR 0027 supersedes the investigator-specific parts of this decision. The
GitHub ecosystem and package-manager normalization, Python evidence rules, and
positive-only authority below remain current. The separate Python agent,
three-tool boundary, unchanged npm agent, and two-variant design no longer
apply.

- Preserve the GitHub-attested ecosystem independently from the selected
  package manager. Explicitly select uv collection for `pip` or `uv` alerts
  whose exact selected path and adjacent files identify a uv project.
- Return typed unsupported evidence for safely readable known Python manifest
  classes instead of treating lack of an implemented adapter as collection
  corruption. Unsafe paths, unreadable files, malformed supported formats,
  byte-limit violations, ambiguity, and orphaned lockfiles remain failures.
- Permit a unique, source-understood Poetry or uv lock record to establish a
  positive resolved instance even when the package is transitive. Do not grant
  complete inventory, consumer, development-scope, or negative authority.
- ~~Add a separate Python investigator asset set with only `list_files`,
  `read_file`, and `search`, plus a Python-specific skill.~~ Superseded by ADR
  0027's one investigator and common four-tool boundary.
- ~~Keep the npm investigator and mandatory ast-grep behavior unchanged. Do
  not add an analyzer registry or expose the JavaScript/TypeScript analyzer to
  Python.~~ Superseded by application-selected capabilities in ADR 0027.
- Permit Python capability findings only to deny with `advisory_applies` or escalate to
  human review. Never permit Python approval or repository-reference absence.
- Accept a Python denial only when trusted task evidence contains a matching
  declaration or resolved instance and the finding contains validated
  repository citations supporting actual use. No-match evidence cannot prove
  Python non-use.
- Apply the existing no-tool judge to validated real-model findings from both
  ecosystem capabilities of the single investigator. The judge receives only
  frozen validated context and cannot add evidence.

## Rejected alternatives

- **Rewrite GitHub's ecosystem value:** rejected because reports must preserve
  attested source identity.
- **Treat every Python lock record as active:** rejected because markers,
  sources, workspaces, groups, and environment forks can affect selection.
- **Reuse the npm investigator unchanged:** rejected because its mandatory
  analyzer and methodology are JavaScript/TypeScript-specific.
- **Add a generic agent or analyzer registry:** the registry rejection remains
  current; the two-variant rationale is superseded by ADR 0027.
- **Allow Python non-use approval from search absence:** rejected because
  distribution/import mapping, dynamic imports, plugins, namespace packages,
  generated code, and custom import hooks make absence unsound.

## Consequences

- Real pip-reported uv alerts can use the uv collector without losing GitHub
  provenance.
- More supported lock alerts complete deterministically, including safe
  transitive records.
- Remaining readable Python shapes can receive bounded explanatory analysis
  instead of failing early or stopping at an unexamined human-review result.
- Python capability conclusions remain positive-only and cannot weaken the
  deterministic non-applicability boundary.
