# Development workflow

## Setup

```text
uv sync --all-groups --locked
uv run python -m copilot download-runtime
```

The runtime download is explicit in setup and automatic on first SDK use as a
fallback. CI provisions it on one Python leg as a download canary.

The installed CLI parses only `.env` in the invocation directory, imports only
the two credential variables, and does not override variables already present
in the environment. `create_app()` remains side-effect-free for tests and
embedding.

## Canonical checks

```text
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv build
```

## Non-trivial iterations

Use the workflow in `.github/copilot-instructions.md`. Local records go under:

```text
.logs/<work-item>/
  execution-plan.md        # sole active execution state
  phase-1.md
  phase-2.md
```

Copy the versioned templates from `.github/templates/`. The logs are working
state, not durable documentation. Promote architectural decisions to an ADR and
reusable corrections to `.github/LESSONS_LEARNED.md`.

Name `<work-item>` with its issue number when one exists; otherwise use a stable
kebab-case slug. Reuse that directory when resuming work.
The absence of `.logs/` is normal until multi-phase work begins.
When more than one plan exists, resume the one marked `ready for implementation`
or `in-progress`; never resume a plan marked historical or complete.

## Testing strategy

- Unit tests cover deterministic rules and workflow behavior.
- Boundary tests use small fakes for Copilot and GitHub interactions.
- Integration tests may exercise the SDK or GitHub only when explicitly marked.
- Default tests are offline, deterministic, and independent of user credentials.
- Safety tests reject permissive SDK configuration and executable code in agent
  asset directories.

When integration tests exist, run them explicitly:

```text
uv run pytest -m integration
```

SDK boundary tests cover explicit custom-agent selection, custom-source skill
loading, exact tool allowlists, permission denial, timeout/cancellation,
malformed output, and SDK failure. New boundary behavior must keep equivalent
offline coverage.
