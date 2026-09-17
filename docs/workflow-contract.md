# Workflow contract

- **Status:** Accepted and implemented
- **Last updated:** 2026-09-17
- **Platform:** GitHub Enterprise Cloud
- **Ecosystems:** npm and Python (`pip` and `uv` Dependabot ecosystems)
- **Publication:** Local artifacts only
- **Default policy:** `default-dependency-review` version `3.0.0`
- **Report schema:** `3.0`
- **Evidence format:** `3.0`
- **Agent task format:** `3.0`
- **Judge review format:** `1.0`
- **Agent capability format:** `1.0`
- **Agent evaluation format:** `1.0`

This file is the authoritative contract for the implemented npm and Python
ecosystem workflows. Start with
[`README.md`](../README.md) for the documentation map. Detailed external and data
format references are linked where useful, but they do not override this
contract.

## Product boundary

The CLI supports two workflows:

| Workflow | Final result |
|---|---|
| Dismissal review | `approve`, `deny`, `human_review`, or a non-actionable lifecycle result |
| Alert triage | `applies`, `does_not_apply`, or `human_review` plus an action |

Both workflows:

1. collect typed dependency and repository evidence;
2. run deterministic policy first;
3. use bounded agent analysis only when trusted routing marks the deterministic
   baseline as non-terminal;
4. treat model output as untrusted input;
5. reconcile the final result in deterministic application code;
6. write local JSON and Markdown artifacts.

The application does not write to GitHub, approve or deny through an API,
remediate dependencies, create pull requests, support GHES, execute package
managers or project code, operate a service or queue, or publish outside the
selected local output directory.

## Commands and inputs

```text
dependabot-validator-grunt review-dismissal [inputs]
dependabot-validator-grunt triage-alert [inputs]
dependabot-validator-grunt evaluate-agent-capabilities --manifest <file> [inputs]
```

| Workflow | Live input | Offline input | Agent behavior |
|---|---|---|---|
| Dismissal | `--request <GitHub URL or owner/repo#alert>` or `--repo <owner/repo> --alert <number>` | `--offline-fixture <directory>` | Deterministic routing decides whether analysis is required. Offline routes use `agent-response.json` by default; `--model` selects real Copilot instead. |
| Triage | `--repo <owner/repo> --alert <number>` | `--offline-fixture <directory>` | Deterministic `does_not_apply` is terminal. Positive-only Yarn, pnpm, pip, Poetry, and uv `applies` decisions are also terminal. npm package-lock `applies`, npm `human_review`, and Python `human_review` baselines require a scripted or real investigator with the application-selected ecosystem capability. |
| Agent evaluation | Not supported | Versioned manifest containing local fixture paths and expected results | Runs the current investigator against local cases. `--model` selects opt-in real Copilot. Evaluation is non-authoritative. |

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

Agent evaluation additionally accepts:

- `--manifest <file>`, a versioned local manifest;
- `--output <directory>`, default `./agent-evaluations`;
- `--model <runtime-model-id>`, selecting real Copilot instead of fixture
  scripted responses.

Every evaluation case names one existing offline fixture and its expected
final result. Paths are resolved relative to the manifest. Evaluation output
is non-authoritative and cannot be consumed as a workflow decision.

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
[`reference/github-api.md`](reference/github-api.md) for endpoint and token
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
- `AlertSnapshot`: advisory identity, ecosystem, attested package spelling,
  normalized package identity, range, severity, scope, GitHub-attested
  direct/transitive relationship, and source digest;
- `RepositorySnapshot`: owner, repository, default branch, immutable snapshot
  identity, provenance, and included/excluded path manifests;
- `DependencyEvidence`: ecosystem, package manager, version scheme, discovered
  package records with explicit descriptive source provenance, declarations,
  consumers, bounded recorded dependency paths with edge-aligned conditions and
  requirements, pip provenance, manifests, issues, proof capabilities, and
  completeness;
- `RepositoryReferenceEvidence`: bounded package-identifier reference status,
  aggregate scan coverage, exclusions, budget use, and insufficiency reasons;
- `EvidenceBundle`: workflow identity, snapshots, evidence items, policy
  identity, and canonical digest;
- `AgentTask`: a bounded model-facing projection of the complete evidence,
  including GitHub-attested dependency relationship, total counts, typed
  samples with explicit truncation indicators, recorded candidate dependency
  paths, complete validated Python import targets with provenance, the trusted
  selected-project analysis root, and typed permitted recommendation/code
  groups;
- `AgentFinding`: an identity-bound claim whose response fields are all
  explicitly supplied by the model: workflow and request identity, proposal,
  confidence, uncertainty, safety flags, and digest-bound repository
  citations. `request_id` is required in the response object and is JSON
  `null` for triage;
- typed dismissal, lifecycle, and triage results.

Missing, partial, unsupported, contradictory, and failed evidence are explicit
states. Required nullable fields are serialized as JSON `null`; artifacts must
round-trip through their owning models.

Alert package names are validated and normalized by ecosystem. npm names must
be non-empty, at most 512 characters, unpadded, free of control or whitespace
characters, and shaped as one URL-safe npm name or one `@scope/name` pair.
Python names must be valid distribution names and use the PyPA canonical
identity: lowercase with each run of `-`, `_`, or `.` replaced by `-`. Reports
preserve the attested spelling and also serialize the canonical identity.
Repository-reference targets retain npm identifier validation because Python
non-use analysis is not supported. Invalid offline or live identifiers fail at
the collection boundary, and failure text does not include the rejected value.

