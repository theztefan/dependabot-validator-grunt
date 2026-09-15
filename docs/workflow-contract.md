# Workflow contract

- **Status:** Accepted and implemented
- **Last updated:** 2026-09-14
- **Platform:** GitHub Enterprise Cloud
- **Ecosystem:** npm
- **Publication:** Local artifacts only
- **Default policy:** `default-npm-dismissal` version `2.0.0`
- **Report schema:** `1.3`
- **Evidence format:** `1.2`
- **Agent task format:** `1.3`
- **Judge review format:** `1.0`

This file is the authoritative contract for current workflow behavior,
permissions, failure handling, and publication safety. Start with
[`README.md`](README.md) for the documentation map. Detailed external and data
format references are linked where useful, but they do not override this
contract.

## Product boundary

The CLI supports two workflows:

| Workflow | Final result |
|---|---|
| Dismissal review | `approve`, `deny`, `human_review`, or a non-actionable lifecycle result |
| Alert triage | `applies`, `does_not_apply`, or `human_review` plus an action |

Both workflows:

1. collect typed npm and repository evidence;
2. run deterministic policy first;
3. use bounded agent analysis only when trusted routing marks the deterministic
   baseline as non-terminal;
4. treat model output as untrusted input;
5. reconcile the final result in deterministic Python;
6. write local JSON and Markdown artifacts.

The application does not write to GitHub, approve or deny through an API,
remediate dependencies, create pull requests, support GHES, support non-npm
ecosystems, operate a service or queue, or publish outside the selected local
output directory.

## Commands and inputs

```text
dependabot-validator-grunt review-dismissal [inputs]
dependabot-validator-grunt triage-alert [inputs]
```

| Workflow | Live input | Offline input | Agent behavior |
|---|---|---|---|
| Dismissal | `--request <GitHub URL or owner/repo#alert>` or `--repo <owner/repo> --alert <number>` | `--offline-fixture <directory>` | Deterministic routing decides whether analysis is required. Offline routes use `agent-response.json` by default; `--model` selects real Copilot instead. |
| Triage | `--repo <owner/repo> --alert <number>` | `--offline-fixture <directory>` | Deterministic `does_not_apply` is terminal. Positive-only Yarn/pnpm `applies` decisions are also terminal; npm package-lock `applies` and `human_review` baselines require a scripted or real Copilot boundary. |

Dismissal `--reason` and `--justification-file` values are operator fallbacks
only when live GitHub data omits them. They never overwrite non-empty attested
fields.

`--offline-fixture` is mutually exclusive with live target and fallback
inputs. `--model` selects real Copilot and its runtime model for an offline
fixture, overriding `agent-response.json`; it does not decide whether analysis
is required. Live workflows also accept `--model` as model selection, but
trusted routing determines whether the boundary runs.

Shared options are:

- `--output <directory>`, default `./reports`;
- `--policy <file>`, default the packaged policy.

Policy precedence is command-line file, then offline fixture `policy.json`,
then packaged default. Invalid combinations fail before collection.

## Credentials and external access

Credentials have separate roles:

- `DEPENDABOT_GITHUB_TOKEN` is used only for live GitHub collection;
- `COPILOT_GITHUB_TOKEN` is used only for real Copilot sessions.

The installed CLI parses `.env` in its current working directory before command
dispatch and imports only these two credential keys. Existing environment
variables, including empty values, take precedence and are not overwritten.
Parent-directory `.env` files and unrelated dotenv keys are ignored.

The two roles may use the same token value when one credential is authorized
for both operations. Distinct least-privileged credentials remain recommended:
reuse combines revocation, audit, exposure, and privilege blast radius.
Credentials never appear in evidence, prompts, reports, or failure artifacts.
Copilot authentication is passed through the SDK's explicit token argument;
token-named variables and unrelated environment values are not inherited by
the Copilot runtime.

