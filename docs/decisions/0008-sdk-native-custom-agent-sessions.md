# ADR 0008: SDK-native custom-agent sessions

- **Status:** Accepted
- **Date:** 2026-09-08
- **Amends:** ADR 0001's Copilot integration module ownership
- **Amended by:** ADR 0012, ADR 0014, ADR 0020, ADR 0026, and ADR 0027

## Context

The initial asset extraction moved model-facing prose out of Python, but the
runtime still concatenated an agent role and a skill into one session system
message. It passed `custom_agents=[]`, disabled SDK skills, and sent a JSON-only
task envelope. That layout did not represent the distinct GitHub Copilot SDK
concepts documented by the Python SDK instructions:

- session system message;
- custom-agent configuration and prompt;
- SDK-loaded skills;
- custom tools;
- dispatched user message.

The SDK Python cookbook also consistently separates session construction from
the message sent with `send` or `send_and_wait`.

## Decision

ADR 0027 supersedes the static investigator-skill binding and strict expected
identity-event requirements below. The single investigator manifest declares
no skill; trusted application code selects and materializes one ecosystem skill. Missing
or mismatched expected identity inventory is diagnostic, while positively
observed extra tools, unexpected enabled skills, deselection, or conflicting
runtime identities still fail closed.

- Keep `copilot.py` responsible for client/session lifecycle, attempts, model
  selection, event/result handling, and cleanup.
- Add `copilot_assets.py` for strict loading and validation of declarative
  session, custom-agent, skill, prompt, and tool metadata.
- Add `copilot_tools.py` for typed custom-tool inputs and executable handler
  construction.
- Define the dependency investigator as an explicit SDK
  `CustomAgentConfig`. Its manifest names the custom agent, its prompt asset,
  exact tool names, preloaded skill, and disabled inference behavior.
- Select that custom agent explicitly when creating the session. Keep
  repository and host custom-agent discovery disabled. Treat runtime agent
  deselection or a mismatched loaded-agent event as a configuration failure.
- Put application-wide trust and output-safety invariants in a separate
  append-mode system prompt.
- Load the dependency-risk skill through the SDK with one explicit packaged
  skills root. Materialize that root for filesystem-only SDK loading. Reject
  the session unless SDK events report exactly the expected skill with the
  `custom` source; do not accept repository, inherited, user, plugin, or
  built-in skill discovery.
- Keep task dispatch in a separate user prompt template. The rendered task must
  contain one fenced JSON block that round-trips to the assigned `AgentTask`.
- Keep tool metadata declarative and executable handlers in application code. The custom
  agent's tool list, declarative tool names, session `available_tools`, and
  constructed SDK tools must be identical.
- Continue using `CopilotClient(mode="empty")`, explicit permission denial,
  isolated environment variables, async context managers, and one bounded
  deadline across attempts.

## Consequences

- Agent identity, system safety, reusable methodology, task dispatch, and tool
  contracts are independently reviewable.
- The SDK receives a real custom agent and SDK-native skill configuration
  rather than one concatenated prompt.
- Adding a second agent requires a new explicit manifest and selection path,
  not automatic discovery or a registry.
- Packaging and behavioral tests must prove every referenced asset is present,
  the selected custom agent is exact, skills come only from the packaged
  directory, and tool permissions remain least privilege.
