# Dependabot Validator Grunt

Dependabot Validator Grunt is a local Python CLI that reviews one Dependabot
dismissal request or triages one Dependabot alert.

It is read-only. It collects evidence, may ask GitHub Copilot to investigate,
and writes a local report. It never dismisses an alert, changes a repository,
opens a pull request, or publishes a decision to GitHub.

## Supported workflows

| Command | Result |
|---|---|
| `review-dismissal` | Recommends `approve`, `deny`, or `human_review`, or reports that the request is no longer actionable |
| `triage-alert` | Classifies an alert as `applies`, `does_not_apply`, or `human_review` and recommends an action |

The live adapter supports GitHub Enterprise Cloud and the npm ecosystem:

- npm `package-lock.json` versions 2 and 3;
- Yarn Classic `yarn.lock` version 1;
- pnpm `pnpm-lock.yaml` version 9.0;
- a selected `package.json` without a lockfile, as partial declaration evidence.

Yarn and pnpm currently prove only positive vulnerable instances. They do not
prove package absence, unaffected versions, development-only installation, or
unused vulnerable symbols.

## How a run works

```text
validate input and policy
  -> collect the Dependabot item and an immutable repository snapshot
  -> select the alert's project and lockfile adapter
  -> build typed evidence with explicit proof capabilities
  -> compute a deterministic baseline
  -> publish a terminal result, or run a bounded Copilot investigation
  -> optionally challenge the finding with a no-tool two-critic judge
  -> reconcile the final result in deterministic Python
  -> recheck GitHub state and atomically write local artifacts
```

Deterministic Python owns every final decision. The investigator can use only
four bounded, read-only tools:

- `list_files`;
- `read_file`;
- `search`;
- `analyze_reachability`, an application-controlled ast-grep analysis.

The judge is a separately packaged custom agent with its own review skill. Its
manifest and session expose no tools or repository access, so it reviews only
compact, previously validated evidence. Model output is always treated as
untrusted input.

## Set up

```bash
uv sync --all-groups --locked
uv run python -m copilot download-runtime
```

## Run offline examples

Offline fixtures require no credentials:

```bash
uv run dependabot-validator-grunt review-dismissal \
  --offline-fixture examples/offline-cases/not-used-absent

uv run dependabot-validator-grunt triage-alert \
  --offline-fixture examples/offline-cases/triage-vulnerable
```

Fixtures use their scripted model response when analysis is required. Add
`--model <runtime-model-id>` and set `COPILOT_GITHUB_TOKEN` to use real Copilot
instead.

## Run against GitHub Enterprise Cloud

```bash
DEPENDABOT_GITHUB_TOKEN=<github-token> \
COPILOT_GITHUB_TOKEN=<copilot-token> \
uv run dependabot-validator-grunt review-dismissal \
  --request https://github.com/OWNER/REPO/security/dependabot/ALERT_NUMBER

DEPENDABOT_GITHUB_TOKEN=<github-token> \
COPILOT_GITHUB_TOKEN=<copilot-token> \
uv run dependabot-validator-grunt triage-alert \
  --repo OWNER/REPO \
  --alert ALERT_NUMBER
```

`COPILOT_GITHUB_TOKEN` is needed only when trusted routing selects an agentic
path. One token value may serve both roles when it has both capabilities, but
separate least-privileged credentials are safer.

The installed CLI reads only these two keys from `./.env`. Exported environment
variables take precedence.

Reports are written under `./reports` by default. Use `--output <directory>` or
`--policy <file>` to override the output directory or policy.

```bash
uv run dependabot-validator-grunt --help
uv run dependabot-validator-grunt --version
```

## Change the solution

Change the smallest owner:

| Concern | Owner |
|---|---|
| CLI parsing and dependency construction | `main.py` |
| Workflow orchestration | `workflow.py` |
| Evidence and result schemas | `models.py` |
| npm ecosystem collection | `npm.py`, `yarn.py`, `pnpm.py`, `dependency_graph.py` |
| Deterministic policy and reconciliation | `deterministic.py`, `policies/default.json` |
| Repository evidence and reachability | `agentic.py`, `reachability.py` |
| Copilot and judge lifecycle | `copilot.py`, `judge.py` |
| Report rendering and publication | `reporting.py` |
| Model-facing role, prompt, skill, and tool descriptions | package data under `agents/`, `system-prompts/`, `prompts/`, `skills/`, and `tools/` |

Policy, permissions, validation, and final decisions belong in Python or
versioned policy JSON, not in prompts.

Run the complete baseline after changes:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv build
```

## Documentation

- [`docs/README.md`](docs/README.md) — documentation map
- [`docs/architecture.md`](docs/architecture.md) — modules and trust boundaries
- [`docs/workflow-contract.md`](docs/workflow-contract.md) — authoritative behavior
- [`docs/development.md`](docs/development.md) — setup and development workflow
- [`docs/decisions/`](docs/decisions/) — architectural decision records
