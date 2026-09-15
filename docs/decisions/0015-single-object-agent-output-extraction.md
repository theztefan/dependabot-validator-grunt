# ADR 0015: Single-object agent output extraction

- **Status:** Accepted
- **Date:** 2026-09-11
- **Amends:** Strict whole-response JSON parsing

## Context

The custom-agent prompt requires a bare `{"finding": {...}}` JSON response.
During live SDK acceptance, both model attempts returned one complete,
schema-shaped JSON object but wrapped it in explanatory prose or a Markdown
fence. Strict whole-response `json.loads` classified both attempts as
malformed before identity, permission, citation, or reconciliation validation
could run.

The complete response is already preserved as untrusted raw output. Surrounding
prose does not need to become authoritative or appear in the validated report.

## Decision

- Preserve the complete raw model response unchanged.
- Extract the first decodable JSON object from the response.
- Reject responses containing no JSON object or another decodable JSON object
  after the selected object.
- Treat all surrounding text as non-authoritative and discard it from the
  validated finding.
- Continue applying the complete task identity, permitted proposal pair,
  schema, citation, confidence, uncertainty, injection, and deterministic
  reconciliation checks to the extracted object.
- Define numeric confidence and the exact search citation object shape in the
  custom-agent response contract; require fail-closed human review when exact
  citations are unavailable.

## Consequences

- Fenced or prose-prefixed single-object responses can proceed to trusted
  validation.
- Multiple-object responses remain ambiguous and fail closed.
- Raw artifacts retain all model text for diagnosis without allowing that text
  to influence the final result.
