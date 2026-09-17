# Artifacts and offline fixtures

Read this page only when changing report publication, schemas, or fixture
loading. The workflow contract remains authoritative for publication safety.

## Run artifacts

Successful runs write beneath:

```text
<output>/<owner>_<repo>/<alert-number>/<correlation-id>/
```

Depending on the selected route, a run may contain:

| Artifact | Purpose |
|---|---|
| `input.json` | Invocation identity and run mode |
| `evidence.json` | Canonical typed evidence and digest |
| `deterministic-decision.json` | Initial decision or agent task |
| `repository-reference-evidence.json` | Bounded package-reference result |
| `agent-task.json` | Validated task supplied to Copilot |
| `agent-capability.json` | Selected capability, assets, analyzer, tools, model, diagnostics, and attempts |
| `reachability-evidence.json` | Validated structural analyzer result |
| `agent-output.raw.json` | Untrusted model output |
| `agent-primary-finding.json` | Validated pre-judge finding |
| `judge-review.json` | Judge result or explicit non-blocking failure |
| `agent-findings.json` | Finding selected for reconciliation |
| `report.json` | Authoritative final report |
| `report.md` | Rendering of `report.json` |
| `failure.json` | Stage-classified failure |

Agent-specific artifacts exist only when that stage runs. Collection failures
may be written under `<output>/_failed/<correlation-id>/`.

## Offline fixtures

Fixtures under `examples/offline-cases/` contain `case.json`, `alert.json`, and
`repository/`. Dismissal fixtures also contain `request.json`. Optional files
are:

- `agent-response.json`;
- `policy.json`;
- `post-analysis-request.json`;
- `post-analysis-alert.json`.

`agent-response.json` may be absent only when routing is terminal or the caller
supplies a model turn. Positive Python triage results are terminal;
inconclusive Python routes and dismissal investigation routes require a
scripted response or selected real model when they reach the Python
investigator. Scripted tool calls use the same names and argument objects as
the bounded runtime tools; `$task.*` identity placeholders and
`$observations` are replaced by the offline fake. Command-line policy
overrides fixture policy, which overrides the packaged default. The fixture
inventory and expected behavior are maintained in
`tests/decision_tree_cases.json`.

Production-shaped Python fixtures cover Poetry transitive direct imports, uv
parent-only use, pip-compile include/`# via` provenance, mixed-language
analysis, and reviewed distribution/import mapping. They are anonymous and
credential-free.

Evidence format, task format, and report schema version `3.0` use
ecosystem-neutral `dependency` fields. Evidence records bounded dependency
paths with edge-aligned kinds, nullable bounded requirements, and effective
conditions, plus separate pip provenance. Path requirements are constraints,
not active-environment proof. Aggregate path truncation remains on dependency
evidence and agent tasks rather than individual paths. Agent tasks carry
candidate paths and validated import targets without upgrading either to
active-environment or transitive-execution proof.

Installed dependency instances serialize path, version, relationship,
comparability, development-only state, explicit descriptive `source_kind`, and
an optional `source_locator`. Version scheme is serialized once on the owning
dependency evidence, not repeated on each instance. Source metadata does not
grant proof authority.

`agent-task.json` is the exact bounded model-facing projection, not a truncated
`EvidenceBundle`. It contains total counts, deterministic typed samples, and
explicit truncation indicators for installed instance details, dependency
consumers, dependency paths, manifest declarations, and dependency provenance.
The legacy duplicated `installed_instances` string tuple is not part of the
format. Validated import targets remain complete. Task construction rejects
canonical serialized output above 24,000 characters before model dispatch.
Existing version 1.x and 2.x artifacts remain historical inputs and are not
silently reinterpreted.

## Agent capability evaluations

`evaluate-agent-capabilities` reads a version `1.0` local manifest. Each case
names an offline fixture and expected final result. Relative fixture paths are
resolved from the manifest directory.

Successful evaluation writes:

```text
<output>/<evaluation-id>/
  evaluation.json
  cases/<case-id>/...workflow artifacts...
```

`evaluation.json` has format `1.0` and `authoritative: false`. It records the
manifest digest, requested and observed model identities, selected capability
digest, final result summaries, validation status, attempt outcomes, and
elapsed time. Case workflow reports remain ordinary local workflow artifacts,
but the evaluation summary cannot publish a Dependabot decision.

Without `--model`, evaluation loads and renders the selected packaged agent,
prompt, and skill, then replays each fixture's `agent-response.json`. This
tests asset validity, routing, tools, validation, reconciliation, and
publication, but not model response quality. With `--model`, each case uses
the same assets in a fresh bounded real-Copilot boundary. The command does not
call GitHub or mutate fixtures.
