# Architecture

## Purpose

Dependabot Validator Grunt is a Python CLI. Its job is to turn one Dependabot alert and one
repository snapshot into a validated report.

The architecture separates trusted facts from model reasoning:

```text
GitHub or offline fixture
        |
        v
trusted collection and typed evidence
        |
        v
deterministic baseline and routing
        |
        +-------------------- terminal result -------------------+
        |                                                        |
        v                                                        v
bounded investigator -> no-tool judge -> deterministic reconciliation
        |                                                        |
        +--------------------- validated result -----------------+
                                 |
                                 v
                         atomic local publication
```

## Trust boundaries

| Boundary | Can do | Cannot do |
|---|---|---|
| GitHub client | Read approved public API endpoints and download one commit tarball | Write to GitHub or follow arbitrary redirects |
| Collectors | Read bounded snapshot files and build typed facts | Run repository code, package managers, lifecycle scripts, or registry requests |
| Investigator | Use four bounded read-only tools over the snapshot | Use shell, writes, GitHub, arbitrary network, MCP, repository instructions, or new tools |
| Judge | Review compact validated context with two critic lenses | Read repository files, call tools, or create new evidence |
| Deterministic engine | Route, prove predicates, validate permissions, and reconcile | Perform I/O or trust model prose |
| Reporter | Render validated data and atomically publish local files | Publish partial authoritative reports or write outside the selected output |

Deterministic application code is the final authority. Prompts can guide investigation,
but they cannot grant a permission or make a final decision.

## Module ownership

```text
src/dependabot_validator_grunt/
  main.py              CLI parsing, dotenv loading, dependency construction
  workflow.py          end-to-end orchestration and stage failures
  models.py            frozen evidence, task, finding, judge, and result models

  github.py            read-only GitHub API and immutable tarball extraction
  npm.py               project selection and npm-ecosystem collector dispatch
  dependency_graph.py  manager-neutral dependency graph projection
  yarn.py              bounded Yarn Classic v1 parser
  pnpm.py              bounded pnpm lockfile v9.0 parser
  python_dependencies.py  explicit Python collector dispatch
  pip_dependencies.py     bounded requirements-file evidence
  poetry_dependencies.py  Poetry declarations, lock records, and candidate graph
  uv_dependencies.py      uv declarations, lock records, and candidate graph
  unsupported_python_dependencies.py  declaration-only unsupported manifests
  python_dependency_common.py  shared Python path and graph projection helpers
  python_imports.py      reviewed distribution-to-import target mapping
  dependency_files.py  stable bounded dependency-file reads
  dependency.py        ecosystem-specific identity and version evaluation

  policy.py            versioned policy loading and validation
  deterministic.py     pure routing, proof, permission, and reconciliation logic

  agentic.py              bounded repository tools, citations, and reference evidence
  reachability.py         public runner, result coordination, and explicit profile dispatch
  reachability_ast_grep.py  trusted staging, config, subprocess, bounds, and citations
  reachability_npm.py     npm JavaScript/TypeScript result interpretation
  reachability_python.py  Python result interpretation
  copilot_tools.py        typed SDK tool schemas and handlers
  copilot_assets.py       strict package-data loading and validation
  agent_capabilities.py   ecosystem capabilities and provenance
  agent_evaluation.py     local non-authoritative investigator evaluation
  copilot.py              Copilot SDK client, session, retry, and model lifecycle
  judge.py                no-tool two-critic review and replacement validation

  reporting.py         JSON/Markdown rendering and atomic local publication
  policies/            versioned policy data
  agents/              custom-agent identity and role package data
  system-prompts/      session-wide trust instructions
  prompts/             task-dispatch template
  skills/              investigation methodology package data
  tools/               model-facing tool metadata
```

Keep responsibilities concrete. Add a protocol only at a real external
boundary that needs an offline fake or a second implementation.

## End-to-end flow

1. `main.py` validates CLI combinations, loads the two allowed dotenv keys, and
   constructs GitHub and Copilot dependencies.
2. `workflow.py` collects the request or alert and an immutable repository
   snapshot.
3. `workflow.py` explicitly dispatches the alert to npm or Python collection.
   `npm.py` selects npm, Yarn, or pnpm evidence. `python_dependencies.py`
   explicitly selects `pip_dependencies.py`, `poetry_dependencies.py`,
   `uv_dependencies.py`, or declaration-only unsupported-manifest handling
   from the attested path.
4. Collectors produce `DependencyEvidence` with explicit proof capabilities.
   Partial data is represented as partial data, not guessed into completeness.
   Poetry and uv may add bounded recorded candidate paths; pip includes and
   `# via` comments remain separate non-authoritative provenance.
