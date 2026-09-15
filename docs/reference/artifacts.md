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
supplies a model turn. Command-line policy overrides fixture policy, which
overrides the packaged default. The fixture inventory and expected behavior are
maintained in `tests/decision_tree_cases.json`.