Offline repository snapshots use a digest of the normalized included paths and
file contents. Live snapshots use the resolved default-branch commit SHA.

The npm-ecosystem collector supports package-lock versions 1, 2, and 3, Yarn
Classic lockfile v1, and pnpm lockfile v9.0 for the project directory identified
by the alert manifest. It normalizes only the selected project and its sibling
`package.json` and selected lockfile; it does not discover unrelated nested
projects or choose heuristically between multiple sibling lockfiles.

Evidence records the package manager, lockfile path/version, collector
capabilities, resolved instances, declarations, consumers, and limitations.
Package-lock v2/v3 retains complete-inventory authority. Package-lock v1, Yarn
v1, and pnpm v9.0 adapters have positive-instance authority only: a concrete,
registry-backed, comparable vulnerable instance can prove that an alert
applies, even when the adapter reports partial graph evidence. These adapters
cannot prove package absence, unaffected versions, `vulnerable_symbol_unused`,
or `dev_only_scope`. Package-lock v1 recursively reads the selected lockfile's
legacy dependency tree and records direct versus transitive placement without
claiming complete hoisting, consumer, workspace, or development-scope
semantics. A valid supported document with unresolved graph edges or
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
Package-lock v1 additionally bounds dependency-tree traversal steps, matching
instances, unique consumers, and aggregate serialized evidence output.
Exhausting any of those limits fails the dependency-evidence stage; the
collector does not emit an authorized partial positive result.
The collector never runs repository, package-manager, or lifecycle code and
never contacts a package registry or synthesizes a lockfile. Complete package
absence and unaffected-version conclusions continue to require explicit
complete-inventory capability.
See [`reference/npm-evidence.md`](reference/npm-evidence.md).

### Python dependency evidence

GitHub's attested ecosystem is preserved separately from the selected package
manager. GitHub uses ecosystem `pip` for pip requirements, Poetry, and
currently observed uv projects; `uv` remains accepted for compatible
normalized inputs. Collection uses the attested ecosystem, exact normalized
alert path, and adjacent files in that selected project only.

Initial Python evidence is positive-only and partial. It can record exact,
comparable vulnerable dependencies selected by repository files. Supported
Poetry and uv locks additionally produce bounded recorded candidate dependency
paths from the selected project to the alerted package. These paths describe
relationships encoded by the lock and project metadata; they do not prove
which environment, extra, group, source fork, or optional feature is active.
Python evidence cannot prove complete inventory, package absence, universal
unaffected versions, dependency-consumer completeness, development-only
installation, or unused vulnerable symbols.

Graph projection is bounded by configured node, edge, path-count, path-depth,
traversal-step, and serialized-size limits. Each serialized path contains one
edge kind, nullable explicit requirement, and nullable effective condition for
every adjacent node pair. Requirements are recorded constraints only; they do
not prove an active environment. Conditions on package nodes and ancestor
edges propagate through the projected root-to-target path.

Cycles, unresolved references, ambiguous target variants, conditional
ancestry, and truncation are preserved as explicit issues. Conditional-only
target ancestry withholds positive graph authority. When one complete
unconditional, non-development, cycle-free path selects the same unique
supported record, conditional alternatives remain context without negating
that positive path. Graph collection or path projection truncation that can
affect the selected target's ancestry, immediate consumers, or root-to-target paths also withholds
`resolved_instances` for that target. These states never authorize
complete-consumer or negative proof. Immediate consumers and paths may remain
bounded investigation context after authority is withheld.

The accepted selection anchors are:

| Dependabot ecosystem | Alert path | Selected project/input |
|---|---|---|
| `pip` | a repository-contained `.txt` or `.in` requirements path | that exact file only |
| `pip` | `pyproject.toml` with adjacent `poetry.lock` and `[tool.poetry]` | that Poetry project |
| `pip` | `pyproject.toml` with adjacent `uv.lock` and `[project]` | that non-workspace uv project |
| `pip` | `poetry.lock` | adjacent Poetry `pyproject.toml` in the same directory |
| `pip` or `uv` | `uv.lock` | adjacent non-workspace uv `pyproject.toml` in the same directory |
| `uv` | `pyproject.toml` containing a `[project]` table | that non-workspace project directory and adjacent `uv.lock` |
| `pip` | readable `pyproject.toml`, `setup.py`, `setup.cfg`, `Pipfile`, or `Pipfile.lock` not selected above | typed partial or unsupported evidence for that exact input |

Absolute paths, traversal, symlinked path components, excluded files, unreadable
selected files, malformed syntax in a selected supported format, byte-limit
violations, ambiguous adjacent Poetry/uv selection, and orphaned selected lock
files fail dependency evidence collection. A safely readable known Python
manifest whose semantics are not implemented produces typed
`completeness="unsupported"` evidence instead of a stage-5 failure. No
repository-wide sibling discovery occurs. uv workspaces and shared-lock member
selection remain unsupported and must not be chosen heuristically.

Python distribution names use PyPA normalization. Versions and advisory ranges
use PEP 440 through the application dependency on `packaging`; lexical,
SemVer, Poetry-operator approximation, and scanner-host marker evaluation are
prohibited.

#### pip requirements

The collector reads only the exact alert-selected requirements input. It uses a
bounded lexical front end and `packaging.Requirement` for requirement records.
One record becomes a comparable resolved instance only when all of these hold:

- it is a normal requirement line in the selected input, not a constraint;
- its normalized name matches the alert package;
- it has exactly one non-wildcard `==` specifier with a valid PEP 440 version;
- it has no environment marker, URL, VCS, path, archive, editable form, or
  environment-variable interpolation;
- duplicate matching records agree on the exact version.

