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
| `evaluate-agent-capabilities` | Runs the current investigator against local fixtures and writes a non-authoritative quality summary |

The live adapter supports GitHub Enterprise Cloud and these dependency inputs:

- npm `package-lock.json` versions 1, 2, and 3; version 1 is positive-only;
- Yarn Classic `yarn.lock` version 1;
- pnpm `pnpm-lock.yaml` version 9.0;
- a selected `package.json` without a lockfile, as partial declaration evidence.
- pip requirements files with one exact, unmarked target pin;
- Poetry projects with lock formats 1.1 and 2.1, including PEP 621-only
  Poetry 2 metadata;
- non-workspace uv projects with lock major version 1 and understood revisions.

Yarn, pnpm, pip, Poetry, and uv currently grant positive-instance authority
only. They do not prove package absence, unaffected versions,
development-only installation, or unused vulnerable symbols. Poetry and uv
also record bounded candidate dependency paths, while pip includes and
`# via` annotations remain non-authoritative provenance rather than graph
edges. Positive Python triage results are terminal; inconclusive Python routes
may enter the shared investigator with an application-selected Python capability that
can identify positive repository use through same-name or reviewed curated
import targets but cannot prove non-use.

Here, **positive-only** means the tool may confirm a supported vulnerable
instance but cannot turn missing or incomplete evidence into a safe negative
conclusion. A **terminal** result is complete without model-assisted
investigation.

## How a run works

```text
validate input and policy
  -> collect the Dependabot item and an immutable repository snapshot
  -> select the alert's project and lockfile adapter
  -> build typed evidence with explicit proof capabilities
  -> compute a deterministic baseline
  -> publish a terminal result, or run a bounded Copilot investigation
  -> optionally challenge the finding with a no-tool two-critic judge
  -> reconcile the final result in deterministic application code
  -> recheck GitHub state and atomically write local artifacts
```

Deterministic application code owns every final decision. The runtime uses one
investigator with an application-selected npm or Python capability. It can use four
bounded, read-only tools:

- `list_files`;
- `read_file`;
- `search`;
- `analyze_reachability`, an application-controlled ast-grep analysis.

Every capability receives the same four-tool allowlist. The structural
analyzer derives the selected project from the alert manifest and processes
only pinned-engine JavaScript/TypeScript or Python profile files in bounded
batches. Other repository text remains available to list, read, and search
tools. Python analyzer targets are derived only from validated same-name or
reviewed curated task targets. Positive authoritative Python import/load
findings can support applicability only for targets without a known competing
distribution; colliding namespaces remain advisory. Parent-only use, unmapped
distribution/import mismatches, no-match, incomplete, or advisory-target
results cannot prove non-use or authorize approval. It never executes Python,
package managers, or build backends.

The judge is a separately packaged custom agent with its own review skill. Its
manifest and session expose no tools or repository access, so it reviews only
compact, previously validated evidence. Model output is always treated as
untrusted input.

## Set up

```text
uv sync --all-groups --locked
uv run python -m copilot download-runtime
```

## Run offline examples

Offline fixtures require no credentials:

```text
uv run dependabot-validator-grunt review-dismissal --offline-fixture examples/offline-cases/not-used-absent
uv run dependabot-validator-grunt triage-alert --offline-fixture examples/offline-cases/triage-vulnerable
```

Fixtures use their scripted model response when analysis is required. Add
`--model <runtime-model-id>` and set `COPILOT_GITHUB_TOKEN` to use real Copilot
instead.

Evaluate the current investigator:

```text
uv run dependabot-validator-grunt evaluate-agent-capabilities --manifest examples/offline-cases/capability-evaluation.json
```

The evaluator runs each case once and writes isolated workflow artifacts plus
an `authoritative: false` `evaluation.json`. It returns exit `9` when a case
fails or misses its expected result.

Production-shaped Python examples include:

- `python-poetry-transitive-import` — recorded transitive path plus an
  authoritative same-name Python import;
- `python-uv-parent-only` — parent use remains human review rather than target
  reachability;
- `python-pip-compile-provenance` — exact pin and `# via` provenance without
  graph authority;
- `python-distribution-import-mismatch` — a reviewed
  `PyYAML`/`yaml` mapping supports authoritative positive use.

Successful runs serialize evidence, agent tasks when present, and reports with
format/schema version `3.0`.

## Run against GitHub Enterprise Cloud

Add `DEPENDABOT_GITHUB_TOKEN` to `./.env`. Add `COPILOT_GITHUB_TOKEN` only
when the selected route may use Copilot, then run:

```text
uv run dependabot-validator-grunt review-dismissal --request https://github.com/OWNER/REPO/security/dependabot/ALERT_NUMBER
uv run dependabot-validator-grunt triage-alert --repo OWNER/REPO --alert ALERT_NUMBER
```

`COPILOT_GITHUB_TOKEN` is needed only when trusted routing selects an investigator
path. One token value may serve both roles when it has both capabilities, but
separate least-privileged credentials are safer.

The installed CLI reads only these two keys from `./.env`. Existing process
environment values take precedence.

Reports are written under `./reports` by default. Use `--output <directory>` or
`--policy <file>` to override the output directory or policy.

```text
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
| Python ecosystem dispatch and collection | `python_dependencies.py`, `pip_dependencies.py`, `poetry_dependencies.py`, `uv_dependencies.py`, `unsupported_python_dependencies.py`, `python_dependency_common.py`, `dependency_files.py`, `dependency.py` |
| Deterministic policy and reconciliation | `deterministic.py`, `policies/default.json` |
| Repository evidence and structural analysis | `agentic.py`, `reachability.py`, `reachability_ast_grep.py`, `reachability_npm.py`, `reachability_python.py` |
| Copilot and judge lifecycle | `copilot.py`, `judge.py` |
| Investigator capabilities, provenance, and evaluation | `agent_capabilities.py`, `agent_evaluation.py`, `agents/investigator-capabilities.json` |
| Report rendering and publication | `reporting.py` |
| Model-facing role, prompt, skill, and tool descriptions | package data under `agents/`, `system-prompts/`, `prompts/`, `skills/`, and `tools/` |

Policy, permissions, validation, and final decisions belong in deterministic
application code or versioned policy data, not in prompts.

Run the complete baseline after changes:

```text
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
- [`docs/reference/agent-capabilities.md`](docs/reference/agent-capabilities.md) — investigator capabilities, evaluation, and extension procedures
- [`docs/decisions/`](docs/decisions/) — architectural decision records