Live GitHub access is read-only and limited to the publicly documented
dismissal-request, Dependabot alert, repository metadata, default-branch, and
immutable tarball endpoints. See
[`reference/live-ghec.md`](reference/live-ghec.md) for endpoint and token
requirements.

The real Copilot boundary queries available models at runtime, rejects an
unavailable explicit model, and otherwise permits runtime default selection.
Default and scripted offline paths require no credential. An offline
`--model` run requires the Copilot credential. Ambient Copilot credentials do
not replace a scripted fixture unless `--model` is supplied.

## Evidence contract

All shared workflow data uses frozen, serializable Pydantic models:

- `RequestSnapshot`: request identity, dismissal reason, exact requester
  justification, lifecycle state, expiry, response history, provenance, and
  source digest;
- `AlertSnapshot`: advisory identity and package, range, severity, scope, and
  source digest;
- `RepositorySnapshot`: owner, repository, default branch, immutable snapshot
  identity, provenance, and included/excluded path manifests;
- `NpmEvidence`: every discovered package instance, relationships, consumers,
  manifests, issues, and completeness;
- `RepositoryReferenceEvidence`: bounded package-identifier reference status,
  aggregate scan coverage, exclusions, budget use, and insufficiency reasons;
- `EvidenceBundle`: workflow identity, snapshots, evidence items, policy
  identity, and canonical digest;
- `AgentTask`: bounded context and typed permitted recommendation/code groups;
- `AgentFinding`: identity-bound claim, proposal, confidence, uncertainty,
  safety flags, and digest-bound repository citations;
- typed dismissal, lifecycle, and triage results.

Missing, partial, unsupported, contradictory, and failed evidence are explicit
states. Required nullable fields are serialized as JSON `null`; artifacts must
round-trip through their owning models.

Alert package names and repository-reference targets use one safe identifier
validation rule. They must be non-empty, at most 512 characters, unpadded,
free of control or whitespace characters, and shaped as one URL-safe npm name
or one `@scope/name` pair. Invalid offline or live alert identifiers fail at
the collection boundary, and failure text does not include the rejected value.

Offline repository snapshots use a digest of the normalized included paths and
file contents. Live snapshots use the resolved default-branch commit SHA.

The npm-ecosystem collector supports package-lock versions 2 and 3, Yarn
Classic lockfile v1, and pnpm lockfile v9.0 for the project directory identified
by the alert manifest. It normalizes only the selected project and its sibling
`package.json` and selected lockfile; it does not discover unrelated nested
projects or choose heuristically between multiple sibling lockfiles.

Evidence records the package manager, lockfile path/version, collector
capabilities, resolved instances, declarations, consumers, and limitations.
Package-lock v2/v3 retains complete-inventory authority. Initial Yarn v1 and
pnpm v9.0 adapters have positive-instance authority only: a concrete,
registry-backed, comparable vulnerable instance can prove that an alert
applies, even when the adapter reports partial graph evidence. These adapters
cannot prove package absence, unaffected versions, `vulnerable_symbol_unused`,
or `dev_only_scope`. A valid supported document with unresolved graph edges or
non-comparable sources remains partial. An unsupported version, malformed
document, ambiguous sibling lockfiles, unsafe path, invalid text, overflow, or
file drift fails the npm-evidence stage.

When the sibling lockfile is absent, the collector still parses the selected
manifest and emits typed declaration evidence for direct, development,
optional, and peer dependencies. Manifest-only evidence is partial. It can
prove what a manifest declares, including exact text, scope, and a supported
npm alias target, but cannot prove an installed version, installed absence,
transitive graph, dependency consumer, development-only installation, or
deployment state. Missing-lockfile analysis can therefore produce a valid
agent-assisted report, but cannot independently support an automated
non-applicability conclusion.

