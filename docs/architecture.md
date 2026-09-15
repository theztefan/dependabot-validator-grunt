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
| GitHub client | Read approved GHEC endpoints and download one commit tarball | Write to GitHub or follow arbitrary redirects |
| Collectors | Read bounded snapshot files and build typed facts | Run repository code, package managers, lifecycle scripts, or registry requests |
| Investigator | Use four bounded read-only tools over the snapshot | Use shell, writes, GitHub, arbitrary network, MCP, repository instructions, or new tools |
| Judge | Review compact validated context with two critic lenses | Read repository files, call tools, or create new evidence |
| Deterministic engine | Route, prove predicates, validate permissions, and reconcile | Perform I/O or trust model prose |
| Reporter | Render validated data and atomically publish local files | Publish partial authoritative reports or write outside the selected output |

Deterministic Python is the final authority. Prompts can guide investigation,
but they cannot grant a permission or make a final decision.

## Module ownership

```text
src/dependabot_validator_grunt/
  main.py              CLI parsing, dotenv loading, dependency construction
  workflow.py          end-to-end orchestration and stage failures
  models.py            frozen evidence, task, finding, judge, and result models

  github.py            read-only GHEC API and immutable tarball extraction
  npm.py               project selection and npm-ecosystem collector dispatch
  dependency_graph.py  manager-neutral dependency graph projection
  yarn.py              bounded Yarn Classic v1 parser
  pnpm.py              bounded pnpm lockfile v9.0 parser

  policy.py            versioned policy loading and validation
  deterministic.py     pure routing, proof, permission, and reconciliation logic

  agentic.py           bounded repository tools, citations, and reference evidence
  reachability.py      application-controlled ast-grep subprocess boundary
  copilot_tools.py     typed SDK tool schemas and handlers
  copilot_assets.py    strict package-data loading and validation
  copilot.py           Copilot SDK client, session, retry, and model lifecycle
  judge.py             no-tool two-critic review and replacement validation

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
3. `npm.py` selects only the project named by the alert manifest and dispatches
   to npm, Yarn, or pnpm parsing.
4. Collectors produce `NpmEvidence` with explicit proof capabilities. Partial
   data is represented as partial data, not guessed into completeness.
5. `deterministic.py` computes a baseline. Lifecycle results and supported
   terminal proofs stop here.
6. If analysis is required, `workflow.py` creates one bounded `AgentTask`.
7. `copilot.py` starts a session with one custom agent, one packaged skill, and
   exactly four tools. Each attempt must invoke the structural analyzer.
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
development-scope capabilities.

Yarn Classic v1 and pnpm v9.0 deliberately start with narrower authority. They
may prove that a referenced, registry-backed, comparable vulnerable instance
exists. They cannot prove that a package is absent, unaffected, unused, or
development-only. This staged design prevents a parser omission from becoming
a false negative security decision.

Adding another JavaScript package manager may reuse the current structural
analyzer, but adding a new language ecosystem is not only a collector change.
It usually requires ecosystem-specific proof capabilities and an extension or
replacement for the JavaScript/TypeScript ast-grep adapter. Add that concrete
boundary only when the ecosystem is implemented; do not introduce a
speculative analyzer framework.

## Model-facing assets

Assets under `agents/`, `system-prompts/`, `prompts/`, `skills/`, and `tools/`
are package data, never Python code:

- the system prompt states session-wide trust rules;
- the custom-agent prompt states the role and output contract;
- the skill states reusable investigation methodology;
- the task prompt carries only the validated task;
- tool metadata describes operations, while Python owns schemas and handlers.

The investigator and judge each have their own explicit manifest, role prompt,
skill, system trust prompt, and task template. They share asset-loading and
runtime-validation mechanics, but not capabilities: the investigator has four
bounded repository tools and the judge has none.

Automatic repository, user, plugin, hook, instruction, MCP, and skill discovery
is disabled. See [`reference/copilot-boundary.md`](reference/copilot-boundary.md).

## Extending the solution

Prefer the smallest owner:

1. Change policy JSON for routes, limits, or permitted outcomes.
2. Change deterministic Python for a new trusted predicate.
3. Change a collector for new evidence.
4. Change a skill for investigation method.
5. Change a prompt only for model-facing wording.
6. Add a module when a new runtime responsibility is concrete.
7. Add another agent or abstraction only after one role is no longer enough.

Workflow behavior must first be defined in
[`workflow-contract.md`](workflow-contract.md). Changes to module ownership,
permissions, validation, or publication policy require an ADR.
