# Skills

Store SDK-loadable methodology under `<skill-name>/SKILL.md` with explicit
`name` and `description` front matter. `copilot.py` materializes only the
selected role's skill and verifies through SDK events that it loaded from the
`custom` source.

Skills may guide investigation, certainty, and escalation. They must not
perform data collection that belongs in Python workflow code or become a
second source of policy authorization.

The SDK eagerly injects the full content of every skill named by a custom
agent. Keep each skill single-purpose, state its tool dependencies, and avoid
repeating session trust rules, response schemas, or task fields.