Line continuations, recursive `-r` includes, `-c` constraints, global options,
per-requirement options, hashes, markers, ranges, arbitrary `===`, URLs, VCS,
paths, editables, malformed records, conflicting pins, and unsupported syntax
do not authorize an instance. They are retained as typed partial issues when
the file remains safely readable. Constraints never introduce dependencies.
Bounded recursive requirement includes and constraints may contribute typed
file provenance and exact-pin inventory. Include relationships, constraints,
and generated `# via` comments are not dependency-graph, consumer, activation,
or development-scope authority. They remain separate provenance records.
The pip requirements scanner independently bounds processed lines, emitted
declarations, exact-pin records, provenance records, and aggregate serialized
evidence/provenance bytes. Exhausting any bound fails the
dependency-evidence stage instead of silently truncating authoritative
evidence.
Filenames do not imply development scope.

#### Poetry

The collector supports Poetry lock formats `1.1` and `2.1`. A matching declaration in
`[project].dependencies` or `[tool.poetry.dependencies]` is recorded when
present and must be unmarked, non-optional, and have no custom source, URL,
VCS, or path identity to classify the record as direct.

One lock record becomes a comparable resolved instance only when it has:

- the matching normalized name and a valid exact PEP 440 version;
- `main` group membership for lock 2.1 or `category = "main"` for lock 1.1,
  and no package marker;
- no custom source record;
- one unique matching version in the supported lock structure.

The unique supported main lock record may be direct or transitive. The
collector reads supported package dependency tables and root declarations to
construct bounded recorded candidate paths. Edge requirements, markers,
optional state, group/category, and source ambiguity are retained. Package-node
and ancestor conditions propagate through the affected candidate path. A
separate complete unconditional, non-development, cycle-free path can retain
positive authority for the same unique supported record. A supported matching
main declaration records
`relationship="direct"`; otherwise a resolved root-to-target path or
GitHub-attested relationship may classify it as transitive. Target-relevant
graph or path truncation withholds the instance. An accepted instance grants
only `resolved_instances`, not consumer completeness, active-environment
selection, or deployment reachability.

Optional dependencies, extras, non-main groups or categories, dependency groups, markers,
custom repositories, direct URLs, VCS, paths, directories, multiple matching
versions, unsupported lock versions, and freshness mismatches do not authorize
an instance. Poetry 2 projects may define package metadata and dependencies
entirely through PEP 621 without a `[tool.poetry]` table. A content-hash value
that cannot be verified by the supported algorithm is recorded as unverified
and prevents claims stronger than “the repository records this locked
resolution.”

Inbound Poetry references to the matching record are authoritative only when
their version requirements are valid PEP 440 specifiers, uniquely select the
record, and have no marker, optional state, unsupported field, or other
selection condition. Unsupported Poetry-specific constraint syntax is never
approximated. Conditional, optional, ambiguous, unsupported, and
version-incompatible references remain explicit unresolved or conditional
candidate-graph context and withhold `resolved_instances`.

#### uv

The collector supports non-workspace uv lock major version `1`. An absent
revision or integer revision from `0` through `3` is understood. A newer
revision remains partial and cannot authorize an instance. A matching
unmarked direct main declaration in `[project].dependencies` is recorded when
present.

One lock record becomes a comparable resolved instance only when it has:

- the matching normalized name and a valid exact PEP 440 version;
- the public PyPI registry source `https://pypi.org/simple`;
- no resolution marker or source marker;
- one unique matching version in the supported lock structure.

The unique supported lock record may be direct or transitive. The collector
reads package dependency references and root project declarations to construct
bounded recorded candidate paths. Explicit root requirements and nullable
lock-edge requirements are retained alongside name, version, source, marker,
optional, group, fork, virtual, and workspace identity rather than guessed
away. Package-node and ancestor conditions propagate through the affected
candidate path. A separate complete unconditional, non-development,
cycle-free path can retain positive authority for the same unique supported
record. A supported matching main declaration records
`relationship="direct"`; otherwise a resolved root-to-target path or
GitHub-attested relationship may classify it as transitive. Target-relevant
graph or path truncation withholds the instance. The attested alert ecosystem
is preserved even when `package_manager="uv"`.

`[tool.uv.workspace]`, dependency groups, legacy dev dependencies, optional
dependencies, extras, conflicts, environment forks, resolution markers,
custom indexes, VCS, URLs, paths, editables, virtual/workspace sources,
multiple matching versions, unsupported lock majors, and unknown
selection-affecting fields do not authorize an instance.

See [`reference/python-evidence.md`](reference/python-evidence.md).

### Proof capability matrix

| Evidence adapter | `resolved_instances` | `complete_inventory` | `dependency_consumers_complete` | `development_scope` |
|---|---:|---:|---:|---:|
| npm package-lock v2/v3 | yes | yes | yes | yes |
| Yarn Classic v1 | conditional positive only | no | no | no |
| pnpm v9.0 | conditional positive only | no | no | no |
| selected pip exact pin | conditional positive only | no | no | no |
| Poetry 1.1/2.1 unique main record | conditional positive only | no | no | no |
| uv v1 unique selected-project record | conditional positive only | no | no | no |

Every deterministic or investigator-assisted proof checks its exact required capabilities.
`completeness == "partial"` does not block an authorized positive instance,
but no partial adapter may authorize a negative, scope, consumer, or non-use
conclusion.

### Serialized migration contract

The `3.0` format retains these machine-visible names introduced by the prior
`2.0` migration:

