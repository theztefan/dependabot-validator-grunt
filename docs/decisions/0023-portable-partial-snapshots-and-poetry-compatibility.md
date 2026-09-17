# ADR 0023: Prefer portable partial snapshots and bounded Poetry compatibility

- **Status:** Accepted
- **Date:** 2026-09-15
- **Amends:** ADR 0021 and ADR 0022
- **Amended by:** ADR 0028

## Context

Expanded live testing found supported npm and Python alerts that could not
reach dependency analysis because an unrelated generated source map exceeded
the ordinary archive-member limit or two unrelated source files differed only
by path case. The archive was otherwise within the bounded download, member,
and expanded-size limits. Failing the entire snapshot discarded safe positive
dependency evidence and prevented bounded agent review.

The same campaign found two common Poetry layouts outside the initial adapter:
Poetry 2 projects using only PEP 621 project metadata and older Poetry lock
format 1.1 files. Both contain explicit, statically parseable positive records.

## Decision

- Omit ordinary oversized files and all members of a normalized
  case-insensitive path collision from the immutable snapshot. Record every
  omitted path in `excluded_paths`.
- Continue failing when the selected dependency input is oversized or part of
  a normalized collision, or when archive download, member-count, or
  expanded-size limits are exceeded.
- Treat exclusions as incomplete repository coverage. They cannot support
  repository-wide negative reference proof, but they do not invalidate
  positive evidence from included immutable files.
- Accept Poetry 2 projects whose dependencies are declared through PEP 621
  without requiring a `[tool.poetry]` table.
- Add positive-only Poetry lock 1.1 support using its explicit `category`
  field. Only unique, exact, main-category, non-optional, unmarked,
  source-understood records receive `resolved_instances`.

## Rejected alternatives

- **Increase the ordinary per-file limit:** rejected because generated bundles
  and source maps provide little investigation value while increasing every
  snapshot's memory and read surface.
- **Extract one path from a case-fold collision:** rejected because choosing a
  winner would make snapshot meaning filesystem-dependent.
- **Ignore exclusions for negative proof:** rejected because omitted content
  could contain the missing reference.
- **Support every historical Poetry lock shape:** rejected because only lock
  1.1 was observed and has a narrow, explicit selection model.

## Consequences

- More large or cross-platform repositories reach deterministic and
  investigator analysis without weakening archive-wide resource bounds.
- Negative conclusions remain fail-closed whenever relevant files were
  omitted.
- Common current and older Poetry projects gain deterministic positive
  coverage while complete inventory and non-use remain unproven.
