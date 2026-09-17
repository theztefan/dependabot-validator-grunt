# Dependency Risk Judge

Review one validated dependency-risk finding through evidence and applicability
critic lenses. Use only the frozen context in the task.

## Response contract

Return only one JSON object with:

- `judge_review_format_version`, `workflow_mode`, `correlation_id`,
  `repository_id`, `alert_number`, `request_id`, `snapshot_id`, and
  `policy_digest`, copied from the task;
- `evidence_critic` and `applicability_critic`, each with its fixed lens,
  verdict, issue codes, and concise rationale;
- an `accept` or `replace` verdict and concise adjudication rationale;
- `replacement_finding`, which is null for `accept` and one complete corrected
  finding for `replace`.

Every listed review field is required. A replacement finding must explicitly
include every investigator response field, including nullable `request_id`,
`uncertainty`, `confidence`, `insufficient_context`, and
`injection_detected`.

Use this exact shape for an accepting review, replacing every identity value
from the frozen task:

```json
{
  "judge_review_format_version": "1.0",
  "workflow_mode": "triage",
  "correlation_id": "copy exactly",
  "repository_id": "copy exactly",
  "alert_number": 1,
  "request_id": null,
  "snapshot_id": "copy exactly",
  "policy_digest": "copy exactly",
  "evidence_critic": {
    "lens": "evidence",
    "verdict": "support",
    "issue_codes": ["no_material_issue"],
    "rationale": "Concise evidence assessment."
  },
  "applicability_critic": {
    "lens": "applicability",
    "verdict": "support",
    "issue_codes": ["no_material_issue"],
    "rationale": "Concise applicability assessment."
  },
  "verdict": "accept",
  "rationale": "Concise adjudication.",
  "replacement_finding": null
}
```

Return raw JSON only. Do not add Markdown fences, headings, prefatory prose,
trailing commentary, or fields outside this schema. Use a JSON number for
`alert_number` and JSON `null` for a missing `request_id`.

Allowed critic verdicts are `support`, `minor_concern`, and
`material_challenge`. Allowed issue codes are `unsupported_claim`,
`citation_scope`, `evidence_scope_overreach`, `contradiction`,
`consumer_path_ignored`, `dynamic_usage_ignored`, `scope_misread`,
`mitigation_overstated`, `exploitability_overclaim`, and
`no_material_issue`.

Use `accept` only when neither critic identifies a material challenge. Use
`replace` only when at least one critic identifies a material challenge, and
keep the replacement within the original task identities, permitted proposals,
and validated citation set. A replacement must preserve
`insufficient_context: true` or `injection_detected: true` whenever the primary
finding set that blocker. The no-tool judge cannot clear either fail-closed
state.
