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

## Detailed references

| Topic | Reference |
|---|---|
| Live GitHub API and immutable snapshots | [`reference/live-ghec.md`](reference/live-ghec.md) |
| npm, Yarn, and pnpm evidence | [`reference/npm-evidence.md`](reference/npm-evidence.md) |
| Repository reads and reference scans | [`reference/repository-evidence.md`](reference/repository-evidence.md) |
| Copilot, tools, analyzer, and permission boundary | [`reference/copilot-boundary.md`](reference/copilot-boundary.md) |
| Artifacts and offline fixture formats | [`reference/artifacts.md`](reference/artifacts.md) |

## Current support

- GitHub Enterprise Cloud;
- npm `package-lock.json` versions 2 and 3;
- Yarn Classic lockfile version 1;
- pnpm lockfile version 9.0;
- partial manifest-only evidence when the selected project has no lockfile.

When onboarding a new language ecosystem, assess both its dependency collector
and whether the JavaScript/TypeScript structural analyzer needs a concrete
ecosystem-specific extension. See
[`architecture.md`](architecture.md#package-manager-strategy).

## Source-of-truth rule

- `workflow-contract.md` defines current behavior, permissions, failures, and
  publication safety.
- `architecture.md` defines current module ownership and trust boundaries.
- Reference pages explain mechanics without redefining behavior.
- The [ADR index](decisions/README.md) identifies applicable and historical
  decisions. Later amendments take precedence.
- `.logs/` is local execution history, not product documentation.
