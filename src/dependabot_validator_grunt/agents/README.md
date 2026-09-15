# Agent definitions

Store each SDK custom agent in a named directory with an `agent.json` manifest
and a separate Markdown prompt. `copilot_assets.py` loads the selected manifest
explicitly; repository, user, and plugin agent discovery remain disabled.

The manifest declares identity, prompt asset, exact tools, preloaded skills,
and inference behavior. Keep the prompt concise: it owns only the role and
response contract. Investigation methodology belongs in the eagerly preloaded
skill; trust invariants and task data belong in their dedicated layers.

The investigator declares the four bounded repository tools. The judge
declares an empty tool list. Both must still be selected explicitly and
validated through SDK events.

Neither file may contain executable code, grant permissions, set policy
thresholds, or make final decisions.
