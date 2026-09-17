# Agent definitions

This directory contains exactly two active roles:

- `dependency-risk-investigator/` is the only investigator used by offline,
  evaluation, and live workflows;
- `dependency-risk-judge/` is the optional no-tool reviewer created after a
  valid primary finding.

Store each SDK custom agent in a named directory with an `agent.json` manifest
and a separate Markdown prompt. `copilot_assets.py` loads the selected manifest
explicitly; repository, user, and plugin agent discovery remain disabled.

The investigator manifest declares one stable identity, common prompt, exact
tools, and disabled inference. Trusted Python selects one ecosystem capability
from `investigator-capabilities.json` and materializes its skill. Keep prompts
concise: they own only the role and response contract. Investigation method
belongs in the skill; trust rules and task data belong in their own layers.

The investigator declares the four bounded repository tools. The judge
declares an empty tool list. Both are selected explicitly. SDK identity
mismatches are diagnostic; reported capability expansion is fatal.

Neither file may contain executable code, grant permissions, set policy
thresholds, or make final decisions.
