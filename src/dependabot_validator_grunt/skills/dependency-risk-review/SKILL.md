---
name: dependency-risk-review
description: Challenge one validated dependency-risk finding using frozen evidence.
---

# Dependency Risk Review

## Method

1. Use the evidence lens to test grounding, citation scope, contradictions, and
   claims stronger than the typed evidence.
2. Use the applicability lens to construct the strongest practical counter-case
   from dependency consumers, dynamic loading, scope, mitigations, and
   exploitability limits.
3. Distinguish a material correction from a minor concern. Do not replace a
   finding merely to rephrase it.
4. If replacement is required, use only facts and citations already present in
   the frozen context.

## Decision rules

- Accept when the finding is proportionate to the evidence and no material
  correction is needed.
- Replace only when a material challenge changes the claim, uncertainty,
  confidence, recommendation, reason code, or valid citation subset.
- Never request repository access, tools, or additional evidence.
- Never invent facts, citations, permissions, or outcomes.
