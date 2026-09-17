# npm evidence reference

The current npm-ecosystem collector supports:

- root `package.json`;
- root `package-lock.json` versions 1, 2, and 3;
- Yarn Classic `yarn.lock` version 1;
- pnpm `pnpm-lock.yaml` version 9.0;
- npm workspaces whose entries resolve through the root lockfile.

GitHub may identify a dependency through `package.json` or its lockfile. A
`package.json` alert binds to the single sibling `package-lock.json`,
`yarn.lock`, or `pnpm-lock.yaml`; multiple sibling lockfiles are rejected as
ambiguous. Lockfiles owned by npm workspace entries remain unsupported.

## Collected evidence

Trusted collection code records every matching installed instance and, where available:

- version;
- workspace, direct, development, optional, or transitive relationship;
- explicit registry, URL, VCS, path, workspace, or unknown source provenance;
- development-only provenance;
- reverse dependency consumers;
- manifest paths;
- completeness issues.

Evidence also records package-manager identity, lockfile path/version, and
proof capabilities. The collector never runs npm, Yarn, pnpm, Corepack,
lifecycle scripts, repository commands, or build tools.

## Version evaluation

Supported advisory comparators are `<`, `<=`, `>`, `>=`, and `=`. Comma is
logical AND. npm SemVer precedence is used, build metadata is ignored, and
installed prereleases remain concrete versions for range comparison.

Package absence is conclusive only with `complete_inventory` capability. An
unaffected-version proof requires that capability and every resolved instance
to be comparable and outside the vulnerable range. Package-lock v1, Yarn v1,
and pnpm v9.0 expose only `resolved_instances`: one concrete vulnerable version
can prove positive applicability, while negative and development-only
conclusions remain unavailable.

Package-lock v1 is read as its legacy nested dependency tree. A matching
top-level entry is classified from the sibling manifest when possible, and
nested entries are transitive. Registry-backed exact SemVer instances can
support positive applicability. The adapter does not claim that the legacy
tree completely describes hoisting, consumers, workspaces, or production
scope. Tree traversal steps, matching instances, unique consumers, and
aggregate serialized evidence output are independently bounded. Bound
exhaustion fails collection and never publishes ordinary authorized partial
positive evidence.

## Completeness

Valid input may produce partial or unsupported evidence for cases including:

- aliases or non-comparable git/tarball entries;
- external, malformed, or unresolved workspace links;
- declared dependencies missing from the lockfile;
- conflicting lockfile-v2 `packages` and `dependencies` data;
- unresolved workspace mappings;
- installed instances without a comparable version.

Partial or unsupported evidence cannot produce deterministic non-applicability
approval. Agent analysis may add repository context, but cannot replace a
missing trusted package or version proof.

Source provenance describes the lockfile record and does not grant authority.
Supported in-repository workspace links are recorded as workspace sources.
Recognized registry resolutions are registry sources, while external tarballs,
VCS references, local paths, and ambiguous records remain explicitly
classified without being promoted to registry provenance.

Malformed syntax, an unsupported lockfile version, ambiguous sibling lockfiles,
an unsafe path, invalid UTF-8, size overflow, or file drift fails the
`npm-evidence` stage instead of producing partial evidence.

Yarn and pnpm lockfiles use stable logical instance locators. They are not
assertions about physical `node_modules` paths or production deployment state.

Vulnerable-range parsing is a deterministic decision concern, not an npm
collection completeness issue. An unparseable range produces a fail-closed
decision after evidence collection.

A `link: true` entry is supported only when its normalized target is an
in-repository workspace represented by the root lockfile and resolves to the
corresponding package entry.