Recognized npm manifests and lockfiles are read through bounded deterministic
readers. Equality with the dependency-file limit is allowed; overflow, size
drift, undecodable text, malformed supported syntax, or an unsafe alert path
fails in the npm-evidence stage. YAML parsing rejects aliases, duplicate keys,
custom tags, excessive depth, excessive nodes, and oversized scalar values.
The collector never runs repository, package-manager, or lifecycle code and
never contacts a package registry or synthesizes a lockfile. Complete package
absence and unaffected-version conclusions continue to require explicit
complete-inventory capability.
See [`reference/npm-evidence.md`](reference/npm-evidence.md).

During archive preflight, the 32 MiB exception applies only when the final
normalized member name is a recognized dependency manifest or lockfile.
Dependency members still count toward the unchanged total expanded-archive
budget. Every other regular archive member remains subject to the ordinary
10 MiB limit, including denied and excluded paths.

Repository reference evidence is prepared only for a task that can propose
`vulnerable_symbol_unused`. It attempts every agent-readable regular repository
file as UTF-8 text regardless of extension, except exact npm lock metadata and
known binary asset formats. Agent-readable GitHub content includes
`.github/workflows/**` and `.github/actions/**`; repository-provided agent,
instruction, hook, plugin, MCP, and credential controls remain excluded.

Binary and dependency-metadata exclusions are application-owned and fixed.
`package.json` dependency identity fields are removed from reference scans,
while scripts and tool configuration remain searchable. Exact file handling is
documented in
[`reference/repository-evidence.md`](reference/repository-evidence.md).

Agent-denied files remain unavailable to Copilot and are outside reference
candidate selection. Symlinks, special files, and known binary assets are also
outside the reference scope. Unknown undecodable or NUL-containing candidates,
invalid manifests, read failures, file-size drift, or total proof-budget
exhaustion make the evidence insufficient.

Agent reads and deterministic reference scans have separate budgets. Repeated
reads of one immutable file use an attempt-local cache. Positive references
remain valid under partial coverage; absence is sufficient only after every
candidate is processed. Detailed cache, scan, and insufficiency semantics are
documented in
[`reference/repository-evidence.md`](reference/repository-evidence.md).

When an agent proposes `vulnerable_symbol_unused`, `reference_found` or
`insufficient` evidence prevents approval. Dismissal becomes `human_review`
with `agent_approval_unproven`. Triage retains the unresolved baseline
assessment, recommends `investigate`, and uses `insufficient_context`.

## Policy and decision contract

Policy JSON contains declarative routes, enabled rule IDs, limits, typed
approval-code allowlists, and a retained model-confidence reporting threshold.
Model confidence is telemetry rather than an approval veto; executable decision
logic and load-bearing proof remain in `deterministic.py`.

Default agent-analysis limits are:

| Limit | Default |
|---|---:|
| Model attempts | 2 |
| Shared wall clock | 360 seconds |
| One agent-readable file | 2 MiB |
| Results from one list/search call | 200 |
| Distinct file content per attempt | 32 MiB |
| Ordinary archive member | 10 MiB |
| Recognized dependency manifest or lockfile | 32 MiB |
| Deterministic reference scan | 64 MiB |
| Analyzer wall clock | 60 seconds |
| Analyzer staged files | 10,000 |
| Analyzer staged input | 64 MiB |
| Analyzer stdout | 4 MiB |
| Analyzer stderr | 256 KiB |
| Analyzer findings | 500 |
| Static model-facing text and metadata | 8,192 characters |

Each retry receives a fresh repository-tool budget and cache, but all retries,
client/session setup, and model work share the one wall-clock deadline. The one-file limit remains subordinate to the per-attempt content budget.
Large dependency files are represented to the model through typed summaries
rather than sent whole. Copilot session mechanics are documented in
[`reference/copilot-boundary.md`](reference/copilot-boundary.md).

The parser stores the complete successful real-model response as `raw_content`
and extracts exactly one JSON object, allowing non-authoritative surrounding
prose or Markdown. Zero or
multiple JSON objects, a non-object response, or a structured finding that
fails task identity, permission-pair, schema, or citation validation is
malformed output. Those failures may use the remaining retry budget;
deterministic reconciliation failures are not retried.