- `AlertSnapshot.ecosystem` and `AlertSnapshot.package_identity`;
- `RepositorySnapshot.coverage_excluded_paths` for omitted files that make
  repository-wide negative proof incomplete;
- `DependencyInstance`, `DependencyDeclaration`, and `DependencyEvidence`;
- `EvidenceBundle.dependency` instead of `EvidenceBundle.npm`;
- `AgentTask.dependency_completeness` instead of `npm_completeness`;
- evidence IDs `dependency.instances` and `dependency.declarations`;
- evidence kinds `dependency_instances` and `dependency_declarations`;
- collection failure stage `dependency_evidence`, retaining exit code 5;
- run collector identities `offline-dependency-v2` and
  `ghec-dependency-v2`;
- dependency evidence collector identity `dependency-evidence-v1`.

Within the `3.0` path shape, `DependencyPath.edge_requirements` is a bounded
nullable tuple aligned one-for-one with `edge_kinds` and `conditions`.
`DependencyPath.truncated` is not serialized because truncation is aggregate
target context on `DependencyEvidence.dependency_paths_truncated` and
`AgentTask.dependency_paths_truncated`. `DependencyDeclaration.groups` is not
serialized because declaration group semantics are represented by relationship
and selection conditions rather than an unused parallel field.
`DependencyInstance.version_scheme` is not serialized because the scheme is an
evidence-wide invariant on `DependencyEvidence.version_scheme`.
`DependencyInstance.source_kind` is always explicit, with an optional
`source_locator`, and describes the observed registry, URL, VCS, path,
workspace, or unknown source without granting proof authority. Instance
relationships are workspace, direct, development, optional, transitive, or
unknown; the unused root relationship is not part of the format.

The default policy identity is `default-dependency-review` version `3.0.0`.
Existing `1.x` and `2.x` evidence, task, and report artifacts remain historical
records and are not accepted as `3.0` objects through compatibility aliases.

During archive preflight, the 32 MiB exception applies only when the final
normalized member name is a recognized dependency manifest or lockfile.
Dependency members still count toward the unchanged total expanded-archive
budget. Every other regular archive member remains subject to the ordinary
10 MiB limit.

An ordinary regular member above its per-file limit is omitted from the
snapshot and recorded in `excluded_paths` instead of failing the whole
collection. A selected dependency input above its dependency-file limit still
fails collection. Every member remains subject to downloaded archive,
member-count, and total expanded-size limits.

Members whose Unicode-normalized, case-folded paths collide are all omitted
and recorded in `excluded_paths`, because they cannot be represented
portably as distinct snapshot paths. Collection fails when the selected
dependency input is part of such a collision. Excluded oversized or colliding
members make repository-wide negative reference evidence incomplete; they do
not invalidate positive observations from included files.

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
| Analyzer wall clock | 120 seconds |
| Analyzer profile files | 20,000 |
| Analyzer profile input | 128 MiB |
| Analyzer batch files | 1,000 |
| Analyzer batch input | 16 MiB |
| Analyzer stdout | 4 MiB |
| Analyzer stderr | 256 KiB |
| Analyzer findings | 500 |
| Static model-facing text and metadata | 8,192 characters |
| Canonical serialized investigator task | 24,000 characters |
| Rendered investigator task prompt | 25,000 characters |

Each retry receives a fresh repository-tool budget and cache, but all retries,
client/session setup, and model work share the one wall-clock deadline. The one-file limit remains subordinate to the per-attempt content budget.
Large dependency files are represented to the model through typed summaries
rather than sent whole. The complete `EvidenceBundle` is not truncated for
model limits. `AgentTask` deterministically retains the first 20 installed
instance records, 20 dependency consumers, 8 dependency paths, 20 declarations,
and 20 provenance records. Each sampled collection carries its available total
count and an explicit truncation indicator. Samples preserve the deterministic
collector order. Sampled dependency paths retain their typed nodes, edge kinds,
edge-aligned requirements and conditions, and path state; dependency-path
truncation also preserves upstream graph-projection truncation. Validated Python import targets are complete and are not sampled or silently
discarded. Python targets come from one versioned application-owned mapping:
reviewed distribution mappings take precedence, otherwise a canonical
distribution identity is authoritative only when it is itself one valid
top-level Python identifier. Broad shared namespaces and unknown mappings are
not invented. Curated targets retain explicit `curated_mapping` provenance.
Task construction rejects a canonical serialized task above its aggregate
limit as typed task validation, before session creation. Prompt rendering
raises a Copilot configuration failure when the complete rendered task prompt
exceeds its separate aggregate limit. Neither pre-dispatch failure consumes a
model retry. Copilot session mechanics are documented in
[`reference/copilot-boundary.md`](reference/copilot-boundary.md).

The parser stores the complete successful real-model response as `raw_content`
and extracts exactly one JSON object, allowing non-authoritative surrounding
prose or Markdown. Zero or
multiple JSON objects, a non-object response, or a structured finding that
omits any response-contract field or fails task identity, permission-pair,
schema, or citation validation is
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
- investigator routes that do not permit fail-closed human review;
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
| npm `not_used` | Deterministic non-applicability proof, otherwise agent analysis |
| npm `inaccurate` | Deterministic non-applicability proof, otherwise denial or human review |
| npm `tolerable_risk` | Agent denial or human review; never automated approval |
| Python `not_used`, `inaccurate`, or `tolerable_risk` | Deterministic proof when available; otherwise Python investigator denial or human review, never approval |
| unknown | `human_review` |

