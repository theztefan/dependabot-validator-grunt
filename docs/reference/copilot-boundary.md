# Copilot boundary reference

This page explains the investigator and judge runtime. The normative workflow
and permission rules remain in
[`../workflow-contract.md`](../workflow-contract.md).

## Explicit roles

The application packages and explicitly selects two custom agents:

- `dependency-risk-investigator` loads `dependency-risk-analysis` and declares
  `list_files`, `read_file`, `search`, and `analyze_reachability`;
- `dependency-risk-judge` loads `dependency-risk-review` and declares no tools.

Each role has its own manifest, role prompt, skill, system trust prompt, and
task template. Shared loading code validates those assets without discovering
additional roles.

Every real role session:

- uses `CopilotClient(mode="empty")`;
- registers and explicitly selects only its packaged custom agent;
- loads only its packaged custom-source skill;
- receives one validated `AgentTask`;
- denies every unlisted permission request;
- disables repository, user, plugin, hook, instruction, MCP, remote-session,
  and automatic skill or agent discovery;
- shares one bounded deadline across client startup, attempts, tools, and model
  work;
- preserves cancellation as cancellation.

SDK events must confirm the expected custom agent, its exact tool list, and its
custom skill source. Missing, mismatched, inferred, or deselected runtime state
is a configuration failure. The final assistant event must remain bound to the
selected role.

The child environment contains only required runtime values and the Copilot
credential. It does not inherit the GitHub collection token or unrelated
environment secrets.

## Investigator attempts and tools

Each attempt receives a fresh repository-tool cache and byte budget. Successful
observations from failed attempts are not carried into the selected finding.

Every accepted real-model attempt must invoke `analyze_reachability` at least
once. The model cannot choose the executable, command, rule, pattern, path,
engine, or configuration. Repeated calls return the attempt-local cached
result.

See [`repository-evidence.md`](repository-evidence.md) for file controls.

## Structural analyzer

The application uses pinned `ast-grep-cli==0.45.3` for bounded JavaScript and
TypeScript syntax evidence. Python selects fixed operations and stages only
approved `.js`, `.jsx`, `.mjs`, `.cjs`, `.ts`, and `.tsx` files. The model
cannot choose commands, rules, patterns, paths, engines, or configuration.

The subprocess has no command shell, package manager, repository rules, runtime
download, network access, or credentials. Trusted Python validates the engine
version, JSON shape, paths, ranges, unchanged source bytes, findings, and
resource limits before creating citations.

Agent-facing states are `syntax_usage_found`, `no_syntax_match`, `incomplete`,
and `unavailable`. Only the first is positive evidence. The others cannot prove
non-reachability or support non-applicability.

Default limits are 10,000 staged files, 64 MiB staged input, 4 MiB stdout,
256 KiB stderr, 500 findings, and 60 seconds. A second analyzer requires a
concrete adapter and ADR covering license, distribution, execution boundaries,
evidence semantics, validation, limits, failure behavior, and decision
authority. Do not add an analyzer registry before that implementation exists.

## Output validation

The prompt requests one JSON object containing one finding. The boundary also
accepts one object surrounded by non-authoritative prose or a Markdown fence.
Zero objects, multiple objects, or an invalid object consume retry budget.

Trusted Python validates:

- workflow and run identity;
- repository, alert, request, snapshot, and policy identity;
- recommendation and reason-code permission;
- confidence and safety flag types;
- every cited observation;
- required analyzer invocation.

The complete successful real-model response is stored as `raw_content` inside
`agent-output.raw.json`. Only the extracted and validated finding can influence
the result.

## Two-critic judge

After a real investigator finding validates, one additional no-tool model turn
reviews it through:

1. an evidence critic;
2. a practical-applicability critic.

The judge runs as the explicit `dependency-risk-judge` custom agent with the
`dependency-risk-review` skill. Its manifest, SDK tool list, and
`available_tools` are all empty. The skill adds methodology but no capability.

The judge receives compact validated context, not repository access. It may
accept the primary finding unchanged or replace it with another complete
finding that uses the same task identity, permitted outcome pair, and a subset
of already validated citations.

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
| Analyzer deadline | 60 seconds |
