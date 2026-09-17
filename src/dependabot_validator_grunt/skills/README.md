# Skills

This directory contains two ecosystem methods and one judge method:

- `javascript-typescript-dependency-risk-analysis/` for the npm capability;
- `python-dependency-risk-analysis/` for the pip and uv capability;
- `dependency-risk-review/` for the no-tool judge.

The same investigator selects one of the two analysis skills. The review skill
belongs only to the judge.

Store SDK-loadable methodology under `<skill-name>/SKILL.md` with explicit
`name` and `description` front matter. `agent_capabilities.py` selects one
versioned ecosystem capability and `copilot.py` materializes only its declared
skill. A positively observed enabled skill outside that selection is fatal;
missing identity inventory is recorded as diagnostic provenance.

Skills may guide investigation, certainty, and escalation. They must not
perform data collection that belongs in Python workflow code or become a
second source of policy authorization.

The SDK eagerly injects the full content of every skill named by a custom
agent. Keep each skill single-purpose, state its tool dependencies, and avoid
repeating session trust rules, response schemas, or task fields.

Reference skills from `agents/investigator-capabilities.json`, increment
`capability_version` for semantic changes, and run
`evaluate-agent-capabilities`.
