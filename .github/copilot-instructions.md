# Dependabot Validator Grunt

## Read only what the change needs

Before editing:

1. Read `README.md` for the product boundary and `docs/architecture.md` for the
   owner of the code you will change.
2. Read the relevant source and tests.
3. Use `docs/README.md` to select only the contract or reference for the
   affected boundary.
4. Use `docs/decisions/README.md` to select only ADRs for the decision being
   changed. ADRs explain rationale; they do not override current contracts.
5. Use the topic index in `.github/LESSONS_LEARNED.md`; do not read unrelated
   entries.
6. If `.logs/` contains a plan marked `ready for implementation` or
   `in-progress`, resume it. Ignore complete or historical plans.

For workflow inputs, evidence, routing, permissions, outputs, failures,
validation, or publication, update `docs/workflow-contract.md` before code.
Run the narrowest relevant check before editing and the full baseline before
finishing. Commands live in `docs/development.md`.

## Architecture guardrails

This is a CLI application, not a general framework. Organize modules by concrete
responsibility and follow `docs/architecture.md`. Do not introduce layers,
registries, factories, or protocols without a current use.

- Keep CLI parsing and dependency construction in `main.py`.
- Put workflow orchestration in `workflow.py`.
- Isolate Copilot SDK lifecycle and session behavior in `copilot.py`.
- Keep GitHub access, tools, models, validation, and reporting in focused modules.
- Add one protocol at the Copilot boundary so default tests can use an offline
  fake. Add other abstractions only for a second implementation or clear test
  seam.
- Treat `agents/`, `system-prompts/`, `prompts/`, `skills/`, `tools/`, and
  `policies/` as package data, never Python code.

Build typed, serializable evidence before agent execution. Keep deterministic
facts and decisions outside prompts. Give each agent only its required context,
skills, and explicitly allowlisted tools. Deny permissions by default and never
use wildcard or blanket approval.

## Iteration workflow

Use the full workflow only for multi-phase work or changes to core workflow,
permissions, validation, or publication safety. For a single-phase feature or
maintenance change, onboard, inspect focused context, make a concise plan,
implement, run the baseline, and request one independent review. Do not create
phase logs for single-phase work.

For multi-phase work, copy `.github/templates/execution-plan.md` to
`.logs/<work-item>/`, use dependency-ordered testable phases, and keep one phase
log per phase. Review the plan and each completed phase in a separate context,
record concrete findings and dispositions, then request an independent final
implementation review. Reconcile every plan item before the full baseline.

Canonical commands are maintained in `docs/development.md`. Run targeted tests
during a phase and the full baseline before completion. Do not update baselines
or weaken checks merely to make failures pass.

## Copilot SDK rules

- Target `github-copilot-sdk>=1.0.13` and Python 3.12-3.14.
- Construct `CopilotClient` with `mode="empty"` so sessions must declare their
  available tools.
- Use async context managers for client and session lifecycle.
- Isolate SDK types and lifecycle in `copilot.py`.
- Use append-mode system instructions unless replacement is explicitly required
  and reviewed.
- Validate custom tool input with Pydantic and return JSON-serializable,
  structured results.
- Use explicit tool allowlists and role-specific permission handlers.
- Treat agent output as untrusted input: parse, validate, and preserve failed
  artifacts separately from approved output.
- Query available models at runtime; do not encode a changing model name as a
  domain invariant.
- The first SDK implementation must add behavioral tests proving that session
  creation passes both an explicit tool allowlist and permission handler, and
  that the handler denies unlisted requests. Static safety tests are only a
  backstop.

## Change discipline

- Prefer precise types and immutable shared models.
- Surface errors with typed outcomes or specific exceptions; no broad silent
  fallbacks.
- Keep tests offline by default. Fake the Copilot and network boundaries.
- An ADR in `docs/decisions/NNNN-slug.md` is required to change core module
  ownership, a workflow invariant, the permission model, or
  validation/publication policy.
  Follow `docs/decisions/README.md`. Other documentation changes do not require
  an ADR.
- Do not implement workflow behavior until `docs/workflow-contract.md` defines
  its inputs, evidence, stages, outputs, failure states, and permission policy.
- Add only durable, repository-specific guidance to instruction files. Avoid
  generic language advice, stale test counts, and duplicated rules.