Complete package absence or proof that every recorded instance is unaffected
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
from a positive-evidence-only Yarn, pnpm, pip, Poetry, or uv adapter is also
terminal because those adapters cannot authorize an investigator-proposed non-applicability
exception. npm `human_review`, npm package-lock `applies`, and Python
`human_review` baselines require bounded agent verification in live or offline
runs. Python tasks permit only `deny/advisory_applies` and fail-closed human
review. They never permit approval or collect repository-reference absence.
Policy validation requires every investigator route to permit `human_review`, so
removing Python approval capability cannot leave a task without a safe outcome.
Python tasks carry bounded recorded candidate dependency paths, path
truncation, GitHub's attested direct/transitive relationship, and validated
import targets. The Python role always declares the same four bounded
repository tools as the npm role. When at least one import target is
authoritative, every accepted real-model attempt must invoke
`analyze_reachability`; when none is authoritative, invocation is optional and
an advisory or inapplicable tool result cannot create decision authority.
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

For npm, a denial requires at least one validated repository citation. For
Python, `advisory_applies` additionally requires trusted dependency provenance:
at least one matching selected-manifest declaration or resolved instance in
the complete trusted dependency evidence and at least one citation that exactly
corresponds to a positive finding in the selected attempt's task-bound
`ReachabilityEvidence`. Bounded task samples are model context only and never
replace the complete evidence used for deterministic authority.
That finding must report language Python, match an authoritative task import
target, and have kind `static_import` or `dynamic_import`. Analyzer evidence
must match the assigned task's snapshot, package, and complete
application-selected target list. A canonical same-name target or reviewed
curated alias may be authoritative only when the application-owned mapping
does not identify a known competing distribution for that namespace. Known
collisions remain advisory for every involved distribution. Agent-derived
alternatives are always advisory. Bound calls without their positive import
finding, plain search citations, parent-dependency use, plain distribution-name
occurrences, documentation, comments, plugin/configuration/command evidence,
analyzer target mismatch, and `no_syntax_match`, `incomplete`, or `unavailable`
results are insufficient. Such validated context may remain attached to a
`human_review` finding, but it cannot authorize denial. No search or structural
no-match can prove Python non-use.

The code sets and independently re-proven predicates in this section are the
canonical policy contract.

### Human review and injection

Agent tasks expose recommendation/code pairs as typed permission groups. A code
is valid only with the recommendation in the same group.

Ordinary unresolved analysis uses `insufficient_context`.
`injection_detected` is handled before normal permission reconciliation and
always escalates an investigator path. Deterministic terminal paths do not interpret
or send requester text to a model, so injection classification does not apply
to them.

Live normalization trims outer whitespace from the requester comment. The task
then preserves the first 4,000 characters of that normalized justification
without deleting or rewriting internal controls. JSON escaping provides
transport safety without changing those characters.

## Agent permission boundary

Model-facing content is explicit package data with separate session-system,
custom-agent, skill, task-dispatch, and tool-definition assets. Trusted application code
loads and validates those assets before opening a session.

The session registers and selects one investigator custom agent. Its manifest
owns the stable identity, fixed tools, common response prompt, and disabled
inference. Before session creation, trusted application code selects one versioned
ecosystem capability from the task. The capability chooses the npm or Python
skill and analyzer profile. It cannot grant tools, permissions, evidence
authority, policy outcomes, or publication rights.

The append-mode system prompt states session safety rules. The user prompt
carries the validated `AgentTask` in one fenced JSON block.

SDK custom-agent, instruction, hook, plugin, MCP, host-git, schedule,
session-store, memory, extension, and remote-session discovery remain disabled.
SDK skill loading is enabled only for one explicit packaged skill directory per
session;
repository, user, plugin, and automatically discovered skill locations are not
used. Sessions continue to explicitly disable the built-in
`customize-cloud-agent` and `github-pr-media` skills.

Executable capability is enforced independently of SDK identity events by
`CopilotClient(mode="empty")`, the
explicit session `available_tools` filter, the fixed registered Python tool
handlers, and the deny-by-default permission callback. Selected-agent,
inventory, and expected-skill events are diagnostic provenance rather than
authorization. Missing, reordered, or mismatched diagnostic events do not by
themselves invalidate an otherwise bounded response. A positively observed
unexpected enabled skill, executable tool outside the allowlist, agent
deselection, or conflicting non-null selected-agent and response-agent
identifiers remains a configuration failure.

The runtime observer is order independent and monotonic through the final
assistant response. It accumulates every custom-agent, selected-agent, skill,
deselection, and response identity observation. Once capability expansion or
deselection is observed, later events cannot clear the failure. Missing
expected inventory, selected-agent, skill, or nullable response identifiers
remain diagnostics. Malformed events are diagnostics unless they positively
expose an untrusted enabled skill or tool.

## Structural usage evidence

The application-controlled ast-grep boundary stages bounded profile-relevant
UTF-8 source files that passed immutable snapshot and denied-path controls.
Profile suffix selection is execution mechanics tied to the pinned engine, not
a source-extension security allowlist or negative-proof boundary. ast-grep
infers language from file paths, and trusted application code invokes only fixed packaged
operations.

Input coverage records candidate, staged, skipped, and operation counts.
Complete staging means only that every eligible file fit the configured input
limits; it does not claim ast-grep supports every language or syntax form.
Unsupported syntax, no match, truncation, timeout, and analyzer failure never
prove semantic non-reachability.

