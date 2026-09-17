# Investigator capabilities

The application has one investigator and one optional judge.

Before the investigator runs, trusted application code selects an ecosystem capability
from `agents/investigator-capabilities.json`:

| Ecosystem | Capability | Skill | Analyzer |
|---|---|---|---|
| npm | `javascript-typescript-v1` | `javascript-typescript-dependency-risk-analysis` | `npm` |
| pip or uv | `python-v1` | `python-dependency-risk-analysis` | `python` |

A capability selects methodology. It cannot add tools, permissions, evidence
authority, policy outcomes, or publication rights.

## Runtime

The investigator always uses:

- agent `dependency-risk-investigator`;
- prompt `agents/dependency-risk-investigator/prompt.md`;
- tools `list_files`, `read_file`, `search`, and `analyze_reachability`;
- deny-by-default permissions;
- strict finding and citation validation;
- deterministic reconciliation.

The selected capability supplies one skill and one analyzer profile. Missing
SDK identity events are diagnostics. Reported extra tools, unexpected enabled
skills, agent deselection, or conflicting runtime agent IDs fail the run.

Real Copilot findings may be reviewed by the no-tool judge. The judge is
created only after the primary finding and required reachability evidence
validate. Judge failure keeps the valid primary finding.

## Ownership

| Change | Owner |
|---|---|
| Ecosystem routing | `workflow.py`, `models.py`, and the concrete collector |
| Capability selection and provenance | `agent_capabilities.py` |
| Capability data | `agents/investigator-capabilities.json` |
| Agent and skill loading | `copilot_assets.py` |
| SDK lifecycle, tools, permissions, retries | `copilot.py` |
| Analyzer coordination | `reachability.py` |
| Analyzer execution, bounds, and citations | `reachability_ast_grep.py` |
| Language-family interpretation | `reachability_<ecosystem>.py` |
| Investigation method | `skills/<skill-name>/SKILL.md` |
| Judge behavior | `judge.py` and judge package data |
| Evaluation | `agent_evaluation.py` |

## Add a package manager

1. Add its typed collector and explicit dispatch branch.
2. Define which evidence is authoritative.
3. Map it to an existing ecosystem capability when the language semantics are
   unchanged.
4. Add collector, workflow, provenance, and evaluation tests.

## Add an ecosystem

1. Define the workflow and evidence rules in `workflow-contract.md`.
2. Add the ecosystem, package manager, analysis family, and version routing as
   exhaustive typed branches.
3. Add the collector and deterministic rules.
4. Add an analyzer profile only when structural semantics differ.
5. Add one skill and one capability entry.
6. Add production-shaped fixtures and evaluation cases.

Do not add another investigator unless it needs different tools, permissions,
or a different response contract.

## Change a skill or capability

1. Keep policy and tool behavior in deterministic application code, not skill
   prose.
2. Update the skill or capability entry.
3. Increment `capability_version` for a semantic change.
4. Update package-data and provenance tests.
5. Run the evaluation suite.

## Evaluate the investigator

Each manifest case has a unique `case_id`, a relative fixture path, and an
expected result. Run:

```text
uv run dependabot-validator-grunt evaluate-agent-capabilities --manifest examples/offline-cases/capability-evaluation.json
```

The command runs each case once through the current investigator boundary.
Without `--model`, it loads and renders the selected packaged agent, prompt,
and skill, then replays `agent-response.json` as the model output. With
`--model`, it uses those same assets in a fresh real Copilot boundary and lazy
judge.

Results are written to:

```text
agent-evaluations/<evaluation-id>/
  evaluation.json
  cases/<case-id>/...workflow artifacts...
```

`evaluation.json` is always non-authoritative. Exit `9` means a case failed or
did not match its expected result.

Each result records elapsed time, classified investigator attempts, and
analyzer metrics when structural analysis ran: authoritative import-target
count, selected project root, status, profile candidate/staged/skipped files,
staged bytes, completed operations, and finding count. Token and cost fields
remain nullable until the SDK exposes trusted values. Use these metrics to
attribute regressions to collection, profile coverage, analyzer bounds, model
formatting, or judging rather than increasing limits without evidence.
