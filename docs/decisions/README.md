# Architectural decisions

ADRs preserve durable rationale. They do not define current workflow behavior
or replace the module map. Start with the most recent decision for the topic,
follow its amendment links only when historical context is needed, then verify
the result in [`../workflow-contract.md`](../workflow-contract.md) and
[`../architecture.md`](../architecture.md).

## Current decision map

| Change area | Start here | Earlier decisions when needed |
|---|---|---|
| Product boundary and reasoning model | [0003](0003-dual-reasoning-npm-inception.md) | [0002](0002-report-only-inception.md) |
| Module ownership and concrete abstractions | [0025](0025-concrete-reachability-boundaries.md) | [0001](0001-practical-modular-cli.md) |
| Decision authority, public codes, and fail-closed proof | [0007](0007-fail-closed-unverifiable-agent-semantics.md), [0011](0011-practical-repository-reference-evidence.md) | [0005](0005-agentic-alert-verification.md), [0006](0006-decision-tree-coverage-and-public-reason-codes.md) |
| Live and offline routing | [0010](0010-input-source-independent-agent-routing.md) | [0009](0009-application-controlled-live-triage.md) |
| Copilot sessions, assets, and output validation | [0027](0027-single-investigator-path.md), [0015](0015-single-object-agent-output-extraction.md) | [0008](0008-sdk-native-custom-agent-sessions.md), [0014](0014-sdk-event-timing-and-tool-overrides.md), [0020](0020-explicit-custom-agent-assets-for-both-roles.md) |
| Agent budgets and scalable analysis | [0029](0029-project-scoped-scalable-import-analysis.md) | [0012](0012-practical-agent-budgets.md), [0016](0016-expanded-live-analysis-budgets.md) |
| Manifest-only evidence and structural analysis | [0029](0029-project-scoped-scalable-import-analysis.md), [0025](0025-concrete-reachability-boundaries.md) | [0017](0017-lockless-evidence-and-syntactic-reachability.md), [0024](0024-python-candidate-paths-and-language-inferred-usage.md) |
| Judge behavior | [0027](0027-single-investigator-path.md) | [0018](0018-two-critic-llm-judge-forum.md), [0020](0020-explicit-custom-agent-assets-for-both-roles.md) |
| Yarn and pnpm evidence authority | [0019](0019-native-yarn-pnpm-positive-evidence.md) | [0003](0003-dual-reasoning-npm-inception.md) |
| Python evidence and investigation | [0028](0028-unconditional-python-path-positive-authority.md), [0029](0029-project-scoped-scalable-import-analysis.md) | [0021](0021-python-positive-evidence.md), [0022](0022-python-investigator-and-live-uv-normalization.md), [0023](0023-portable-partial-snapshots-and-poetry-compatibility.md), [0024](0024-python-candidate-paths-and-language-inferred-usage.md) |
| Credentials and dotenv loading | [0013](0013-dotenv-and-shared-credential-values.md) | None |
| Investigator capabilities and evaluation | [0027](0027-single-investigator-path.md) | [0020](0020-explicit-custom-agent-assets-for-both-roles.md) |

## Superseded records

| ADR | Replacement | Why it remains |
|---|---|---|
| [0026: Version investigator capability bundles and evaluations](0026-versioned-investigator-capability-bundles.md) | [0027](0027-single-investigator-path.md) | It records the short-lived multi-variant design and why the repository returned to one investigator path. |

Do not delete a superseded ADR merely to shorten the directory. Keep it when a
later decision depends on its rejected alternatives or explains a migration.
Remove a record only when it contains no durable architectural rationale, and
migrate every inbound link first.

## Record status

| Status | ADRs |
|---|---|
| Accepted | [0001](0001-practical-modular-cli.md), [0002](0002-report-only-inception.md), [0003](0003-dual-reasoning-npm-inception.md), [0005](0005-agentic-alert-verification.md), [0006](0006-decision-tree-coverage-and-public-reason-codes.md), [0007](0007-fail-closed-unverifiable-agent-semantics.md), [0008](0008-sdk-native-custom-agent-sessions.md), [0009](0009-application-controlled-live-triage.md), [0010](0010-input-source-independent-agent-routing.md), [0011](0011-practical-repository-reference-evidence.md), [0012](0012-practical-agent-budgets.md), [0013](0013-dotenv-and-shared-credential-values.md), [0014](0014-sdk-event-timing-and-tool-overrides.md), [0015](0015-single-object-agent-output-extraction.md), [0016](0016-expanded-live-analysis-budgets.md), [0017](0017-lockless-evidence-and-syntactic-reachability.md), [0018](0018-two-critic-llm-judge-forum.md), [0019](0019-native-yarn-pnpm-positive-evidence.md), [0020](0020-explicit-custom-agent-assets-for-both-roles.md), [0021](0021-python-positive-evidence.md), [0022](0022-python-investigator-and-live-uv-normalization.md), [0023](0023-portable-partial-snapshots-and-poetry-compatibility.md), [0024](0024-python-candidate-paths-and-language-inferred-usage.md), [0025](0025-concrete-reachability-boundaries.md), [0027](0027-single-investigator-path.md), [0028](0028-unconditional-python-path-positive-authority.md), [0029](0029-project-scoped-scalable-import-analysis.md) |
| Superseded | [0026](0026-versioned-investigator-capability-bundles.md) |
| Historical | None |

## ADR standard

New ADRs must contain:

- status, date, and explicit amendment relationships;
- the durable problem that cannot be understood from current code alone;
- the chosen constraint and material rejected alternative;
- operational or architectural consequences.

Use `Accepted`, `Superseded`, or `Historical` as the primary status. Express
partial changes through `Amends`, `Amended by`, `Supersedes`, and `Superseded
by` metadata, with both ADRs recording the relationship.

Keep current contract text, implementation checklists, research catalogs,
campaign results, and version changelogs out of ADRs. Temporary evidence belongs
in gitignored `.logs/`; promote only conclusions that still constrain future
changes.
