# Python dependency evidence

Read this page when changing pip requirements, Poetry, uv, Python package
identity, or PEP 440 evaluation. The workflow contract defines authoritative
selection, proof capabilities, routing, and failures.

## Implementation ownership

`python_dependencies.py` is the explicit, exhaustive facade over the concrete
collectors. `pip_dependencies.py` owns requirements-file parsing and
provenance, `poetry_dependencies.py` owns Poetry declarations and candidate
graphs, `uv_dependencies.py` owns uv declarations and candidate graphs, and
`unsupported_python_dependencies.py` owns declaration-only fallback manifests.
`python_dependency_common.py` contains only shared bounded path, parsing, and
graph-projection helpers. Poetry and uv each parse their lock package array
once into manager-specific records reused for instance authority and candidate
path projection.

## Identity and versions

Preserve the GitHub-attested distribution spelling for reports. Match Python
distributions with the PyPA canonical name: lowercase and replace each run of
`-`, `_`, or `.` with `-`. Distribution identity is not Python import-module
identity. Trusted task construction uses a versioned closed mapping for common
reviewed differences, including Pillow/PIL, PyYAML/yaml,
scikit-learn/sklearn, beautifulsoup4/bs4, OpenCV/cv2,
python-dateutil/dateutil, python-dotenv/dotenv,
typing-extensions/typing_extensions, django-cors-headers/corsheaders,
djangorestframework/rest_framework, psycopg2-binary/psycopg2, PyJWT/jwt,
python-jose/jose, python-multipart/multipart,
email-validator/email_validator, grpcio/grpc, apache-airflow/airflow,
ansible-core/ansible, Jupyter package mappings, PyCryptodome mappings, and
msgpack-python/msgpack. The mapping is deliberately small and reviewed. Shared
namespace roots such as `google`, `azure`, `zope`, and `backports` are not
authoritative targets. Known competing distributions for the same import
namespace remain advisory on both sides of the collision; examples include
PyJWT/jwt, python-multipart/multipart, the OpenCV variants/cv2,
psycopg2-binary/psycopg2, and python-dotenv/dotenv.

Use `packaging` for PEP 440 versions, specifiers, and PEP 508 requirements.
Never compare versions lexically, translate Poetry operators approximately, or
evaluate markers using the scanner host environment.

## Evidence authority and graph context

All Python adapters are partial and may grant only `resolved_instances`.
Supported positive records are:

- one exact unmarked pin in the alert-selected pip requirements input;
- one unique supported Poetry 1.1 or 2.1 main lock record, classified as direct when a
  supported main declaration exists and transitive otherwise;
- one unique public-PyPI uv v1 lock record without selection ambiguity,
  classified as direct when a supported project declaration exists and
  transitive otherwise.

Unknown syntax, profiles, markers, groups, extras, sources, workspaces,
versions, or project selection withhold positive authority. Missing records
never prove absence or unaffected inventory.

Supported Poetry and uv locks also expose bounded recorded candidate graphs.
The collectors parse package nodes, supported dependency references, and main
project roots, then project immediate consumers and root-to-target paths for
matching target records. Paths retain selection-affecting markers,
optional state, groups, sources, forks, and unresolved or ambiguous references.
Each path also retains one bounded nullable explicit requirement per edge,
aligned with its edge kind and effective condition. Requirements are recorded
constraints only and do not prove an active environment. Package-node and
ancestor conditions propagate through the affected candidate path. A separate
complete unconditional, non-development, cycle-free path can retain positive
authority for the same unique supported record.
They are investigation context, not proof of the active environment, complete
consumer coverage, transitive vulnerable symbol execution, or package non-use.
Cycles and node, edge, depth, count, or serialized-size limits are explicit
partial evidence. If collection or projection truncation can affect the target
ancestry, consumers, or paths, the collector withholds `resolved_instances`
while retaining bounded context. Version `3.0` evidence serializes these paths,
and version `3.0` agent tasks carry the bounded path context and aggregate
truncation state.

Poetry edge resolution retains each declared version requirement and accepts
only requirements that `packaging` can parse directly as PEP 440 specifiers.
Poetry-specific operators are not approximated. Unsupported,
version-incompatible, or ambiguous inbound references remain authority
blockers. Conditional or optional alternatives do not negate a separate
complete unconditional, non-development, cycle-free path to the same unique
supported record; conditional-only target ancestry remains non-authoritative.

Selected pip requirements files may recursively read bounded repository-local
`-r` includes and `-c` constraints. Every include relationship is recorded as
non-authoritative provenance; constraints never introduce a dependency.
pip-compile `# via` annotations are also advisory provenance and never become
graph edges or dependency consumers. Unsafe, excluded, missing, unreadable, or
over-budget included files fail collection. Independent limits also bound
processed lines, matching declarations, exact-pin records, provenance records,
and aggregate serialized evidence/provenance output. Exhaustion fails
collection rather than returning truncated authoritative records. Include
cycles stop safely and remain explicit issues. Exact pins and their line
provenance are preserved even when an include withholds positive authority;
the records remain in version `3.0` evidence rather than being promoted to
agent-task graph paths.

## Runtime boundary

Collectors read bounded repository files only. They do not execute pip,
Poetry, uv, build backends, plugins, project code, or network requests. Python
evidence does not enter repository-reference absence proof. Inconclusive tasks
may use the shared task-bound structural analyzer with fixed Python import/load
operations.

Readable PEP 621, `setup.py`, `setup.cfg`, `Pipfile`, and `Pipfile.lock`
inputs may contribute typed declaration context without resolved-instance
authority. Inconclusive evidence may enter the single investigator with the
Python capability. It receives bounded list, read, search, and task-bound
structural-analysis tools. It can support positive-use findings, but search
absence cannot prove non-use and distribution names must not be assumed to
equal import names.
The analyzer derives a trusted project root from the selected manifest and
processes only pinned-engine Python source and stub paths under that root.
Other repository text remains available to bounded list, read, and search
tools. Files are analyzed in deterministic batches under shared aggregate
limits; incomplete batches remain explicit and cannot prove non-use.
Mixed-language or multi-project repositories do not weaken the requirement for
an exact authoritative Python target finding within the selected project.
Python capability findings cannot propose approval. Deterministic denial reconciliation
requires trusted dependency provenance plus an exact citation to a selected
attempt-local Python `static_import` or literal `dynamic_import` finding for an
authoritative task target. Search-only, parent-only, bound-call-only, advisory
target, no-match, incomplete, unavailable, plugin/configuration/CLI, and
import-name mismatch evidence remains `human_review` context. Valid real-model
findings may be challenged by the no-tool judge.

Literal `__import__` calls count only when the import level is omitted or
statically zero. Relative or indeterminate levels are not evidence of external
package usage.

Poetry projects may use `[project]` metadata and dependencies without a
`[tool.poetry]` table. Lock 1.1 uses `category = "main"` while lock 2.1 uses
main group membership; both remain positive-only and partial.

Authoritative format references:

- [PyPA name normalization](https://packaging.python.org/en/latest/specifications/name-normalization/)
- [PyPA dependency specifiers](https://packaging.python.org/en/latest/specifications/dependency-specifiers/)
- [PyPA version specifiers](https://packaging.python.org/en/latest/specifications/version-specifiers/)
- [pip requirements files](https://pip.pypa.io/en/stable/reference/requirements-file-format/)
- [Poetry dependency specification](https://python-poetry.org/docs/dependency-specification/)
- [uv project layout](https://docs.astral.sh/uv/concepts/projects/layout/)
