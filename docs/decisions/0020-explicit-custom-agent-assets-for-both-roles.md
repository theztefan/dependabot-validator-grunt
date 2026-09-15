# ADR 0020: Define both model roles as explicit custom agents

- **Status:** Accepted
- **Date:** 2026-09-15
- **Amends:** ADR 0008 and ADR 0018

## Context

The investigator used the SDK's custom-agent and custom-skill model, while the
judge ran as an unselected default agent. Judge methodology lived in its system
prompt and its response contract lived in the task template. The two model
roles therefore had different packaging, review, and runtime-verification
boundaries despite both being application-defined agents.

## Decision

- Give the investigator and judge separate explicit manifests, role prompts,
  skills, system trust prompts, and task templates.
- Keep two concrete role loaders and one shared frozen asset shape. Do not add
  filesystem discovery or a general agent registry.
- Require each manifest to name one exact prompt and one exact skill, disable
  inference, and declare its complete tool list.
- Keep the investigator's four repository tools.
- Give the judge an empty manifest tool list, no SDK tools, an empty
  `available_tools` list, and the same deny-by-default permission handler.
- Verify custom-agent inventory, selected-agent identity and tools,
  custom-source skill loading, no deselection, and final response identity for
  both sessions.
- Keep trust rules in system prompts, role and output contracts in agent
  prompts, methodology in skills, and typed data in minimal task templates.

## Consequences

- Both roles are visible and reviewable under `agents/` with the same
  customization structure.
- A judge skill changes guidance, not capability; the judge remains no-tool and
  repository-blind.
- Packaging and boundary tests must cover both complete asset sets and reject
  orphaned, mismatched, or unexpectedly loaded assets.
- Adding another role still requires an explicit loader and reviewed runtime
  path rather than automatic discovery.