Startup validation rejects:

- duplicate entries in enabled rules, dismissal route outcome/code lists, and
  triage outcome/code lists;
- resource limits where one permitted file read exceeds the complete
  per-attempt session-byte budget;
- unknown rule IDs or dismissal reasons;
- unknown fields;
- routes that cannot produce fail-closed human review;
- agent outcomes outside the route's final outcomes;
- agent approval permissions without canonical approval codes;
- `tolerable_risk` approval;
- enabled deterministic denials whose routes forbid denial;
- triage without human review;
- noncanonical triage approval codes.

Internal enabled-rule IDs may differ from published reason codes:

| Internal rule | Published result code |
|---|---|
| `approve_package_absent` | `dependency_no_longer_present` |
| `approve_unaffected_versions` | `version_not_affected` |

### Dismissal routing

| Reason | Default behavior |
|---|---|
| `fix_started` | Deterministic `deny` |
| `no_bandwidth` | Deterministic `deny` |
| `not_used` | Deterministic non-applicability proof, otherwise agent analysis |
| `inaccurate` | Deterministic non-applicability proof, otherwise denial or human review |
| `tolerable_risk` | Agent denial or human review; never automated approval |
| unknown | `human_review` |

Complete package absence or proof that every installed instance is unaffected
can approve `not_used` or `inaccurate`. For `not_used`, the only agent approval
code is `vulnerable_symbol_unused`; its trusted predicate is independently
re-proven before acceptance through npm relationships, dependency consumers,
and bounded repository reference evidence. The code is retained for
compatibility; it establishes sufficient absence of the package identifier in
usage-bearing repository text, not formal semantic proof that every vulnerable
symbol is unreachable.

The default `inaccurate` route has no agent approval code. The default
`tolerable_risk` route has no approval outcome. Package absence or unaffected
versions remain attached as audit context when a tolerable-risk request
escalates, but they do not approve that reason.

Permitted dismissal denial codes are:

- `advisory_applies`;
- `decommission_not_valid`;
- `reason_justification_mismatch`;
- deterministic `deny_fix_started` and `deny_no_bandwidth`.

`reachable_and_exploitable`, `preconditions_not_met`, and
`false_positive_confirmed` are recognized decision-tree claims but are not
permitted outcomes. The current evidence model cannot independently prove
them, so proposals using them fail closed.

### Triage routing

Priority begins as alert severity.

| Deterministic evidence | Result |
|---|---|
| Complete package absence | `does_not_apply` / `none` |
| Every installed instance proven unaffected | `does_not_apply` / `none` |
| Evidence authorized for resolved-instance proof with at least one vulnerable instance | `applies` / `remediate` |
| Partial, unsupported, or inconclusive evidence | `human_review` / `investigate` |

Deterministic `does_not_apply` decisions are terminal. An `applies` decision
from a positive-evidence-only Yarn or pnpm adapter is also terminal because
those adapters cannot authorize an agentic non-applicability exception.
`human_review` and npm package-lock `applies` baselines require bounded agent
verification in live or offline runs. The mature npm path retains agentic
verification because its complete consumer and development-scope evidence can
support authorized `vulnerable_symbol_unused` or `dev_only_scope` outcomes.
This routing is owned by workflow logic and is not disabled by a command-line
option or triage policy outcome allowlist.

Live runs use the real Copilot boundary when required. Missing credentials on
that evidence-dependent route fail as a configuration error. Credential and
explicit-model validation are deferred until the workflow selects the route,
so a deterministic terminal run does not require or validate a model.

Offline fixtures use an explicitly supplied model turn first, then
`agent-response.json`. If neither exists for a required route, the run fails as
a configuration error. CLI `--model` explicitly supplies real Copilot and
overrides the script. Deterministic terminal routes do not invoke either
boundary.

