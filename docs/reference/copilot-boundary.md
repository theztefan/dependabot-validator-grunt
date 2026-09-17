# Copilot boundary reference

This page explains the investigator and judge runtime. The normative workflow
and permission rules remain in
[`../workflow-contract.md`](../workflow-contract.md).

## Investigator capabilities

The runtime explicitly selects two role identities:

- `dependency-risk-investigator` declares `list_files`, `read_file`, `search`,
  and `analyze_reachability`; trusted application code selects one versioned npm or
  Python capability and materializes its skill;
- `dependency-risk-judge` loads `dependency-risk-review` and declares no tools.

The investigator manifest owns the stable identity, fixed tools, disabled
inference, and common response prompt. Trusted application code selects the analyzer
profile and one packaged methodology skill through an exhaustive ecosystem
branch. Capabilities do not grant tools, permissions, policy outcomes, or
evidence authority. The judge retains its separate asset lifecycle.

Every real role session:

- uses `CopilotClient(mode="empty")`;
- registers and explicitly selects only its packaged custom agent;
- loads only its packaged custom-source skill;
- receives one validated, role-specific bounded input;
- denies every unlisted permission request;
- disables repository, user, plugin, hook, instruction, MCP, remote-session,
  and automatic skill or agent discovery;
- shares one bounded deadline across client startup, attempts, tools, and model
  work;
- preserves cancellation as cancellation.

Investigators receive version `3.0` `AgentTask` data. Python tasks may carry
bounded recorded candidate paths and validated import-target provenance; those
fields provide context without claiming an active environment or granting
additional permission. The complete evidence bundle remains unchanged.
Model-facing tasks retain total counts plus deterministic typed samples of at
most 20 installed instances, 20 consumers, 8 dependency paths, 20 declarations,
and 20 provenance records. Every collection has explicit task-level truncation
state, and dependency-path truncation also retains upstream graph-projection
truncation. Validated import targets remain complete.

SDK agent, skill, and inventory events provide diagnostic provenance. The
observer is order-independent and monotonic. Missing or mismatched expected
identity events do not reject an otherwise capability-bounded response. Any
positively observed enabled skill outside the selected packaged skill, tool
outside the fixed allowlist, agent deselection, or conflicting non-null
selected/response agent identity remains a configuration failure.

The child environment contains only required runtime values and the Copilot
credential. It does not inherit the GitHub collection token or unrelated
environment secrets.

Sessions explicitly disable the SDK built-in `customize-cloud-agent` and
`github-pr-media` skills. Any positively observed unexpected enabled skill
remains a configuration failure.

## Investigator attempts and tools

Deterministic terminal routes do not invoke the investigator. Inconclusive npm
or Python work may use it with the selected ecosystem capability. Python tasks
have no approval permission and cannot use absence of search results as proof
of non-use.

Each attempt receives a fresh repository-tool cache and byte budget. Successful
observations from failed attempts are not carried into the selected finding.

Every npm model turn must invoke `analyze_reachability` at least once. Python
turns must invoke it when an authoritative task import target exists;
otherwise invocation is optional. Workflow orchestration enforces this for
every model-turn implementation, while real-model attempts also enforce it
internally for retry classification. Python target identifiers are derived
only from `AgentTask.import_targets`. The model cannot choose the executable,
command, target, rule, pattern, path, language, engine, or configuration.
Repeated calls return the attempt-local cached result.

See [`repository-evidence.md`](repository-evidence.md) for file controls.

## Structural analyzer

The application uses pinned `ast-grep-cli==0.45.3` for bounded structural
syntax evidence. Trusted application code derives the selected-project root from the
alert manifest and selects only pinned-engine profile paths below that root:
JavaScript and TypeScript forms for npm, and Python source and stub files for
Python. This is an execution optimization, not a security allowlist or a claim
that other files are irrelevant to the investigation; ordinary bounded
repository tools can still inspect them. The model cannot choose the project
root, target identifiers, commands, rules, patterns, paths, languages, engines,
or configuration.

`reachability.py` is the public runner and result coordinator.
`reachability_ast_grep.py` exclusively owns trusted staging, application-owned
configuration, subprocess execution, output parsing and bounds, immutable
source rechecks, and citation construction. `reachability_npm.py` and
`reachability_python.py` own only their concrete language-family
interpretation. The coordinator selects between those two functions with an
exhaustive direct branch; there is no interpreter registry, protocol, class
hierarchy, or dynamic discovery.

The application selects exactly one explicit profile from the assigned task.
The `npm` profile runs only import-statement and call-expression operations and
registers only JavaScript, JSX, TypeScript, or TSX findings for static imports,
`require`, dynamic imports, and bound calls. The `python` profile runs only
import-statement, from-import-statement, and call operations and registers only
Python findings for direct imports, aliases, literal
`importlib.import_module`, literal `__import__`, and calls through imported
bindings. This direct selection supports mixed-language repositories without a
registry. Profile files are sorted and split into deterministic batches of at
most 1,000 files and 16 MiB. Batches share aggregate file, byte, output,
finding, and 120-second limits. Fixed application-owned language-scoped rules
preserve path-based language inference and prevent irrelevant-language input
from consuming the selected profile's budget. Raw operation collection is
separate from trusted profile-aware interpretation. Advisory task targets may
produce investigation context but never decision authority.

