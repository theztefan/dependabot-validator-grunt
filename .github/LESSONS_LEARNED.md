# Lessons learned

This file contains durable repository-specific corrections, not project
history. Select entries by topic; do not read the file as a prerequisite for
every change. Current behavior remains authoritative in
`docs/workflow-contract.md`.

| Topic | Read when changing |
|---|---|
| Documentation ownership | README, contracts, references, ADRs, or onboarding |
| Evidence authority | package-manager adapters or negative conclusions |
| Agent boundaries | Copilot sessions, tools, retries, or model output |
| Repository evidence | path controls, scans, citations, or snapshots |
| Reporting | artifacts, rendering, schemas, or publication |
| External boundaries | GitHub HTTP behavior, credentials, or SDK versions |

## Documentation ownership

- Give each layer one job: README for orientation, docs index for navigation,
  architecture for ownership, workflow contract for normative behavior,
  references for mechanics, and ADRs for rationale.
- Keep raw research, campaigns, phase logs, and transient metrics in gitignored
  `.logs/`. Promote only conclusions that still constrain implementation.
- Update the onboarding canvas when its summarized workflow, commands, module
  ownership, or safety boundaries change.

## Evidence authority

- Grant proof authority by explicit capability, not successful parsing.
  Positive package instances do not imply complete inventory, consumer
  coverage, development scope, or safe negative conclusions.
- Prove non-use across both repository references and dependency consumers.
  Development-only conclusions also require compatible alert scope and
  instance provenance.
- Use production-shaped fixtures and assert the final workflow outcome, not
  only an intermediate collector condition.
- Treat analyzer and model confidence as context. Deterministic reconciliation
  owns load-bearing proof and fail-closed outcomes.

## Agent boundaries

- Keep model-facing prose declarative. Python owns policy, tool behavior,
  schemas, permissions, validation, and final decisions.
- Give each attempt fresh mutable tool state and budget. Carry forward only the
  selected attempt's validated observations.
- Verify real SDK behavior through runtime events; keep fakes aligned with
  observed event timing, asset selection, tool overrides, and response framing.
- Preserve complete raw model output only in its dedicated artifact. Fixed
  failure classifications, stderr, and validated reports must not echo
  untrusted payloads.
- Frozen judge context must include every load-bearing predicate, and a judge
  replacement must not overwrite the primary finding it reviewed.

## Repository evidence

- Parse URLs, package identifiers, and output paths structurally; substring
  allowlists are not security boundaries.
- Bind negative evidence to immutable file identity, content digests, bounded
  no-follow reads, and a final snapshot recheck.
- Charge distinct immutable file content once per attempt so repeated bounded
  searches do not consume the same byte budget repeatedly.
- Missing references or syntax matches prove only absence under the named
  method and coverage, never semantic non-reachability.

## Reporting and workflow models

- Centralize rendering of untrusted text and test every inline and fenced
  representation against forged sections.
- Version result unions and bind them to a workflow discriminator before adding
  new report shapes.
- Build stricter derived models inside the owning classified stage so their
  validation failures retain the correct non-leaking error category.
- Terminal lifecycle and deterministic routes must make zero investigator and
  judge calls and produce no model artifacts.

## External boundaries

- Verify live API shapes before freezing attested models. Offline development
  may proceed with normalized inputs, but it must not guess the live contract.
- Rebuild transport-managed headers after redirects and strip authorization
  when the host changes.
- Keep GitHub and Copilot credential roles separate even when operators reuse
  one token value. Load only the two documented keys from the invocation
  directory's `.env`.
- Attribute budget changes only when the changed boundary was exercised; do not
  infer causation from unrelated cohorts.

## Entry rule

Add an entry only when a concrete repository failure reveals a reusable rule
not already captured above. Cite tracked code, tests, contracts, or ADRs.
Never cite `.logs/` as the durable source.