JavaScript/TypeScript operations cover static import, `require`, dynamic import,
and bound calls. Python operations cover `import`, `from ... import ...`,
literal `importlib.import_module`, absolute literal `__import__`, and calls
bound to a validated import. Relative or indeterminate `__import__` levels do
not produce external-package findings. Every finding includes the
ast-grep-reported language,
matched target, immutable citation, and optional binding. The model cannot
choose target identities, patterns, rules, paths, languages, or commands.
Trusted application code derives Python analyzer targets only from
`AgentTask.import_targets`; task targets without authority may produce advisory
findings but cannot authorize a decision.

The application selects exactly one explicit structural usage profile from the
assigned task. npm tasks select `npm`, whose operation set contains only
JavaScript/TypeScript import statements and call expressions and whose trusted
interpretation registers only JavaScript, JSX, TypeScript, or TSX findings.
`pip` and `uv` tasks select `python`, whose operation set contains only Python
import statements, from-import statements, and calls and whose trusted
interpretation registers only Python findings. This is direct application
dispatch, not a registry or plugin boundary. Fixed application-owned,
language-scoped import rules include the complete application-selected target
set, so unrelated imports are discarded by ast-grep before consuming the
shared output budget. Call operations run only on files containing a target
literal or a target import match; this preserves supported runtime imports and
bound-call interpretation without collecting every call in unrelated files.
Trusted interpretation still validates exact syntax and target identity.

The runtime defines two roles:

- `dependency-risk-investigator`, with the four bounded repository tools and
  one trusted application-selected ecosystem capability;
- `dependency-risk-judge`, with no tools and the
  `dependency-risk-review` skill.

The packaged investigator capabilities are:

- `javascript-typescript-v1`, selected only for npm ecosystem tasks, using the
  `npm` analyzer profile and
  `javascript-typescript-dependency-risk-analysis` skill;
- `python-v1`, selected only for `pip` and `uv` ecosystem tasks, using the
  `python` analyzer profile and `python-dependency-risk-analysis` skill.

Capability data contains only ecosystem methodology and versioning. The
investigator identity, manifest, common prompt, and tool boundary are fixed in
trusted application code and cannot be changed by a capability entry.

Selection is one exhaustive application-owned branch. Unknown ecosystems fail
configuration. GitHub's attested ecosystem remains separate from the selected
package manager, so a pip-attested uv project still uses uv collection and the
Python capability.

The routing matrix is:

| Alert ecosystem | Selected package manager | Collector | Analyzer | Capability |
|---|---|---|---|---|
| `npm` | `npm`, `yarn-classic`, or `pnpm` | npm | `npm` | `javascript-typescript-v1` |
| `pip` | `pip` or `poetry` | Python | `python` | `python-v1` |
| `pip` | `uv` | Python uv normalization | `python` | `python-v1` |
| `uv` | `uv` | Python | `python` | `python-v1` |

Every other ecosystem/package-manager combination fails validation. Collection,
lifecycle evidence, capability selection, version semantics, analyzer profile,
and permissions use explicit branches without a catch-all non-npm route.

Every real session:

- uses `CopilotClient(mode="empty")`;
- registers and explicitly selects only its packaged role;
- disables custom-agent inference and rejects runtime agent deselection;
- receives only its typed task or frozen review context;
- preloads only the skill named by the selected capability or judge
  role;
- uses a permission handler that denies every request not satisfied by an
  explicitly registered custom tool;
- records available role and custom-source skill runtime events as diagnostics
  and rejects positively observed capability expansion.

Each investigator session:

- receives the assigned `AgentTask`;
- receives safe aggregate repository reference status and counts when its route
  can propose `vulnerable_symbol_unused`;
- registers and passes through only the fixed investigator tool allowlist;
- binds the custom agent to those same tool names;
- preloads only its selected capability skill;
- applies one policy deadline across bounded attempts;
- preserves cancellation rather than converting it to a result.

Every model-turn implementation used by workflow orchestration must invoke
`analyze_reachability` for npm tasks and for Python tasks with at least one
authoritative import target. Python tasks without an authoritative target may
omit it; if called without any task import target, the handler returns a fixed
inapplicable result without running the analyzer. After every `ModelTurn.run`
returns, workflow orchestration authoritatively validates the invocation count,
selected profile, assigned snapshot, package, and complete target list before
accepting output. The real Copilot boundary performs the same validation inside
each attempt so omission or mismatch remains retry-classified as malformed
model behavior. A normal Python analyzer result is citable context, but only
the exact authoritative positive-import predicate defined above can authorize
denial.

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
- dedicated model-agent controls and VS Code MCP configuration.

The agent has no shell, process, write, GitHub, arbitrary network,
package-manager, MCP, or out-of-snapshot capability.

`analyze_reachability` is an application-owned wrapper around a pinned
`ast-grep` runtime. The model cannot select an executable, engine, path, rule,
pattern, language, command, or configuration. Trusted application code binds one or more
application-selected target identifiers and the immutable snapshot, deriving
Python targets from the assigned task rather than tool input, stages
bounded regular UTF-8 files under the existing denied-path controls, supplies a
minimal application-owned config outside the staged repository, places every
staged path after the command-line option terminator, uses fixed
application-owned operations, strips credentials and proxy settings, applies
input, output, result, and wall-clock limits, and reconstructs citations from
snapshot bytes. Runtime downloads, repository configuration, rewrite mode,
package-manager execution, and repository code execution are prohibited.

Files are staged in deterministic priority and path order so likely source
files precede metadata, lockfiles, and documentation when a file or input-byte
limit is reached. Candidate, staged, and skipped counts expose bounded input
coverage. Completed-operation counts expose only which fixed ast-grep
operations finished; they do not claim that ast-grep recognized every staged
file. A positive match from a partial subset remains usable syntactic evidence
with an explicit partial-coverage limitation. No match from partial staging or
an incomplete operation set is `incomplete`, never `no_syntax_match`.

