# Prompt templates

Store task-dispatch messages here as `.tmpl` files. Each role template contains
exactly one fenced JSON block with its one supported placeholder and no other
placeholders. The loader validates that structure; typed renderers validate the
rendered investigator task and bounded judge context.

Prompts must not duplicate role instructions, investigation methodology, policy
allowlists, output instructions, or deterministic decision logic. The task is
already self-describing typed JSON, so surrounding prose should be minimal.
