# Engineer onboarding canvas

This project extension renders an interactive onboarding guide for Dependabot
Validator Grunt. Ask Copilot to open the **Engineer onboarding** canvas, or open
the `engineer-onboarding` canvas ID with an optional starting topic.

The **Full flows** page visualizes the end-to-end application path for offline
and live dismissal review and alert triage, including deterministic,
investigator, drift, publication, and failure branches. The **Evaluate agents**
page explains how to run non-authoritative regression cases against the current
investigator.

The guide summarizes the repository's authoritative documentation and source:

- `README.md`
- `docs/README.md`
- `docs/architecture.md`
- `docs/development.md`
- change-specific pages selected through the docs and ADR indexes
- `src/dependabot_validator_grunt/`

Keep every topic summary and rendered page aligned with those sources when
workflow behavior, commands, module ownership, agent assets, or safety
boundaries change. Examples should remain single-line and shell-neutral;
credential setup belongs in explanatory text rather than command prefixes.