Triage agent approval codes are:

- `vulnerable_symbol_unused`;
- `dev_only_scope`.

The only triage denial code is `advisory_applies`. Unsupported
reachable/exploitable conclusions fail closed.

The code sets and independently re-proven predicates in this section are the
canonical policy contract.

### Human review and injection

Agent tasks expose recommendation/code pairs as typed permission groups. A code
is valid only with the recommendation in the same group.

Ordinary unresolved analysis uses `insufficient_context`.
`injection_detected` is handled before normal permission reconciliation and
always escalates an agentic path. Deterministic terminal paths do not interpret
or send requester text to a model, so injection classification does not apply
to them.

Live normalization trims outer whitespace from the requester comment. The task
then preserves the first 4,000 characters of that normalized justification
without deleting or rewriting internal controls. JSON escaping provides
transport safety without changing those characters.

## Agent permission boundary

Model-facing content is explicit package data with separate session-system,
custom-agent, skill, task-dispatch, and tool-definition assets. Trusted Python
loads and validates those assets before opening a session.

The session registers one SDK `CustomAgentConfig` and selects it explicitly.
The custom agent owns its role and structured-output instructions, exact tool
names, preloaded skill name, and disabled inference behavior. A separate
append-mode system prompt owns application-wide trust and safety invariants. A
separate user prompt dispatches the validated `AgentTask` in one fenced JSON
block.

SDK custom-agent, instruction, hook, plugin, MCP, host-git, schedule,
session-store, memory, extension, and remote-session discovery remain disabled.
SDK skill loading is enabled only for one explicit packaged skill directory per
session;
repository, user, plugin, and automatically discovered skill locations are not
used. Before dispatch, SDK events must confirm the explicitly selected custom
agent and its exact tool names. Before any response is accepted, SDK events
must also confirm the expected skill with source `custom` and no agent
deselection. Missing or mismatched events, agent deselection, or any project,
inherited, personal, plugin, or built-in skill source is a configuration
failure.

The application defines exactly two explicit custom agents:

- `dependency-risk-investigator`, with the four bounded repository tools and
  the `dependency-risk-analysis` skill;
- `dependency-risk-judge`, with no tools and the
  `dependency-risk-review` skill.

Every real session:

- uses `CopilotClient(mode="empty")`;
- registers and explicitly selects only its packaged role;
- disables custom-agent inference and rejects runtime agent deselection;
- receives only its typed task or frozen review context;
- preloads only the skill named by the selected role;
- uses a permission handler that denies every request not satisfied by an
  explicitly registered custom tool;
- verifies the selected role and custom-source skill through runtime events
  before accepting output.

The investigator session:

- receives the assigned `AgentTask`;
- receives safe aggregate repository reference status and counts when its route
  can propose `vulnerable_symbol_unused`;
- registers only `list_files`, `read_file`, `search`, and
  `analyze_reachability`;
- passes those exact names through `available_tools`;
- binds the custom agent to those same tool names;
- preloads only the packaged `dependency-risk-analysis` skill;
- applies one policy deadline across bounded attempts;
- preserves cancellation rather than converting it to a result.

The judge session registers no tools, passes an empty `available_tools` list,
and binds the judge manifest to an empty tool list. Its review skill receives no
additional capability; the judge can use only the frozen validated context in
its dispatched task.

Repository tools are read-only and bounded. Trusted handlers reject:

- absolute paths and `..`;
- paths escaping the immutable snapshot;
- symlinks and binary files;
- credential-like files;
- repository-provided controls under any nested `.github` location except
  `.github/workflows` and `.github/actions`;
- dedicated Copilot or Claude controls and VS Code MCP configuration.

The agent has no shell, process, write, GitHub, arbitrary network,
package-manager, MCP, or out-of-snapshot capability.

