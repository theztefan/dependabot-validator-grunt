# Architectural decisions

ADRs explain why durable constraints exist. They are not a second workflow
contract and are not required reading as a set. Use this index to select the
decision relevant to a proposed change, then verify current behavior in
[`../workflow-contract.md`](../workflow-contract.md) and current ownership in
[`../architecture.md`](../architecture.md).

## Read by topic

| Change area | ADRs |
|---|---|
| Module ownership and abstractions | [0001](0001-practical-modular-cli.md) |
| Read-only product and npm-first reasoning | [0002](0002-report-only-inception.md), [0003](0003-dual-reasoning-npm-inception.md) |
| Agent permissions, public codes, and fail-closed proof | [0005](0005-agentic-alert-verification.md), [0006](0006-decision-tree-coverage-and-public-reason-codes.md), [0007](0007-fail-closed-unverifiable-agent-semantics.md), [0011](0011-practical-repository-reference-evidence.md) |
| Copilot SDK sessions and output validation | [0008](0008-sdk-native-custom-agent-sessions.md), [0012](0012-practical-agent-budgets.md), [0014](0014-sdk-event-timing-and-tool-overrides.md), [0015](0015-single-object-agent-output-extraction.md), [0016](0016-expanded-live-analysis-budgets.md), [0020](0020-explicit-custom-agent-assets-for-both-roles.md) |
| Live and offline routing | [0009](0009-application-controlled-live-triage.md), [0010](0010-input-source-independent-agent-routing.md) |
| Credentials and dotenv | [0013](0013-dotenv-and-shared-credential-values.md) |
| Manifest-only evidence and structural analysis | [0017](0017-lockless-evidence-and-syntactic-reachability.md) |
| Judge behavior | [0018](0018-two-critic-llm-judge-forum.md), [0020](0020-explicit-custom-agent-assets-for-both-roles.md) |
| Yarn and pnpm evidence authority | [0019](0019-native-yarn-pnpm-positive-evidence.md) |

## Historical inception records

ADR [0002](0002-report-only-inception.md) contains the retained inception
rationale for the read-only product boundary. Delivery sequencing and research
spikes are not architectural decisions and are not kept as ADRs. ADR 0006
remains the rationale for separating internal rules from public codes, while
ADR 0007 supersedes part of its original proof semantics.

## ADR standard

New ADRs must contain:

- status, date, and explicit amendment relationships;
- the durable problem that cannot be understood from current code alone;
- the chosen constraint and material rejected alternative;
- operational or architectural consequences.

Keep campaign results, research catalogs, implementation checklists, version
changelogs, and duplicated contract text out of ADRs. Store temporary evidence
under gitignored `.logs/` and promote only conclusions that still constrain
future changes.

Use `Accepted`, `Superseded`, or `Historical` as the primary status. Express
partial changes through `Amends`, `Amended by`, `Supersedes`, and `Superseded
by` metadata, with both ADRs recording the relationship.
