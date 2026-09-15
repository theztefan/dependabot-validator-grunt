# ADR 0014: SDK event timing and explicit tool overrides

- **Status:** Accepted
- **Date:** 2026-09-11
- **Amends:** ADR 0008's creation-time asset event requirement
- **Amended by:** ADR 0017

## Context

Live acceptance against GitHub Copilot SDK 1.0.11 exposed three runtime
contracts not represented by the offline fake:

- session event callbacks must be identity-hashable;
- custom tools named `list_files`, `read_file`, and `search` must explicitly
  declare that they override built-in names, even with `mode="empty"`;
- the runtime emits exact custom-agent selection before dispatch, but emits the
  custom-skill load event only after dispatch begins.
- SDK 1.0.11 enables the built-in `customize-cloud-agent` and
  `github-pr-media` skills unless they are explicitly disabled.

Waiting for both agent and skill events before dispatch therefore deadlocked
until the asset timeout. Skipping runtime verification would weaken the
fail-closed boundary.

## Decision

- Make the mutable session observer identity-hashable rather than value-equal.
- Mark only the three exact allowlisted repository tools as intentional
  built-in overrides.
- Explicitly disable the two SDK 1.0.11 built-in skills. Accept their exact
  complete inventory only when both are reported disabled, and continue
  rejecting every missing, unexpected, or enabled skill source or name at
  runtime.
- Before task dispatch, require the selected-agent event to match the packaged
  custom-agent name and exact tool list.
- Treat custom-agent inventory as discovery only; it cannot satisfy selected
  agent confirmation.
- Before accepting model output, require the expected single custom-source
  skill event and no agent deselection.
- When the older custom-agent inventory event is available, retain its runtime
  identifier and bind the final assistant event to it.
- SDK 1.0.11 reports `agent_id` as null on both selected-agent and assistant
  events. When no inventory identifier is available, bind response acceptance
  to the exact selected-agent event and no-deselection invariant instead.

## Consequences

- Real SDK 1.0.11 sessions can start without relaxing tool permissions or
  enabling discovery.
- Skill confirmation occurs after dispatch but before any response is trusted,
  matching the runtime's lazy skill-loading behavior.
- Offline fakes must cover both event timing and intentional tool-override
  metadata.
