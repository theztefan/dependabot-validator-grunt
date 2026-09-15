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

Allowed critic verdicts are `support`, `minor_concern`, and
`material_challenge`. Allowed issue codes are `unsupported_claim`,
`citation_scope`, `evidence_scope_overreach`, `contradiction`,
`consumer_path_ignored`, `dynamic_usage_ignored`, `scope_misread`,
`mitigation_overstated`, `exploitability_overclaim`, and
`no_material_issue`.

Use `accept` only when neither critic identifies a material challenge. Use
`replace` only when at least one critic identifies a material challenge, and
keep the replacement within the original task identities, permitted proposals,
and validated citation set.