`analyze_reachability` is an application-owned wrapper around a pinned
`ast-grep` runtime. The model cannot select an executable, engine, path, rule,
pattern, command, or configuration. Trusted Python binds the operation to the
assigned package and immutable snapshot, stages only allowlisted JavaScript and
TypeScript files, uses fixed application-owned queries, strips credentials and
proxy settings, applies input, output, result, and wall-clock limits, and
reconstructs citations from snapshot bytes. Runtime downloads, repository
configuration, rewrite mode, package-manager execution, and repository code
execution are prohibited.

Files are staged in deterministic path order. Reaching the analyzer file or
input-byte limit stops additional staging instead of discarding positive
evidence from the bounded processed subset. A positive match from that subset
remains usable syntactic evidence with an explicit partial-coverage limitation.
No match from a partial subset is `incomplete`, never `no_syntax_match`.

The tool produces syntactic usage evidence: imports, requires, dynamic imports,
and package-bound call shapes. It does not produce a call graph or prove
semantic reachability. No finding means only that the packaged structural
queries found no match within their stated scope and limits.

Each real model attempt has an isolated analyzer-invocation ledger. Before a
response is accepted, trusted code must confirm that the attempt invoked
`analyze_reachability` at least once for the assigned package and snapshot.
Repeated invocations return the attempt-local cached result rather than
rerunning the subprocess. Omission is malformed agent behavior and may consume
the remaining retry budget.

Unavailable, failed, truncated, or incomplete analyzer coverage cannot prove
non-reachability, but it does not force human review when other citable evidence
supports a permitted conclusion. Likewise, `no_syntax_match` may contribute to
a non-use conclusion only when deterministic reconciliation independently
re-proves complete dependency evidence, no dependency consumers, and bounded
repository-reference absence. No individual repository tool is mandatory
after the analyzer invocation; the agent chooses the smallest useful evidence
path.

The Copilot child environment contains only the Copilot credential and required
runtime variables. It excludes GitHub collection credentials and unrelated
environment secrets.

Agent output must:

- be exactly one structured finding;
- match workflow, correlation, repository, alert, request, snapshot, and
  policy identities;
- use one permitted recommendation/code pair;
- cite only observations returned by trusted tools.

Agent prose, confidence, and citations are never final authority. Deterministic
reconciliation owns the result.

Self-reported confidence, descriptive uncertainty text, and redundant citations
do not override a complete trusted approval predicate. `insufficient_context`
and `injection_detected` remain structured blockers, and every approval still
requires its reason-specific dependency and repository proof.

### Two-critic judge forum

After a real Copilot finding passes task, tool-invocation, schema, permission,
and citation validation, one additional no-tool Copilot turn reviews the frozen
finding. The compact judge forum applies two domain critics:

1. **Evidence critic** — checks whether the claim and recommendation follow
   from typed npm evidence, validated citations, reachability scope, and any
   repository-reference proof.
2. **Applicability critic** — constructs the strongest practical counter-case,
   including dependency consumers, dynamic loading, scope, mitigations, and
   overclaims about exploitability.

Both critic assessments and the adjudication are returned in one structured
response. This is one LLM call, not two independent critic sessions. The judge
has no tools, repository access, additional capabilities, MCP servers, or
credentials beyond the Copilot session credential. Its packaged review skill
supplies methodology only. It receives only bounded task context, the
validated primary finding, compact reachability and repository-reference
summaries, npm completeness, installed-instance properties, dependency
consumers, and the permitted recommendation/code pairs.

The judge returns `accept` with the unchanged finding or `replace` with one
corrected `AgentFinding`. A replacement must preserve task identity, use a
permitted recommendation/code pair, and cite only observations already
validated in the primary attempt. Trusted Python validates the selected finding
again before deterministic reconciliation.

Judge input and output are character-bounded. A judge timeout, unavailable
model, malformed response, or invalid replacement is recorded as an explicit
judge failure artifact and leaves the already validated primary finding in
place. The judge is an evaluator-optimizer, not a new availability or safety
gate. It cannot approve an outcome that deterministic reconciliation cannot
independently prove. Every judged run persists the validated primary finding
separately from the selected finding so a replacement remains auditable.