The subprocess has no command shell, package manager, repository rules, runtime
download, network access, or credentials. Each invocation uses a minimal
application-owned config outside the staged repository and places staged paths
after the command-line option terminator, so repository config and
option-shaped filenames cannot alter parsing or invocation. Trusted application code
validates the engine version, JSON shape, paths, ranges, unchanged source
bytes, findings, and resource limits before creating citations.

Agent-facing states are `syntax_usage_found`, `no_syntax_match`, `incomplete`,
and `unavailable`. Only the first is positive evidence. The others cannot prove
non-reachability or support non-applicability.
When a Python task has no application-selected import target, the wrapper may
return a fixed `inapplicable` tool result without starting ast-grep. That result
is not `ReachabilityEvidence` and has no decision authority.

Evidence records application-selected targets, candidate, staged, and skipped
file counts, staged bytes, the selected `npm` or `python` profile, completed
fixed operations, and positive findings with detected language and matched
target. No match, unsupported syntax, partial coverage, failure, and
unavailability never prove non-reachability; ast-grep may not support every
staged language or syntax.

Default limits are 20,000 staged files, 128 MiB staged input, 4 MiB stdout,
256 KiB stderr, 500 findings, and 120 seconds. A second analyzer requires a
concrete adapter and ADR covering license, distribution, execution boundaries,
evidence semantics, validation, limits, failure behavior, and decision
authority. Do not add an analyzer registry before that implementation exists.

## Output validation

The prompt requests one JSON object containing one finding. The boundary also
accepts one object surrounded by non-authoritative prose or a Markdown fence.
Zero objects, multiple objects, or an invalid object consume retry budget.

Trusted application code validates:

- workflow and run identity;
- repository, alert, request, snapshot, and policy identity;
- the explicit presence of every response-contract field;
- recommendation and reason-code permission for ordinary findings;
- confidence and safety flag types;
- every cited observation;
- required npm and authoritative-target Python analyzer invocation;
- exact analyzer binding to the task package, snapshot, and selected targets.

Workflow orchestration performs the authoritative invocation and binding check
after every `ModelTurn.run`, including scripted and alternative turns. The
real Copilot implementation retains the same check inside each attempt so a
missing or mismatched invocation consumes retry budget as malformed behavior.

`request_id` is a required nullable response field: dismissal findings copy the
assigned ID and triage findings return JSON `null`. `uncertainty`,
`workflow_mode`, `policy_reason_code`, `confidence`, `insufficient_context`, and
`injection_detected` are also required even when their value is empty, false, or
zero. An ordinary forbidden recommendation/code pair is malformed model output
and can consume retry budget. A finding with `insufficient_context` or
`injection_detected` remains eligible for deterministic blocker escalation even
if its proposed ordinary pair is forbidden; citation validation is unchanged.

An unverifiable citation invalidates any finding that could change the
decision. For a `human_review` finding, unverifiable optional citations are
discarded and cannot enter the authoritative report; the inconclusive finding
may still be retained.

Python `deny/advisory_applies` additionally requires dependency provenance and
a citation that exactly matches a selected attempt-local analyzer finding with
language Python, an authoritative task target, and kind `static_import` or
`dynamic_import`. Search-only, parent-only, bound-call-only, advisory-target,
no-match, incomplete, unavailable, and mismatched-target evidence cannot
authorize denial.

The citation key is `(path, line, digest)`. If that key identifies an exact
attempt-local observation but the model reformats or truncates its excerpt,
trusted application code restores the canonical observed excerpt. The model-provided
excerpt is never authoritative.

The complete successful real-model response is stored as `raw_content` inside
`agent-output.raw.json`. Only the extracted and validated finding can influence
the result.

## Two-critic judge

After a real investigator finding validates, one additional no-tool model turn
reviews it through:

1. an evidence critic;
2. a practical-applicability critic.

The judge is constructed only after a primary finding validates and time
remains. The provider and review are inside the non-blocking failure boundary;
terminal routes and primary failures never load judge assets.

The judge runs as the explicit `dependency-risk-judge` custom agent with the
`dependency-risk-review` skill. Its manifest, SDK tool list, and
`available_tools` are all empty. The skill adds methodology but no capability.

The judge receives compact validated context, not repository access. It may
accept the primary finding unchanged or replace it with another complete
finding that uses the same task identity, permitted outcome pair, and a subset
of already validated citations. Its independently bounded payload uses typed
installed-instance records, consumers, candidate paths, declarations,
provenance, complete import targets, counts, and truncation indicators. It does
not receive the removed legacy `installed_instances` strings.

Judge timeout, malformed output, or invalid replacement is recorded and the
valid primary finding is retained. Deterministic reconciliation remains the
final authority.

## Default model limits

| Limit | Default |
|---|---:|
| Attempts | 2 |
| Shared workflow deadline | 360 seconds |
| Agent-readable content per attempt | 32 MiB |
| Static model-facing text and metadata | 8,192 characters |
| Canonical serialized investigator task | 24,000 characters |
| Rendered investigator task prompt | 25,000 characters |
| Analyzer deadline | 120 seconds |
