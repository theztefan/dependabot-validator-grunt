"""Deterministic positive-only uv dependency evidence."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version
from pydantic import ValidationError

from dependabot_validator_grunt.dependency_files import bounded_toml_object
from dependabot_validator_grunt.dependency_graph import (
    DependencyEdge,
    DependencyGraph,
    DependencyNode,
)
from dependabot_validator_grunt.models import (
    DependencyDeclaration,
    DependencyEvidence,
    DependencyInstance,
    Ecosystem,
    canonical_json,
)
from dependabot_validator_grunt.python_dependency_common import (
    OBJECT_ADAPTER,
    OBJECT_LIST_ADAPTER,
    GraphTruncation,
    bounded_graph_issues,
    combined_condition,
    condition_value,
    graph_target_context,
    has_unconditional_runtime_path,
    requirement_list_mentions,
    selected_project_paths,
)

_PYTHON_GRAPH_MAX_NODES = 10_000
_PYTHON_GRAPH_MAX_EDGES = 50_000
_PYTHON_GRAPH_MAX_TRUNCATED_NODE_NAMES = 10_000
_PYTHON_GRAPH_MAX_TRUNCATED_RELATIONSHIPS = 50_000


@dataclass(frozen=True)
class _UvPackageRecord:
    index: int
    instance_id: str
    raw: dict[str, object]
    raw_version: str | None
    parsed_version: Version | None
    package_name: str | None
    source_identity: str | None
    condition: str | None
    references: tuple[
        tuple[
            object,
            Literal["transitive", "optional", "development"],
            str | None,
            str | None,
        ],
        ...,
    ]
    inbound_dependencies: tuple[object, ...]


def collect_uv_declarations(
    pyproject: dict[str, object],
    *,
    package_name: str,
    manifest_path: str,
) -> tuple[tuple[DependencyDeclaration, ...], bool]:
    project = OBJECT_ADAPTER.validate_python(pyproject.get("project", {}))
    if not project:
        raise ValueError("selected uv pyproject.toml does not contain project metadata")
    try:
        raw_dependencies = OBJECT_LIST_ADAPTER.validate_python(project.get("dependencies", []))
    except ValidationError as error:
        raise ValueError("uv project dependencies must be an array") from error
    package_identity = canonicalize_name(package_name)
    declarations: list[DependencyDeclaration] = []
    unsupported_match = False
    for raw_dependency in raw_dependencies:
        if not isinstance(raw_dependency, str):
            raise ValueError("uv project dependency must be a string")
        try:
            requirement = Requirement(raw_dependency)
        except InvalidRequirement as error:
            raise ValueError("uv project dependency is malformed") from error
        if canonicalize_name(requirement.name) != package_identity:
            continue
        supported = (
            requirement.marker is None and requirement.url is None and not requirement.extras
        )
        unsupported_match = unsupported_match or not supported
        declarations.append(
            DependencyDeclaration(
                manifest_path=manifest_path,
                name=requirement.name,
                spec=str(requirement.specifier),
                relationship="direct",
                marker=str(requirement.marker) if requirement.marker is not None else None,
                source_kind="url" if requirement.url is not None else "registry",
                source_locator=requirement.url,
            )
        )
    return tuple(declarations), unsupported_match


def _uv_unsupported_sections_mention_target(
    pyproject: dict[str, object],
    *,
    package_name: str,
) -> bool:
    package_identity = canonicalize_name(package_name)
    project = OBJECT_ADAPTER.validate_python(pyproject.get("project", {}))
    optional_dependencies = OBJECT_ADAPTER.validate_python(project.get("optional-dependencies", {}))
    for group_name, dependencies in optional_dependencies.items():
        if requirement_list_mentions(
            dependencies,
            package_identity=package_identity,
            context=f"project optional dependency group {group_name}",
        ):
            return True

    dependency_groups = OBJECT_ADAPTER.validate_python(pyproject.get("dependency-groups", {}))
    for group_name, dependencies in dependency_groups.items():
        if requirement_list_mentions(
            dependencies,
            package_identity=package_identity,
            context=f"uv dependency group {group_name}",
        ):
            return True

    tool = OBJECT_ADAPTER.validate_python(pyproject.get("tool", {}))
    uv = OBJECT_ADAPTER.validate_python(tool.get("uv", {}))
    return requirement_list_mentions(
        uv.get("dev-dependencies", []),
        package_identity=package_identity,
        context="uv legacy dev dependencies",
    )


def _uv_lock_has_conditional_inbound_reference(
    package_records: tuple[_UvPackageRecord, ...],
    *,
    package_identity: str,
) -> bool:
    conditional_fields = (
        "optional-dependencies",
        "dev-dependencies",
        "dependency-groups",
    )
    for record in package_records:
        for raw_dependency in record.inbound_dependencies:
            if not isinstance(raw_dependency, dict):
                continue
            dependency = OBJECT_ADAPTER.validate_python(raw_dependency)
            name = dependency.get("name")
            if (
                isinstance(name, str)
                and canonicalize_name(name) == package_identity
                and set(dependency) - {"name", "version", "source"}
            ):
                return True
        for field in conditional_fields:
            if record.raw.get(field) is not None and _value_mentions_package(
                record.raw[field],
                package_identity=package_identity,
            ):
                return True
    return False


def _uv_source_identity(value: object) -> str | None:
    if value is None:
        return None
    try:
        source = OBJECT_ADAPTER.validate_python(value)
    except ValidationError:
        return None
    return canonical_json(source)


def _uv_versions_match(candidate: str | None, reference: str) -> bool:
    if candidate is None:
        return False
    try:
        return Version(candidate) == Version(reference)
    except InvalidVersion:
        return False


def _uv_package_condition(package: dict[str, object]) -> str | None:
    conditions: list[str] = []
    source = package.get("source")
    source_identity = _uv_source_identity(source)
    public_source = canonical_json({"registry": "https://pypi.org/simple"})
    if source is not None and source_identity != public_source:
        conditions.append(condition_value("source", source))
    for field in (
        "resolution-markers",
        "resolution-marker",
        "marker",
        "fork-markers",
        "conflicts",
        "optional",
        "groups",
        "group",
    ):
        value = package.get(field)
        if value is not None:
            conditions.append(condition_value(field, value))
    return combined_condition(*conditions)


def _uv_reference_condition(
    dependency: dict[str, object],
    *,
    inherited: str | None,
) -> str | None:
    conditions: list[str] = []
    for field, value in sorted(dependency.items()):
        if field in {"name", "version", "source"}:
            continue
        conditions.append(condition_value(field, value))
    return combined_condition(inherited, *conditions)


def _uv_dependency_sections(
    package: dict[str, object],
) -> tuple[
    tuple[
        object,
        Literal["transitive", "optional", "development"],
        str | None,
        str | None,
    ],
    ...,
]:
    requirements_by_name = _uv_explicit_requirements(package)
    references: list[
        tuple[
            object,
            Literal["transitive", "optional", "development"],
            str | None,
            str | None,
        ]
    ] = []
    try:
        dependencies = OBJECT_LIST_ADAPTER.validate_python(package.get("dependencies", []))
    except ValidationError as error:
        raise ValueError("uv package dependencies must be an array") from error
    references.extend(
        (
            dependency,
            "transitive",
            None,
            _uv_reference_requirement(dependency, requirements_by_name=requirements_by_name),
        )
        for dependency in dependencies
    )
    for field, kind, condition_name in (
        ("optional-dependencies", "optional", "extra"),
        ("dev-dependencies", "development", "development-group"),
        ("dependency-groups", "development", "dependency-group"),
    ):
        raw_section = package.get(field)
        if raw_section is None:
            continue
        section: dict[str, object]
        if isinstance(raw_section, list):
            section = {"default": cast(list[object], raw_section)}
        else:
            try:
                section = OBJECT_ADAPTER.validate_python(raw_section)
            except ValidationError as error:
                raise ValueError(f"uv package {field} must be a table or array") from error
        for group, raw_dependencies in section.items():
            try:
                grouped_dependencies = OBJECT_LIST_ADAPTER.validate_python(raw_dependencies)
            except ValidationError as error:
                raise ValueError(f"uv package {field} entries must be arrays") from error
            references.extend(
                (
                    dependency,
                    cast(
                        Literal["transitive", "optional", "development"],
                        kind,
                    ),
                    f"{condition_name}={group}",
                    _uv_reference_requirement(
                        dependency,
                        requirements_by_name=requirements_by_name,
                    ),
                )
                for dependency in grouped_dependencies
            )
    return tuple(references)


def _parse_uv_packages(
    lock: dict[str, object],
    *,
    lock_manifest: str,
) -> tuple[tuple[_UvPackageRecord, ...], set[str]]:
    try:
        raw_packages = OBJECT_LIST_ADAPTER.validate_python(lock.get("package"))
    except ValidationError as error:
        raise ValueError("uv lock packages must be an array") from error
    records: list[_UvPackageRecord] = []
    issues: set[str] = set()
    for index, raw_package in enumerate(raw_packages):
        try:
            package = OBJECT_ADAPTER.validate_python(raw_package)
        except ValidationError as error:
            raise ValueError("uv lock package is malformed") from error
        try:
            inbound_dependencies = tuple(
                OBJECT_LIST_ADAPTER.validate_python(package.get("dependencies", []))
            )
        except ValidationError:
            inbound_dependencies = ()
        raw_name = package.get("name")
        package_name = (
            canonicalize_name(raw_name) if isinstance(raw_name, str) and raw_name else None
        )
        if package_name is None:
            issues.add(f"uv package[{index}] has no supported name")
        raw_version_value = package.get("version")
        raw_version = raw_version_value if isinstance(raw_version_value, str) else None
        parsed_version = None
        if package_name is not None and raw_version is not None:
            try:
                parsed_version = Version(raw_version)
            except InvalidVersion:
                issues.add(f"uv package[{index}] has an invalid PEP 440 version")
        records.append(
            _UvPackageRecord(
                index=index,
                instance_id=f"{lock_manifest}:package[{index}]",
                raw=package,
                raw_version=raw_version,
                parsed_version=parsed_version,
                package_name=package_name,
                source_identity=(
                    _uv_source_identity(package.get("source")) if package_name is not None else None
                ),
                condition=(_uv_package_condition(package) if package_name is not None else None),
                references=(_uv_dependency_sections(package) if package_name is not None else ()),
                inbound_dependencies=inbound_dependencies,
            )
        )
    return tuple(records), issues


def _uv_explicit_requirements(package: dict[str, object]) -> dict[str, str]:
    try:
        metadata = OBJECT_ADAPTER.validate_python(package.get("metadata", {}))
        requires_dist = OBJECT_LIST_ADAPTER.validate_python(metadata.get("requires-dist", []))
    except ValidationError:
        return {}
    requirements: dict[str, set[str]] = {}
    for raw_requirement in requires_dist:
        if not isinstance(raw_requirement, dict):
            continue
        requirement = OBJECT_ADAPTER.validate_python(raw_requirement)
        raw_name = requirement.get("name")
        specifier = requirement.get("specifier")
        if (
            not isinstance(raw_name, str)
            or not raw_name
            or not isinstance(specifier, str)
            or not specifier
        ):
            continue
        requirements.setdefault(canonicalize_name(raw_name), set()).add(specifier)
    return {
        package_name: next(iter(specifiers))
        for package_name, specifiers in requirements.items()
        if len(specifiers) == 1
    }


def _uv_reference_requirement(
    raw_dependency: object,
    *,
    requirements_by_name: dict[str, str],
) -> str | None:
    if not isinstance(raw_dependency, dict):
        return None
    dependency = OBJECT_ADAPTER.validate_python(raw_dependency)
    raw_name = dependency.get("name")
    if not isinstance(raw_name, str) or not raw_name:
        return None
    return requirements_by_name.get(canonicalize_name(raw_name))


def _uv_root_dependencies(
    pyproject: dict[str, object],
    *,
    issues: set[str],
) -> tuple[tuple[dict[str, object], str | None, str | None], ...]:
    project = OBJECT_ADAPTER.validate_python(pyproject.get("project", {}))
    try:
        raw_dependencies = OBJECT_LIST_ADAPTER.validate_python(project.get("dependencies", []))
    except ValidationError as error:
        raise ValueError("uv project dependencies must be an array") from error
    dependencies: list[tuple[dict[str, object], str | None, str | None]] = []
    for raw_dependency in raw_dependencies:
        if not isinstance(raw_dependency, str):
            raise ValueError("uv project dependency must be a string")
        try:
            requirement = Requirement(raw_dependency)
        except InvalidRequirement as error:
            raise ValueError("uv project dependency is malformed") from error
        conditions: list[str] = []
        if requirement.marker is not None:
            conditions.append(f"marker={requirement.marker}")
        if requirement.extras:
            conditions.append(f"extras={','.join(sorted(requirement.extras))}")
        if requirement.url is not None:
            conditions.append(f"url={requirement.url}")
        identity: dict[str, object] = {"name": canonicalize_name(requirement.name)}
        specifiers = tuple(requirement.specifier)
        if (
            len(specifiers) == 1
            and specifiers[0].operator == "=="
            and "*" not in specifiers[0].version
        ):
            try:
                exact_version = str(Version(specifiers[0].version))
            except InvalidVersion:
                exact_version = None
            if exact_version is not None:
                identity["version"] = exact_version
        if requirement.url is not None:
            identity["source"] = {"url": requirement.url}
        edge_requirement = str(requirement.specifier) or None
        dependencies.append((identity, combined_condition(*conditions), edge_requirement))
    if project.get("optional-dependencies"):
        issues.add("uv project optional dependencies are not main graph roots")
    if pyproject.get("dependency-groups"):
        issues.add("uv dependency groups are not main graph roots")
    tool = OBJECT_ADAPTER.validate_python(pyproject.get("tool", {}))
    uv = OBJECT_ADAPTER.validate_python(tool.get("uv", {}))
    if uv.get("dev-dependencies"):
        issues.add("uv development dependencies are not main graph roots")
    return tuple(dependencies)


def _build_uv_graph(
    package_records: tuple[_UvPackageRecord, ...],
    pyproject: dict[str, object],
    *,
    lock_version: str,
    package_issues: set[str],
) -> tuple[DependencyGraph, GraphTruncation]:
    issues = set(package_issues)
    records: list[_UvPackageRecord] = []
    nodes: list[DependencyNode] = []
    by_name: dict[str, list[_UvPackageRecord]] = {}
    truncated = False
    truncated_node_names: set[str] = set()
    truncated_relationships: set[tuple[str, str]] = set()
    truncation_summary_incomplete = False

    def record_truncated_node(package_name: str) -> None:
        nonlocal truncation_summary_incomplete
        if package_name in truncated_node_names:
            return
        if len(truncated_node_names) >= _PYTHON_GRAPH_MAX_TRUNCATED_NODE_NAMES:
            truncation_summary_incomplete = True
            return
        truncated_node_names.add(package_name)

    def record_truncated_relationship(consumer_name: str, dependency_name: str) -> None:
        nonlocal truncation_summary_incomplete
        relationship = (consumer_name, dependency_name)
        if relationship in truncated_relationships:
            return
        if len(truncated_relationships) >= _PYTHON_GRAPH_MAX_TRUNCATED_RELATIONSHIPS:
            truncation_summary_incomplete = True
            return
        truncated_relationships.add(relationship)

    def record_truncated_package(record: _UvPackageRecord) -> None:
        nonlocal truncation_summary_incomplete
        if record.package_name is None:
            return
        record_truncated_node(record.package_name)
        for raw_dependency, _kind, _condition, _requirement in record.references:
            if not isinstance(raw_dependency, dict):
                truncation_summary_incomplete = True
                continue
            dependency = OBJECT_ADAPTER.validate_python(raw_dependency)
            raw_dependency_name = dependency.get("name")
            if not isinstance(raw_dependency_name, str) or not raw_dependency_name:
                truncation_summary_incomplete = True
                continue
            record_truncated_relationship(
                record.package_name,
                canonicalize_name(raw_dependency_name),
            )

    for record in package_records:
        if record.package_name is None:
            continue
        if len(records) >= _PYTHON_GRAPH_MAX_NODES:
            truncated = True
            record_truncated_package(record)
            continue
        node = DependencyNode(
            instance_id=record.instance_id,
            package_name=record.package_name,
            version=record.raw_version,
            comparable=record.parsed_version is not None,
        )
        records.append(record)
        nodes.append(node)
        by_name.setdefault(record.package_name, []).append(record)
        if record.condition is not None:
            issues.add(f"conditional uv package node: {record.instance_id}")
    if truncated:
        issues.add("uv dependency graph node limit was reached")

    edges: list[DependencyEdge] = []
    edge_keys: set[tuple[str, str | None, str, str, str, str | None, str | None]] = set()

    def append_reference(
        *,
        consumer_id: str,
        consumer_name: str,
        raw_dependency: object,
        kind: Literal["runtime", "transitive", "optional", "development"],
        inherited_condition: str | None,
        requirement: str | None,
    ) -> None:
        nonlocal truncated
        if not isinstance(raw_dependency, dict):
            issues.add(f"unsupported uv dependency reference from {consumer_id}")
            return
        dependency = OBJECT_ADAPTER.validate_python(raw_dependency)
        raw_name = dependency.get("name")
        if not isinstance(raw_name, str) or not raw_name:
            issues.add(f"uv dependency reference from {consumer_id} has no supported name")
            return
        actual_name = canonicalize_name(raw_name)
        candidates = list(by_name.get(actual_name, ()))
        raw_version = dependency.get("version")
        if raw_version is not None:
            if not isinstance(raw_version, str):
                candidates = []
                issues.add(
                    f"uv dependency reference from {consumer_id} has an invalid version identity"
                )
            else:
                candidates = [
                    candidate
                    for candidate in candidates
                    if _uv_versions_match(candidate.raw_version, raw_version)
                ]
        if "source" in dependency:
            source_identity = _uv_source_identity(dependency.get("source"))
            if source_identity is None:
                candidates = []
                issues.add(
                    f"uv dependency reference from {consumer_id} has an invalid source identity"
                )
            else:
                candidates = [
                    candidate
                    for candidate in candidates
                    if candidate.source_identity == source_identity
                ]
        target_id = candidates[0].instance_id if len(candidates) == 1 else None
        if not candidates:
            issues.add(f"unresolved uv dependency reference: {consumer_id} -> {actual_name}")
        elif len(candidates) > 1:
            issues.add(f"ambiguous uv dependency reference: {consumer_id} -> {actual_name}")
        target_condition = candidates[0].condition if len(candidates) == 1 else None
        condition = combined_condition(
            _uv_reference_condition(dependency, inherited=inherited_condition),
            target_condition,
        )
        if condition is not None:
            issues.add(f"conditional uv dependency edge: {consumer_id} -> {actual_name}")
        edge_key = (
            consumer_id,
            target_id,
            raw_name,
            actual_name,
            kind,
            condition,
            requirement,
        )
        if edge_key in edge_keys:
            return
        if len(edges) >= _PYTHON_GRAPH_MAX_EDGES:
            truncated = True
            record_truncated_relationship(consumer_name, actual_name)
            return
        edge_keys.add(edge_key)
        edges.append(
            DependencyEdge(
                consumer_id=consumer_id,
                target_id=target_id,
                declared_name=raw_name,
                actual_name=actual_name,
                kind=kind,
                condition=condition,
                requirement=requirement,
            )
        )

    for record in records:
        if record.package_name is None:
            continue
        for raw_dependency, kind, condition, requirement in record.references:
            append_reference(
                consumer_id=record.instance_id,
                consumer_name=record.package_name,
                raw_dependency=raw_dependency,
                kind=kind,
                inherited_condition=combined_condition(record.condition, condition),
                requirement=requirement,
            )
    for dependency, condition, requirement in _uv_root_dependencies(pyproject, issues=issues):
        append_reference(
            consumer_id="importer:.",
            consumer_name="<project>",
            raw_dependency=dependency,
            kind="runtime",
            inherited_condition=condition,
            requirement=requirement,
        )
    if truncated:
        issues.add("uv dependency graph edge or node limit was reached")
    return (
        DependencyGraph(
            lockfile_version=lock_version,
            nodes=tuple(nodes),
            edges=tuple(edges),
            issues=bounded_graph_issues(issues),
        ),
        GraphTruncation(
            node_names=tuple(sorted(truncated_node_names)),
            relationships=tuple(sorted(truncated_relationships)),
            incomplete=truncation_summary_incomplete,
        ),
    )


def _value_mentions_package(value: object, *, package_identity: str) -> bool:
    if isinstance(value, str):
        try:
            return canonicalize_name(Requirement(value).name) == package_identity
        except InvalidRequirement:
            return canonicalize_name(value) == package_identity
    if isinstance(value, list):
        items = cast(list[object], value)
        return any(
            _value_mentions_package(item, package_identity=package_identity) for item in items
        )
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        name = mapping.get("name")
        if isinstance(name, str) and canonicalize_name(name) == package_identity:
            return True
        return any(
            _value_mentions_package(item, package_identity=package_identity)
            for item in mapping.values()
        )
    return False


def collect_uv_evidence(
    repository: Path,
    ecosystem: Ecosystem,
    package_name: str,
    manifest_path: str,
    *,
    max_dependency_file_bytes: int,
    excluded_paths: tuple[str, ...],
    max_dependency_paths: int,
    max_dependency_path_depth: int,
    max_dependency_path_bytes: int,
) -> DependencyEvidence:
    pyproject_path, lock_path, prefix = selected_project_paths(
        repository,
        manifest_path,
        lock_name="uv.lock",
    )
    pyproject_manifest = f"{prefix}pyproject.toml"
    lock_manifest = f"{prefix}uv.lock"
    if pyproject_manifest in excluded_paths or lock_manifest in excluded_paths:
        raise ValueError("selected uv dependency file was excluded from the snapshot")
    if not pyproject_path.is_file() or not lock_path.is_file():
        raise ValueError("selected uv project requires adjacent pyproject.toml and uv.lock")
    pyproject = bounded_toml_object(pyproject_path, max_dependency_file_bytes)
    lock = bounded_toml_object(lock_path, max_dependency_file_bytes)
    lock_version = lock.get("version")
    if not isinstance(lock_version, int) or isinstance(lock_version, bool) or lock_version != 1:
        raise ValueError("only uv lock major version 1 is supported")
    revision = lock.get("revision")
    understood_revision = revision is None or (
        isinstance(revision, int) and not isinstance(revision, bool) and 0 <= revision <= 3
    )
    declarations, unsupported_declaration = collect_uv_declarations(
        pyproject,
        package_name=package_name,
        manifest_path=pyproject_manifest,
    )
    issues = {"uv support is positive-evidence only"}
    tool = OBJECT_ADAPTER.validate_python(pyproject.get("tool", {}))
    uv = OBJECT_ADAPTER.validate_python(tool.get("uv", {}))
    workspace = uv.get("workspace")
    sources = OBJECT_ADAPTER.validate_python(uv.get("sources", {}))
    target_source = next(
        (
            value
            for name, value in sources.items()
            if canonicalize_name(name) == canonicalize_name(package_name)
        ),
        None,
    )
    custom_indexes = uv.get("index")
    authority_blocked = False
    if workspace is not None:
        authority_blocked = True
        issues.add("uv workspaces are unsupported")
    if target_source is not None or custom_indexes is not None:
        authority_blocked = True
        issues.add("uv source overrides and custom indexes prevent public PyPI authority")
    if not understood_revision:
        authority_blocked = True
        issues.add("uv lock revision is newer than the understood revision")
    if unsupported_declaration:
        authority_blocked = True
        issues.add("matching uv declaration is not an unmarked direct registry dependency")
    unsupported_section_match = _uv_unsupported_sections_mention_target(
        pyproject,
        package_name=package_name,
    )
    if unsupported_section_match:
        authority_blocked = True
        issues.add("matching uv dependency appears in an unsupported dependency section")
    if len(declarations) > 1:
        authority_blocked = True
        issues.add("multiple matching direct main uv declarations are ambiguous")

    package_records, package_issues = _parse_uv_packages(
        lock,
        lock_manifest=lock_manifest,
    )
    package_identity = canonicalize_name(package_name)
    conditional_inbound_reference = _uv_lock_has_conditional_inbound_reference(
        package_records,
        package_identity=package_identity,
    )
    if conditional_inbound_reference:
        issues.add("matching uv lock record has a conditional or optional inbound edge")
    matches: list[tuple[int, Version]] = []
    matching_record_count = 0
    unsupported_lock_match = False
    for record in package_records:
        if record.package_name != package_identity:
            continue
        matching_record_count += 1
        raw_version = record.raw.get("version")
        public_source = canonical_json({"registry": "https://pypi.org/simple"})
        if (
            not isinstance(raw_version, str)
            or record.source_identity != public_source
            or record.condition is not None
        ):
            unsupported_lock_match = True
            issues.add("matching uv lock record has an unsupported profile or source")
            continue
        if record.parsed_version is None:
            unsupported_lock_match = True
            issues.add("matching uv lock record has an invalid PEP 440 version")
        else:
            matches.append((record.index, record.parsed_version))

    rendered_lock_version = f"1.{revision}" if revision is not None else "1"
    graph, graph_truncation = _build_uv_graph(
        package_records,
        pyproject,
        lock_version=rendered_lock_version,
        package_issues=package_issues,
    )
    target_ids = {node.instance_id for node in graph.nodes if node.package_name == package_identity}
    consumers, paths, paths_truncated, conditional_ancestry = graph_target_context(
        graph,
        target_ids=target_ids,
        candidate_name=package_identity,
        graph_truncation=graph_truncation,
        max_dependency_paths=max_dependency_paths,
        max_dependency_path_depth=max_dependency_path_depth,
        max_dependency_path_bytes=max_dependency_path_bytes,
    )
    issues.update(graph.issues)
    unconditional_runtime_path = has_unconditional_runtime_path(paths)
    if (conditional_inbound_reference or conditional_ancestry) and not unconditional_runtime_path:
        authority_blocked = True
        issues.add("matching uv target has conditional dependency ancestry")
    elif conditional_inbound_reference or conditional_ancestry:
        issues.add("matching uv target also has conditional dependency alternatives")
    if paths_truncated:
        authority_blocked = True
        issues.add("matching uv target graph context was truncated; positive authority withheld")

    instances: tuple[DependencyInstance, ...] = ()
    if matching_record_count != 1 or len(matches) != 1 or unsupported_lock_match:
        if matching_record_count:
            issues.add("matching uv lock records are ambiguous")
    elif not authority_blocked:
        index, version = matches[0]
        instances = (
            DependencyInstance(
                path=f"{lock_manifest}:package[{index}]",
                version=str(version),
                relationship="direct" if declarations else "transitive",
                source_kind="registry",
                source_locator="https://pypi.org/simple",
            ),
        )

    return DependencyEvidence(
        ecosystem=ecosystem,
        package_manager="uv",
        version_scheme="pep440",
        lockfile_version=rendered_lock_version,
        lockfile_path=lock_manifest,
        proof_capabilities=("resolved_instances",) if instances else (),
        package_name=package_name,
        instances=instances,
        manifest_paths=(pyproject_manifest, lock_manifest),
        completeness="partial",
        declarations=declarations,
        dependency_consumers=consumers,
        dependency_paths=paths,
        dependency_paths_truncated=paths_truncated,
        issues=tuple(sorted(issues)),
    )
