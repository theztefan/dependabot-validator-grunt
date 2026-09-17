# Documentation

Dependabot Validator Grunt is a read-only CLI. It collects trusted Dependabot
and repository evidence, uses deterministic rules first, calls a bounded
Copilot investigator only when needed, optionally challenges that finding with
a no-tool judge, and writes local reports.

## Minimum reading path

| Need | Read |
|---|---|
| Run the product | [`../README.md`](../README.md) |
| Find the owner of a change | [`architecture.md`](architecture.md) |
| Set up the repository and run checks | [`development.md`](development.md) |
| Change workflow behavior or safety | [`workflow-contract.md`](workflow-contract.md) |
| Change one implementation boundary | The matching reference below |
| Change an architectural decision | [`decisions/README.md`](decisions/README.md) |

Do not read every reference, ADR, lesson, or historical plan by default.
Current contracts define what the system does. ADRs explain why selected
constraints exist. `.logs/` contains local execution history and research and
is not published product documentation.

## Public writing conventions

- Explain the product and architecture in implementation-neutral terms.
- Name a language, package manager, hosting platform, or SDK only when the
  behavior is specific to that boundary.
- Keep commands single-line and portable; describe credential configuration
  separately instead of embedding shell-specific environment syntax.
- Expand uncommon abbreviations and prefer `investigator` or `model-assisted`
  over ambiguous terms such as `agentic`.
- Do not include private links, internal service names, restricted procedures,
  credentials, or local execution history.

## Focused implementation references

`reference/` is intentionally retained. These pages explain durable mechanics
that are too detailed for the architecture overview and are not normative
workflow rules. A reference page should have one concrete owner, a focused
maintenance audience, and enough stable detail to keep the workflow contract
readable. Merge or remove a page when it merely repeats a contract, ADR, or
source listing.

| Topic | Primary owner | Why it remains separate |
|---|---|---|
| [Public GitHub API and immutable snapshots](reference/github-api.md) | `github.py` maintainers | External API, redirect, archive, and extraction mechanics |
| [npm, Yarn, and pnpm evidence](reference/npm-evidence.md) | JavaScript package-manager collectors | Lockfile semantics and proof limits |
| [pip, Poetry, and uv evidence](reference/python-evidence.md) | Python package-manager collectors | Packaging standards, identity mapping, and partial graph semantics |
| [Repository reads and reference scans](reference/repository-evidence.md) | `agentic.py` and snapshot maintainers | Shared file controls, coverage, caching, and reference-scan limits |
| [Copilot, tools, analyzer, and permission boundary](reference/copilot-boundary.md) | Copilot and reachability maintainers | SDK lifecycle, tool isolation, analyzer execution, and output validation |
| [Investigator capabilities and evaluation](reference/agent-capabilities.md) | Capability and evaluation maintainers | Extension procedure, provenance, and non-authoritative quality checks |
| [Artifacts and offline fixture formats](reference/artifacts.md) | Reporting and fixture maintainers | File layout, schema projection, and fixture conventions |

## Current support

- GitHub Enterprise Cloud;
- npm `package-lock.json` versions 1, 2, and 3; version 1 is positive-only;
- Yarn Classic lockfile version 1;
- pnpm lockfile version 9.0;
- partial manifest-only evidence when the selected project has no lockfile.
- exact selected pip requirements pins;
- Poetry lock formats 1.1 and 2.1;
- non-workspace uv lock major version 1 with understood revisions.

Python deterministic evidence is positive-only. Poetry and uv may add recorded
candidate paths, and pip may add include or `# via` provenance, without
claiming an active environment or complete graph. Inconclusive evidence may use
the investigator with the selected Python capability and four bounded tools for
positive-use analysis
with task-bound structural import evidence, without package execution,
approval permissions, or negative proof. Evidence,
agent-task, and report formats are version `3.0`. When onboarding another
language ecosystem, assess the collector and any concrete language-specific
usage semantics separately. See
[`architecture.md`](architecture.md#package-manager-strategy).

## Source-of-truth rule

- `workflow-contract.md` defines current behavior, permissions, failures, and
  publication safety.
- `architecture.md` defines current module ownership and trust boundaries.
- Reference pages explain durable implementation mechanics without redefining
  behavior or rationale.
- The [ADR index](decisions/README.md) identifies applicable and historical
  decisions. Later amendments take precedence.
- `.logs/` is local execution history, not product documentation.