5. `deterministic.py` computes a baseline. Lifecycle results and supported
   terminal proofs stop here.
6. If analysis is required, `workflow.py` creates one bounded `AgentTask`.
7. `agent_capabilities.py` exhaustively selects one versioned ecosystem
   capability from the task. `copilot.py` starts the single investigator with
   that packaged skill and the fixed four-tool
   allowlist. npm must invoke the
   structural analyzer. Python must invoke it when the task has an
   authoritative import target; tasks without one may receive an inapplicable
   or advisory result. The public reachability runner coordinates one trusted
   ast-grep mechanics boundary with a direct `npm` or `python` interpretation
   branch. The analyzer stages bounded readable text, lets the pinned engine
   infer languages from paths, and runs only the application-selected
   operation profile. Trusted interpretation registers findings only for that
   profile's language family. Structural execution is scoped to the selected
   manifest directory and batches only profile-relevant paths under shared
   aggregate limits. Workflow orchestration validates required invocation and
   task/profile/project binding after every model-turn implementation returns;
   the real Copilot boundary repeats the check inside each attempt for retry
   classification.
8. Trusted handlers validate every observation, citation, identity, and
   proposed recommendation/code pair.
9. For real Copilot findings, `judge.py` runs one no-tool review containing an
   evidence critic and an applicability critic. Judge failure is recorded but
   does not discard a valid primary finding.
10. `deterministic.py` re-proves the final predicate and reconciles the result.
11. `workflow.py` rechecks mutable GitHub state.
12. `reporting.py` writes local artifacts atomically, publishing
    authoritative `report.json` last.

## Package-manager strategy

npm package-lock v2/v3 has mature complete-inventory, consumer, and
development-scope capabilities. Legacy package-lock v1 is supported with
positive-instance authority only.

Yarn Classic v1 and pnpm v9.0 deliberately start with narrower authority. They
may prove that a referenced, registry-backed, comparable vulnerable instance
exists. They cannot prove that a package is absent, unaffected, unused, or
development-only. This staged design prevents a parser omission from becoming
a false negative security decision.

pip, Poetry, and uv follow the same positive-only principle. They accept only
the narrowly defined records in
[`reference/python-evidence.md`](reference/python-evidence.md), grant only
`resolved_instances`, and keep positive vulnerable triage records terminal.
Poetry and uv candidate paths improve investigation without proving an active
environment or transitive symbol execution; pip provenance never becomes graph
authority. Inconclusive records may use the investigator with the
application-selected Python capability for positive-use evidence. It has the same
four-tool allowlist as the npm capability and can call the task-bound analyzer
for validated Python import targets, but has no repository-reference absence
proof, approval permission, or authority to prove non-use. Valid real-model
findings may still receive the shared no-tool judge review. Evidence, task,
and report formats are version `3.0`.

Explicit ecosystem dispatch is preferred over a collector registry. Add a
shared abstraction only when another concrete implementation needs it. A new
language-specific analyzer remains a separate architectural decision.

## Model-facing assets

Assets under `agents/`, `system-prompts/`, `prompts/`, `skills/`, and `tools/`
are package data, never Python code:

- the system prompt states session-wide trust rules;
- the custom-agent prompt states the role and output contract;
- the skill states reusable investigation methodology;
- the task prompt carries only the validated task;
- tool metadata describes operations, while application code owns schemas and
  handlers.

The runtime uses one investigator identity plus the judge. Trusted application code
selects the npm or Python capability, analyzer profile, and skill. The
investigator always has the same four bounded repository tools. Task data and
deterministic validation keep ecosystem evidence authority separate; the
judge has no tools.

Automatic repository, user, plugin, hook, instruction, MCP, and skill discovery
is disabled. See [`reference/copilot-boundary.md`](reference/copilot-boundary.md).

`agent_evaluation.py` is a development and release-quality boundary, not
workflow authority. It runs the current investigator against versioned local
cases and writes a non-authoritative quality summary.
Extension procedures are in
[`reference/agent-capabilities.md`](reference/agent-capabilities.md).

## Extending the solution

Prefer the smallest owner:

1. Change policy JSON for routes, limits, or permitted outcomes.
2. Change deterministic application code for a new trusted predicate.
3. Change a collector for new evidence.
4. Change a skill for investigation method.
5. Change a prompt only for model-facing wording.
6. Add a module when a new runtime responsibility is concrete.
7. Add another agent or abstraction only after one role is no longer enough.

Workflow behavior must first be defined in
[`workflow-contract.md`](workflow-contract.md). Changes to module ownership,
permissions, validation, or publication policy require an ADR.