## Workflow stages

1. Validate invocation, paths, policy, credential availability, and role assignment.
2. Normalize the workflow target and collect request/alert metadata.
3. Resolve and collect an immutable repository snapshot.
4. Build typed npm evidence and the canonical evidence bundle.
5. Stop dismissal recommendation processing for non-pending or expired
   requests and produce a lifecycle result.
6. Run deterministic routing and proof evaluation.
7. Build and persist bounded repository reference evidence when the selected
   route can propose `vulnerable_symbol_unused`.
8. Create and run a bounded agent task when trusted routing marks the baseline
   as non-terminal. For triage, npm package-lock `applies` and every
   `human_review` baseline are agentic; `does_not_apply` and staged Yarn/pnpm
   `applies` decisions are terminal. Fail configuration when an agent-required
   route lacks a real or scripted boundary.
9. Validate tool observations and structured agent output.
10. Only when stage 8 actually ran a judged agentic boundary, run the bounded
    two-critic judge forum over the frozen valid finding. Lifecycle results and
    terminal deterministic decisions make zero investigator and judge LLM
    calls and produce no judge artifacts.
11. Reconcile the judge-selected result in deterministic Python using typed npm and repository
    reference evidence.
12. Re-read observable request and alert state.
13. Replace a dismissal recommendation with a stale lifecycle result when
    request or alert state changed. Triage drift is a validation failure.
14. Atomically publish local artifacts, including the judge review or failure
    record when a judge was configured.

The deterministic engine does not call GitHub, Copilot, the filesystem, or the
network. Filesystem observations are materialized as typed facts by trusted
repository handlers before reconciliation.

## Output and publication

`report.json` is authoritative. `report.md` is rendered only from validated
report data. Raw model output is never rendered directly.

A report is publishable only when:

- schemas and result-mode unions validate;
- identifiers and digests bind to one run;
- cited repository observations exist;
- the final dismissal recommendation is policy-permitted;
- deterministic proofs are schema-valid outputs of the deterministic engine;
- agent findings remain within an assigned typed permission group;
- untrusted text is safely rendered;
- stale or terminal requests produce lifecycle results, not recommendations.

Report publication uses an exclusive per-run reservation and stages both
outputs before publishing either one. Each final file replacement is atomic,
`report.md` is published first, and authoritative `report.json` is published
last. If staging or publication fails, the exact files created by that
publication attempt are removed; failure handling does not remove or overwrite
a prior successful report, and no new authoritative partial report remains.
Detailed artifact and fixture formats are in
[`reference/artifacts.md`](reference/artifacts.md).

## Failure states

| Exit | Failure |
|---:|---|
| 0 | Local report created, including `human_review` |
| 2 | Invalid invocation, settings, credentials, required agent boundary, Copilot configuration, or policy |
| 3 | GitHub authentication or authorization failure |
| 4 | Request, alert, repository, fixture, or snapshot collection failure |
| 5 | npm evidence collection failure |
| 6 | Copilot SDK, timeout, cancellation, or malformed-output failure |
| 7 | Reconciliation, validation, or stale triage-state failure |
| 8 | Artifact publication failure |

Failures are stage-classified. Untrusted raw model payloads remain only in
dedicated raw-output artifacts and are not copied into validated reports,
failure messages, or CLI stderr.

Unexpected filesystem, value, or schema failures while constructing eligible
repository reference evidence or binding it into the agent task are validation
failures with fixed trusted failure text. Artifact write failures during that
work remain publication failures and are not reclassified.

## Change control

Update this contract before changing workflow inputs, evidence, stages,
outputs, failure states, permissions, validation, or publication policy.

An ADR is required to change core module ownership, a workflow invariant, the
permission model, or validation/publication policy. Historical rationale lives
under [`decisions/`](decisions/).