Raw ast-grep operations are selected by profile without a model-selected
language flag: `npm` collects target-filtered import statements and call
expressions from target-relevant files; `python` collects target-filtered
import statements and from-import statements, then calls from target-relevant
files.
Trusted profile-aware interpretation then emits common positive finding kinds
such as `static_import`, `dynamic_import`, `runtime_require`, and `bound_call`,
with the detected language and matched target bound into each finding. The
tool does not produce a call graph or prove semantic reachability. No finding
means only that the selected fixed operations found no trusted match within
their stated scope and limits; ast-grep may not support every staged language
or syntax form.

The application derives one trusted analysis root from the parent directory of
the alert-selected manifest. The analyzer may inspect only profile-relevant
files under that root. Repository list, read, and search tools retain their
existing bounded whole-snapshot access so the investigator can inspect shared
configuration, but a decision-changing structural citation from an unrelated
sibling project is rejected. Root-project alerts continue to analyze the whole
snapshot.

Profile file selection is an execution boundary tied to the pinned engine, not
a repository path-security boundary or a negative-proof claim. The npm profile
accepts JavaScript and TypeScript path forms supported by the pinned engine;
the Python profile accepts Python source and stub files. Other readable files
remain available to ordinary repository tools but are not sent through
ast-grep. Analyzer evidence records the selected project root and profile
candidate, staged, skipped, and byte counts.

Reviewed Python distribution-to-import mappings may widen target discovery.
Mappings with a known competing distribution for the same top-level namespace
remain non-authoritative even when the spelling is canonical for one
distribution. This includes both sides of known collisions, preventing package
presence plus an ambiguous import from authorizing `advisory_applies`.

Profile files are processed in deterministic bounded batches. Every batch and
operation shares the one analyzer deadline and aggregate stdout, stderr,
finding, file, and byte limits. Positive findings completed before exhaustion
remain valid. Missing batches or operations make no-match coverage
`incomplete`; increasing aggregate limits never converts partial evidence into
negative proof.

Each real model attempt has an isolated analyzer-invocation ledger. Before a
real response is accepted for an attempt, trusted code confirms required
invocation and exact task/profile/project-root binding so malformed behavior
can consume the remaining retry budget. Workflow orchestration repeats that
validation after every model-turn implementation returns, including scripted
and alternative turns. Produced evidence must use the complete
application-selected target list. Repeated invocations return the
attempt-local cached result rather than rerunning the subprocess.

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
- explicitly provide `workflow_mode`, `correlation_id`, `repository_id`,
  `alert_number`, `request_id`, `snapshot_id`, `policy_digest`, `claim`,
  `citations`, `uncertainty`, `proposed_recommendation`,
  `policy_reason_code`, `confidence`, `insufficient_context`, and
  `injection_detected`;
- match workflow, correlation, repository, alert, request, snapshot, and
  policy identities;
- use one permitted recommendation/code pair for an ordinary finding;
- cite only observations returned by trusted tools.

`request_id` remains a required nullable identity field: dismissal findings
carry the assigned request ID and triage findings carry JSON `null`.
`uncertainty` is required even when the correct value is an empty string.
Trusted validation rejects an ordinary forbidden recommendation/reason-code
pair before reconciliation so a real model attempt can retry. A finding that
sets `insufficient_context` or `injection_detected` remains eligible for safe
deterministic escalation even when its proposed ordinary pair is otherwise
forbidden; blocker findings still pass through the unchanged citation
anti-fabrication rules.

Citation identity is the trusted path, line, and digest tuple. When that tuple
matches an attempt-local observation, trusted application code replaces the model's
excerpt with the canonical observed excerpt before publication. A missing or
unobserved tuple remains fabricated evidence and invalidates any
decision-changing finding; unverifiable optional citations on `human_review`
are discarded.

Agent prose, confidence, and citations are never final authority. Deterministic
reconciliation owns the result.

Every investigator run writes `agent-capability.json` with
`agent_capability_format_version: "1.0"`. The canonical object contains:

- `correlation_id`, `task_digest`, `snapshot_id`, `policy_digest`, and
  `evidence_digest`;
- attested `ecosystem` and selected `package_manager`;
- `execution_mode: scripted | copilot`;
- `capability_id`, `capability_version`, and canonical SHA-256
  `capability_digest`;
- `agent_name`, `role_prompt_asset`, `role_prompt_digest`, `skill_name`,
  `skill_asset`, and `skill_digest`;
- `analyzer_profile` and the ordered fixed `tool_names`;
- nullable `requested_model` and `observed_model`;
- ordered normalized diagnostic codes and classified attempt outcomes.

Digests use canonical JSON for capability objects and normalized UTF-8 asset
bytes. The npm capability uses `capability_version: "1.3.0"` and the Python
capability uses `capability_version: "1.2.0"`.
Scripted runs record the validated selected configuration with
`execution_mode: scripted`; they do not claim that Copilot observed or executed
the prompt, skill, agent, or tools. Provenance is bound and published before
the final report; validation or write failure uses the existing configuration
or publication failure classification.

Self-reported confidence, descriptive uncertainty text, and redundant citations
do not override a complete trusted approval predicate. `insufficient_context`
and `injection_detected` remain structured blockers, and every approval still
requires its reason-specific dependency and repository proof.

### Two-critic judge forum

