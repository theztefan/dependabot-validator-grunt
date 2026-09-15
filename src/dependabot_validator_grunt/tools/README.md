# Tool definitions

Store model-facing names and descriptions for trusted custom tools here.
`copilot_assets.py` validates the declarative names against the selected custom
agent, and `copilot_tools.py` binds those definitions to typed Python handlers.

Tool definitions are metadata only. Authorization, input validation, bounds,
and execution remain in Python.
