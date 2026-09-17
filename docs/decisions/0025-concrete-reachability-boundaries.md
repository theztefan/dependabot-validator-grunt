# ADR 0025: Split concrete structural-analysis responsibilities

- **Status:** Accepted
- **Date:** 2026-09-16
- **Amends:** ADR 0001 and ADR 0024
- **Amended by:** ADR 0029

## Context

The first multi-language structural analyzer accumulated trusted file staging,
application-owned ast-grep configuration, subprocess execution, output and
resource validation, JavaScript/TypeScript interpretation, Python
interpretation, citation construction, and public result coordination in one
module. Those responsibilities now have distinct reasons to change, but the
application still has one analyzer and exactly two explicit language profiles.

Splitting by concrete responsibility improves reviewability only if the
security boundary remains cohesive and profile selection stays visible.
Introducing an interpreter protocol, registry, plugin system, class hierarchy,
or dynamic discovery would obscure the fixed permission model without
providing a second implementation.

## Decision

- Keep `reachability.py` as the public runner and result coordinator, retaining
  the existing `AstGrepRunner` import and a compatible
  `AstGrepReachabilityRunner` name.
- Put trusted staging, application-owned configuration, subprocess execution,
  engine verification, deadlines, output and stderr bounds, file and byte
  bounds, raw-output validation, immutable source rechecks, finding caps, and
  citation construction together in `reachability_ast_grep.py`.
- Put npm JavaScript/TypeScript interpretation in `reachability_npm.py` and
  Python interpretation in `reachability_python.py`.
- Select the `npm` or `python` interpreter through one exhaustive direct branch
  in the public coordinator.
- Share only concrete raw-match access, citation validation, de-duplication,
  and bound enforcement from the ast-grep boundary. Do not add an interpreter
  abstraction or discovery mechanism.
- Preserve every workflow status, limitation, operation set, ordering rule,
  target binding, and positive-only evidence semantic.

## Rejected alternatives

- **Keep one large module:** rejected because trusted execution mechanics and
  two independent language semantics require unrelated changes in the same
  file.
- **Create a generic analyzer or interpreter framework:** rejected because
  there is one analyzer and two fixed branches, so a registry or protocol would
  add indirection without another implementation.
- **Move citation validation into each interpreter:** rejected because path,
  byte-range, immutable-source, and result-bound checks are part of the single
  trusted subprocess boundary.

## Consequences

- Security and resource controls remain reviewable in one focused module.
- npm and Python syntax semantics can evolve independently without changing
  subprocess mechanics.
- The public API and deterministic workflow behavior remain stable.
- A new analyzer or language family still requires an explicit architectural
  decision rather than dynamic registration.
