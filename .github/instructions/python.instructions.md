---
applyTo: "**/*.py"
description: "Python implementation and test conventions"
---

- Use Python 3.12 syntax and built-in generics.
- Use four spaces, Ruff formatting, absolute package imports, and complete type
  annotations.
- Use frozen Pydantic models for shared structured data unless mutation is part
  of the documented lifecycle.
- Keep `Any` at third-party boundaries and convert it immediately to project-owned
  types.
- Use async APIs for I/O. Bound waits and preserve cancellation.
- Test behavior and failure paths. Prefer a small fake at the Copilot boundary
  over deep SDK mocks.
