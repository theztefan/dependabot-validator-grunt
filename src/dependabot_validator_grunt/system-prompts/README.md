# Session system prompts

Store per-session trust and application safety invariants here. The selected
role's prompt is appended through the SDK session configuration and remains
separate from custom-agent role prompts, reusable skills, and dispatched tasks.

Use a short tagged block so the boundary is distinct from the SDK's preserved
system instructions. Do not repeat agent output fields, tool documentation, or
investigation methods here.

System prompts may constrain model behavior but do not grant tools,
permissions, outcomes, or publication authority.