After a real Copilot finding passes task, tool-invocation, schema, permission,
and citation validation, the application may construct one no-tool judge and
review the frozen finding. `JudgedModelTurn` receives a zero-argument judge
provider rather than a constructed judge. It invokes the provider only after
primary validation and a positive remaining deadline, catches provider and
review failures as `JudgeFailure`, rechecks the deadline after construction,
and preserves cancellation. The compact judge forum applies two domain critics:

1. **Evidence critic** — checks whether the claim and recommendation follow
   from typed dependency evidence, validated citations, reachability scope, and any
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
summaries, ecosystem, dependency completeness, declarations,
installed-instance properties, dependency consumers, candidate dependency
paths, dependency provenance, complete validated import targets, and the
permitted recommendation/code pairs. Validated real-model findings from either
ecosystem capability are reviewed; the judge remains repository-blind and cannot
create new evidence. The judge uses its own smaller samples, counts, truncation
indicators, and aggregate character limits. It receives typed installed
instance records only and never receives the removed legacy
`installed_instances` string field.

The judge returns `accept` with the unchanged finding or `replace` with one
corrected `AgentFinding`. A replacement must preserve task identity, use a
permitted recommendation/code pair, and cite only observations already
validated in the primary attempt. It must also preserve any
`insufficient_context` or `injection_detected` blocker set by the primary
finding; a no-tool reviewer cannot clear a fail-closed safety state. Trusted
Python validates the selected finding again before deterministic
reconciliation.

Judge input and output are character-bounded. The judge may retry one missing
or malformed response within the same bounded deadline. A final timeout,
unavailable model, asset or constructor failure, malformed response, or invalid
replacement is recorded as an explicit judge failure artifact and leaves the
already validated primary finding in place. Terminal routes and
primary-investigator failures do not construct or load judge assets. The judge
is an evaluator-optimizer, not a new availability or safety gate. It cannot
approve an outcome that deterministic reconciliation cannot
independently prove. Every judged run persists the validated primary finding
separately from the selected finding so a replacement remains auditable.

## Workflow stages

1. Validate invocation, paths, policy, credential availability, and role assignment.
2. Normalize the workflow target and collect request/alert metadata.
3. Resolve and collect an immutable repository snapshot.
4. Build typed dependency evidence and the canonical evidence bundle.
5. Stop dismissal recommendation processing for non-pending or expired
   requests and produce a lifecycle result.
6. Run deterministic routing and proof evaluation.
7. Build and persist bounded repository reference evidence when the selected
   route can propose `vulnerable_symbol_unused`.
8. Create and run a bounded agent task when trusted routing marks the baseline
   as non-terminal. For triage, npm package-lock `applies`, npm
   `human_review`, and Python `human_review` baselines require investigation.
   `does_not_apply` and staged positive-only `applies` results are terminal.
   Fail configuration when an agent-required route lacks a real or scripted
   boundary.
9. Validate tool observations and structured agent output.
10. Only when stage 8 actually ran a judged investigator boundary, run the bounded
    two-critic judge forum over the frozen valid finding. Construct judge assets
    only at this point. Lifecycle results, terminal deterministic decisions,
    and failed primary investigations make zero judge constructions or calls
    and produce no judge artifacts.
11. Reconcile the judge-selected result in deterministic application code using typed dependency and repository
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

Agent evaluation writes beneath its selected output directory:

- one isolated workflow artifact directory per case;
- `evaluation.json`, the canonical non-authoritative evaluation summary for
  that evaluation run;
- no workflow `report.json` outside the isolated case directories.

The manifest has `agent_evaluation_manifest_version: "1.0"`, a safe unique
`evaluation_id`, and non-empty unique cases. Each case has a safe unique
`case_id`, a relative existing `fixture`, and one expected result containing
`workflow_mode`, `result_kind`, optional `recommendation` or `assessment`, and
optional `reason_code`. Paths cannot escape the manifest directory.

Each case receives a fresh model boundary, workflow output directory, attempt
state, and tool cache. Scripted cases load and render the selected packaged
agent, prompt, and skill before replaying `agent-response.json`; they validate
the boundary and workflow, not model response quality. Real-model cases use
the same assets and also receive a fresh lazy judge. Evaluation uses ordinary
policy precedence. Scripted fixture turns skip judging; valid real-model
findings receive the no-tool judge.

`evaluation.json` has `agent_evaluation_format_version: "1.0"` and
`authoritative: false`. It records the evaluation and manifest digest,
requested model, start and completion times, and one result per case. Each
result records capability provenance, primary/judge/final result
summaries when available, validation and expectation status, classified
attempts, elapsed milliseconds, and nullable input, output, cache, cost, and
tool metrics when the SDK exposes them.

Evaluation continues after case execution or expectation failures and records
them. Cancellation stops immediately and remains cancellation. The output
directory is exclusively reserved; case artifacts are isolated; the summary is
staged and atomically published last even when cases fail. Exit `0` means every
case executed and matched expectations. Exit `9` means a manifest,
case-execution, expectation, or evaluation-publication failure occurred after
the canonical summary was written when publication was possible. It never
authorizes a Dependabot decision or changes the current investigator.

## Failure states

| Exit | Failure |
|---:|---|
| 0 | Local report created, including `human_review` |
| 2 | Invalid invocation, settings, credentials, required agent boundary, Copilot configuration, or policy |
| 3 | GitHub authentication or authorization failure |
| 4 | Request, alert, repository, fixture, or snapshot collection failure |
| 5 | Dependency evidence collection failure |
| 6 | Copilot SDK, timeout, cancellation, or malformed-output failure |
| 7 | Reconciliation, validation, or stale triage-state failure |
| 8 | Artifact publication failure |
| 9 | Agent evaluation manifest, execution, expectation, or publication failure |

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
