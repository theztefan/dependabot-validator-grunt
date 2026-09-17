# ADR 0026: Version investigator capability bundles and evaluations

- **Status:** Superseded
- **Date:** 2026-09-17
- **Amends:** ADR 0008, ADR 0014, ADR 0020, and ADR 0022
- **Consistent with:** ADR 0024 and ADR 0025
- **Superseded by:** ADR 0027

## Context

The first multi-ecosystem implementation packages separate npm and Python
investigator custom agents. Their repository tools, SDK lifecycle, structured
output contract, permission boundary, and deterministic reconciliation are the
same. Their package-usage methodology and analyzer profile differ.

Adding one custom-agent identity for every package manager would duplicate the
same runtime boundary. Keeping one identity per language family would remain
workable, but agent names and SDK inventory events are configuration
provenance, not proof that a model followed the selected methodology.

The product also lacks a versioned way to identify the exact investigator
assets used by a run or compare a candidate capability bundle against the
current implementation. Static review alone cannot establish whether a prompt
or skill change improves correctness, abstention, retries, latency, or cost.

## Decision

- Add one explicit bundled investigator custom-agent identity. Trusted application code
  selects one closed, versioned capability bundle from the validated task.
- The bundled manifest owns the stable identity, common role prompt, fixed
  tools, and disabled inference. A bundle names an application-owned analyzer
  profile and one packaged skill. It cannot grant tools, permissions, policy
  outcomes, or evidence authority. This replaces ADR 0008's requirement that
  one manifest statically name the investigator skill; each bundled or legacy
  manifest still names its own prompt asset.
- Keep the investigator's four bounded repository tools fixed at the shared
  runtime boundary. Package-manager collection and proof capabilities remain
  deterministic.
- Preserve the existing per-role implementation temporarily as a
  non-default evaluation and rollback control. Do not expose model-selected
  routing or automatic agent discovery.
- Select bundles through an exhaustive direct branch. Unknown ecosystems fail
  configuration. GitHub's attested ecosystem remains distinct from the
  selected package manager, including pip-reported uv projects.
- Treat selected-agent, inventory, and expected-skill SDK events as runtime
  diagnostics. This replaces ADR 0008 and ADR 0014's requirement that missing
  or mismatched expected identity events fail the run. Continue to fail closed
  when the runtime positively reports an unexpected enabled skill, extra
  executable tool, agent deselection, or response from a conflicting observed
  runtime-agent identifier.
- Keep explicit `mode="empty"`, `available_tools`, bounded Python handlers,
  deny-by-default permissions, strict finding parsing, task and citation
  binding, and deterministic reconciliation.
- Continue explicitly disabling the SDK built-in `customize-cloud-agent` and
  `github-pr-media` skills. If the runtime reports either or any other
  unexpected skill as enabled, fail configuration.
- Construct judge assets only after the primary finding validates and the
  shared deadline permits review. Judge construction or execution failure
  remains non-blocking and retains the primary finding.
- Persist a versioned capability provenance artifact for every investigator run.
  Keep report format `3.0`; provenance is a separate artifact rather than a
  silent report-shape change.
- Add a local, non-authoritative evaluation command. It runs versioned cases
  against explicit investigator variants, records final outcomes and bounded
  operational metrics, and never promotes or publishes a production decision.

ADR 0024's evidence, task, and report `3.0` formats and Python positive-only
authority remain unchanged. ADR 0025's concrete npm and Python analyzer
interpreters and exhaustive direct dispatch remain unchanged; capability
bundles select those profiles rather than replacing them with a registry.

## Rejected alternatives

- **One agent per package manager:** rejected because lockfile parsing and
  evidence authority belong to deterministic collectors, while package usage
  follows language/runtime semantics.
- **Dynamic bundle or agent registry:** rejected because supported bundles are
  a small application-owned set requiring reviewed code and tests.
- **Use SDK identity events as an authorization boundary:** rejected because
  names and inventory do not constrain executable capabilities or prove model
  compliance.
- **Remove finding and citation validation with identity checks:** rejected
  because untrusted output can otherwise invent evidence, cross task
  boundaries, or propose unauthorized outcomes.
- **Delete the prior roles immediately:** rejected because paired evaluation
  and rollback require a stable control during this increment.
- **Put capability provenance directly into report `3.0`:** rejected because
  that would change the authoritative report schema without changing final
  decision semantics.

## Consequences

- New ecosystem families add one reviewed collector path, analyzer
  interpretation when needed, capability bundle, skill, and evaluation cases
  without adding a package-manager-specific agent.
- Runtime configuration is simpler and less dependent on SDK event timing,
  while capability expansion and untrusted output remain fail closed.
- Engineers can compare legacy and bundled investigators using the same
  immutable fixtures before removing the control path.
- Package data and documentation must identify bundle ownership, provenance,
  evaluation formats, and the admission criteria for another investigator
  identity.
