# ADR 0013: Invocation dotenv and shared credential values

- **Status:** Accepted
- **Date:** 2026-09-11
- **Amends:** The workflow credential-value separation invariant

## Context

Live commands require separate environment variable names for GitHub
collection and Copilot authentication. Operators commonly keep local
credentials in a gitignored `.env`, but the CLI did not load that file.

The application also rejected equal variable values. That enforced credential
value uniqueness, but prevented a token authorized for both GitHub API and
Copilot use from supporting a local evaluation. Functional role isolation does
not require value uniqueness: the GitHub client and Copilot SDK can still
receive credentials through separate, explicit construction paths.

Token reuse has a security cost. One credential may need broader privileges,
and revocation, audit, accidental exposure, and compromise affect both roles.

## Decision

- Add `python-dotenv` as a runtime dependency.
- At the installed CLI entrypoint, parse only `.env` in the current invocation
  directory and import only `DEPENDABOT_GITHUB_TOKEN` and
  `COPILOT_GITHUB_TOKEN` before command dispatch.
- Do not search parent directories and do not override variables already
  present in the process environment, including empty values.
- Keep `create_app()` side-effect-free.
- Continue requiring both role variables when their respective boundaries are
  selected, but allow them to contain the same value.
- Continue passing GitHub collection credentials only to `GitHubClient`.
- Continue passing Copilot authentication through the SDK's explicit token
  argument while giving the SDK child process only the existing runtime
  environment allowlist.
- Do not import unrelated dotenv keys, including proxy, certificate, temporary
  directory, or SDK runtime values, into the application environment.
- Continue excluding credential values from prompts, evidence, reports,
  failures, and raw agent artifacts.
- Recommend distinct least-privileged tokens even though they are no longer
  mandatory.

## Consequences

- Local operators can place both credential variables in a gitignored `.env`
  and invoke the CLI without manually sourcing it.
- Exported variables remain authoritative and can intentionally suppress a
  value from `.env` by being set to an empty string.
- A shared token can enable live end-to-end evaluation when it is authorized
  for both GitHub collection and Copilot access.
- Shared-token users accept combined privilege, audit, revocation, and exposure
  blast radius.
- Library-style callers of `create_app()` do not read local files implicitly.
