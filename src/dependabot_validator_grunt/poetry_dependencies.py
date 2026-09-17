"""Deterministic positive-only Poetry dependency evidence."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import SpecifierSet
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
)
from dependabot_validator_grunt.python_dependency_common import (
    OBJECT_ADAPTER,
    OBJECT_LIST_ADAPTER,
    STRING_LIST_ADAPTER,
    GraphTruncation,
    bounded_graph_issues,
    combined_condition,
    condition_value,
    graph_target_context,
    has_unconditional_runtime_path,
    pep440_specifier,
    requirement_list_mentions,
    selected_project_paths,
)

_PYTHON_GRAPH_MAX_NODES = 10_000
_PYTHON_GRAPH_MAX_EDGES = 50_000
_PYTHON_GRAPH_MAX_TRUNCATED_NODE_NAMES = 10_000
_PYTHON_GRAPH_MAX_TRUNCATED_RELATIONSHIPS = 50_000
SourceKind = Literal["registry", "url", "vcs", "path", "workspace", "unknown"]


@dataclass(frozen=True)
class _PoetryPackageRecord:
    index: int
    node: DependencyNode
    raw: dict[str, object]
    parsed_version: Version | None
    condition: str | None


@dataclass(frozen=True)
class _PoetryDependencyVariant:
    kind: Literal["runtime", "transitive", "optional"]
    requirement: str | None
    specifier: SpecifierSet | None
    condition: str | None
    supported: bool


def collect_poetry_declarations(
    pyproject: dict[str, object],
    *,
    package_name: str,
    manifest_path: str,
) -> tuple[tuple[DependencyDeclaration, ...], bool]:
    package_identity = canonicalize_name(package_name)
    declarations: list[DependencyDeclaration] = []
    unsupported_match = False
    project = OBJECT_ADAPTER.validate_python(pyproject.get("project", {}))
    try:
        raw_project_dependencies = OBJECT_LIST_ADAPTER.validate_python(
            project.get("dependencies", [])
        )
    except ValidationError as error:
        raise ValueError("Poetry project dependencies must be an array") from error
    for raw_dependency in raw_project_dependencies:
        if not isinstance(raw_dependency, str):
            raise ValueError("Poetry project dependency must be a string")
        try:
            requirement = Requirement(raw_dependency)
        except InvalidRequirement as error:
            raise ValueError("Poetry project dependency is malformed") from error
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

    tool = OBJECT_ADAPTER.validate_python(pyproject.get("tool", {}))
    poetry = OBJECT_ADAPTER.validate_python(tool.get("poetry", {}))
    poetry_dependencies = OBJECT_ADAPTER.validate_python(poetry.get("dependencies", {}))
    for name, raw_spec in poetry_dependencies.items():
        if name == "python" or canonicalize_name(name) != package_identity:
            continue
        supported = isinstance(raw_spec, str) and pep440_specifier(raw_spec) is not None
        spec = raw_spec if isinstance(raw_spec, str) else ""
        marker = None
        source_kind: SourceKind = "registry"
        source_locator = None
        if isinstance(raw_spec, dict):
            dependency = OBJECT_ADAPTER.validate_python(raw_spec)
            raw_version = dependency.get("version")
            spec = raw_version if isinstance(raw_version, str) else ""
            raw_marker = dependency.get("markers")
            marker = raw_marker if isinstance(raw_marker, str) else None
            source_keys = ("source", "git", "url", "path")
            selected_sources = [key for key in source_keys if key in dependency]
            allowed_keys = {"version"}
            supported = (
                isinstance(raw_version, str)
                and pep440_specifier(raw_version) is not None
                and marker is None
                and not selected_sources
                and set(dependency) <= allowed_keys
            )
            if selected_sources:
                key = selected_sources[0]
                source_kind = cast(
                    SourceKind,
                    {
                        "git": "vcs",
                        "url": "url",
                        "path": "path",
                        "source": "unknown",
                    }[key],
                )
                source_locator = str(dependency[key])
        unsupported_match = unsupported_match or not supported
        declarations.append(
            DependencyDeclaration(
                manifest_path=manifest_path,
                name=name,
                spec=spec,
                relationship="direct",
                marker=marker,
                source_kind=source_kind,
                source_locator=source_locator,
            )
        )
    return tuple(declarations), unsupported_match


def _dependency_mapping_mentions(
    value: object,
    *,
    package_identity: str,
    context: str,
) -> bool:
    try:
        dependencies = OBJECT_ADAPTER.validate_python(value)
    except ValidationError as error:
        raise ValueError(f"{context} must be a table") from error
    return any(canonicalize_name(name) == package_identity for name in dependencies)


def _poetry_unsupported_sections_mention_target(
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

    tool = OBJECT_ADAPTER.validate_python(pyproject.get("tool", {}))
    poetry = OBJECT_ADAPTER.validate_python(tool.get("poetry", {}))
    if _dependency_mapping_mentions(
        poetry.get("dev-dependencies", {}),
        package_identity=package_identity,
        context="Poetry dev dependencies",
    ):
        return True
    groups = OBJECT_ADAPTER.validate_python(poetry.get("group", {}))
    for group_name, raw_group in groups.items():
        group = OBJECT_ADAPTER.validate_python(raw_group)
        if _dependency_mapping_mentions(
            group.get("dependencies", {}),
            package_identity=package_identity,
            context=f"Poetry dependency group {group_name}",
        ):
            return True
    extras = OBJECT_ADAPTER.validate_python(poetry.get("extras", {}))
    for extra_name, raw_dependencies in extras.items():
        try:
            dependencies = OBJECT_LIST_ADAPTER.validate_python(raw_dependencies)
        except ValidationError as error:
            raise ValueError(f"Poetry extra {extra_name} must be an array") from error
        for dependency in dependencies:
            if not isinstance(dependency, str):
                raise ValueError(f"Poetry extra {extra_name} entries must be strings")
            if canonicalize_name(dependency) == package_identity:
                return True
    return False


def _poetry_package_condition(
    package: dict[str, object],
    *,
    lock_version: str,
) -> str | None:
    conditions: list[str] = []
    for field in ("markers", "marker"):
        value = package.get(field)
        if value is not None:
            conditions.append(condition_value(field, value))
    optional = package.get("optional")
    if optional is not None and optional is not False:
        conditions.append(condition_value("optional", optional))
    if lock_version == "2.1":
        groups = package.get("groups")
        if groups != ["main"]:
            conditions.append(condition_value("groups", groups))
    else:
        category = package.get("category")
        if category != "main":
            conditions.append(condition_value("category", category))
    source = package.get("source")
    if source is not None:
        conditions.append(condition_value("source", source))
    return combined_condition(*conditions)


def _parse_poetry_packages(
    lock: dict[str, object],
    *,
    lock_version: str,
    lock_manifest: str,
) -> tuple[tuple[_PoetryPackageRecord, ...], set[str]]:
    try:
        raw_packages = OBJECT_LIST_ADAPTER.validate_python(lock.get("package"))
    except ValidationError as error:
        raise ValueError("Poetry lock packages must be an array") from error
    records: list[_PoetryPackageRecord] = []
    issues: set[str] = set()
    for index, raw_package in enumerate(raw_packages):
        try:
            package = OBJECT_ADAPTER.validate_python(raw_package)
        except ValidationError as error:
            raise ValueError("Poetry lock package is malformed") from error
        raw_name = package.get("name")
        if not isinstance(raw_name, str) or not raw_name:
            issues.add(f"Poetry package[{index}] has no supported name")
            continue
        raw_version = package.get("version")
        version = raw_version if isinstance(raw_version, str) else None
        parsed_version = None
        if version is not None:
            try:
                parsed_version = Version(version)
            except InvalidVersion:
                issues.add(f"Poetry package[{index}] has an invalid PEP 440 version")
        records.append(
            _PoetryPackageRecord(
                index=index,
                node=DependencyNode(
                    instance_id=f"{lock_manifest}:package[{index}]",
                    package_name=canonicalize_name(raw_name),
                    version=version,
                    comparable=parsed_version is not None,
                ),
                raw=package,
                parsed_version=parsed_version,
                condition=_poetry_package_condition(package, lock_version=lock_version),
            )
        )
    return tuple(records), issues


def _poetry_dependency_variants(
    raw_dependency: object,
) -> tuple[_PoetryDependencyVariant, ...]:
    if isinstance(raw_dependency, list):
        variants: list[_PoetryDependencyVariant] = []
        for item in cast(list[object], raw_dependency):
            variants.extend(_poetry_dependency_variants(item))
        if variants:
            return tuple(variants)
        return (
            _PoetryDependencyVariant(
                kind="transitive",
                requirement=None,
                specifier=None,
                condition=None,
                supported=False,
            ),
        )
    if isinstance(raw_dependency, str):
        specifier = pep440_specifier(raw_dependency)
        return (
            _PoetryDependencyVariant(
                kind="transitive",
                requirement=raw_dependency,
                specifier=specifier,
                condition=None,
                supported=specifier is not None,
            ),
        )
    if not isinstance(raw_dependency, dict):
        return (
            _PoetryDependencyVariant(
                kind="transitive",
                requirement=None,
                specifier=None,
                condition=None,
                supported=False,
            ),
        )
    dependency = OBJECT_ADAPTER.validate_python(raw_dependency)
    conditions: list[str] = []
    for field in ("markers", "marker", "python", "platform"):
        value = dependency.get(field)
        if value is not None:
            conditions.append(condition_value(field, value))
    optional = dependency.get("optional")
    if optional is not None and optional is not False:
        conditions.append(condition_value("optional", optional))
    extras = dependency.get("extras")
    if extras:
        conditions.append(condition_value("extras", extras))
    for field in ("source", "git", "url", "path"):
        value = dependency.get(field)
        if value is not None:
            conditions.append(condition_value(field, value))
    known_fields = {
        "version",
        "markers",
        "marker",
        "python",
        "platform",
        "optional",
        "extras",
        "source",
        "git",
        "url",
        "path",
    }
    unknown_fields = sorted(set(dependency) - known_fields)
    if unknown_fields:
        conditions.append(f"fields={','.join(unknown_fields)}")
    raw_version = dependency.get("version")
    requirement = raw_version if isinstance(raw_version, str) else None
    specifier = pep440_specifier(requirement) if requirement is not None else None
    marker_fields_valid = all(
        field not in dependency or isinstance(dependency[field], str)
        for field in ("markers", "marker", "python", "platform")
    )
    optional_valid = "optional" not in dependency or isinstance(optional, bool)
    extras_valid = True
    if "extras" in dependency:
        try:
            STRING_LIST_ADAPTER.validate_python(extras)
        except ValidationError:
            extras_valid = False
    supported = (
        specifier is not None
        and marker_fields_valid
        and optional_valid
        and extras_valid
        and not any(field in dependency for field in ("source", "git", "url", "path"))
        and not unknown_fields
    )
    return (
        _PoetryDependencyVariant(
            kind="optional" if optional is True else "transitive",
            requirement=requirement,
            specifier=specifier,
            condition=combined_condition(*conditions),
            supported=supported,
        ),
    )


def _poetry_root_dependencies(
    pyproject: dict[str, object],
    *,
    issues: set[str],
) -> tuple[tuple[str, _PoetryDependencyVariant], ...]:
    dependencies: list[tuple[str, _PoetryDependencyVariant]] = []
    project = OBJECT_ADAPTER.validate_python(pyproject.get("project", {}))
    try:
        project_dependencies = OBJECT_LIST_ADAPTER.validate_python(project.get("dependencies", []))
    except ValidationError as error:
        raise ValueError("Poetry project dependencies must be an array") from error
    for raw_dependency in project_dependencies:
        if not isinstance(raw_dependency, str):
            raise ValueError("Poetry project dependency must be a string")
        try:
            requirement = Requirement(raw_dependency)
        except InvalidRequirement as error:
            raise ValueError("Poetry project dependency is malformed") from error
        conditions: list[str] = []
        if requirement.marker is not None:
            conditions.append(f"marker={requirement.marker}")
        if requirement.extras:
            conditions.append(f"extras={','.join(sorted(requirement.extras))}")
        if requirement.url is not None:
            conditions.append(f"url={requirement.url}")
        specifier = pep440_specifier(str(requirement.specifier), allow_empty=True)
        edge_requirement = str(requirement.specifier) or None
        dependencies.append(
            (
                canonicalize_name(requirement.name),
                _PoetryDependencyVariant(
                    kind="runtime",
                    requirement=edge_requirement,
                    specifier=specifier,
                    condition=combined_condition(*conditions),
                    supported=specifier is not None and requirement.url is None,
                ),
            )
        )

    tool = OBJECT_ADAPTER.validate_python(pyproject.get("tool", {}))
    poetry = OBJECT_ADAPTER.validate_python(tool.get("poetry", {}))
    poetry_dependencies = OBJECT_ADAPTER.validate_python(poetry.get("dependencies", {}))
    for name, raw_dependency in poetry_dependencies.items():
        if name == "python":
            continue
        variants = _poetry_dependency_variants(raw_dependency)
        for variant in variants:
            dependencies.append(
                (
                    canonicalize_name(name),
                    _PoetryDependencyVariant(
                        kind="optional" if variant.kind == "optional" else "runtime",
                        requirement=variant.requirement,
                        specifier=variant.specifier,
                        condition=variant.condition,
                        supported=variant.supported,
                    ),
                )
            )
    if project.get("optional-dependencies"):
        issues.add("Poetry project optional dependencies are not main graph roots")
    if poetry.get("dev-dependencies") or poetry.get("group"):
        issues.add("Poetry non-main dependency groups are not graph roots")
    return tuple(dependencies)


def _build_poetry_graph(
    package_records: tuple[_PoetryPackageRecord, ...],
    pyproject: dict[str, object],
    *,
    lock_version: str,
    package_issues: set[str],
) -> tuple[DependencyGraph, GraphTruncation]:
    issues = set(package_issues)
    records: list[_PoetryPackageRecord] = []
    by_name: dict[str, list[_PoetryPackageRecord]] = {}
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

    def record_truncated_package(record: _PoetryPackageRecord) -> None:
        nonlocal truncation_summary_incomplete
        record_truncated_node(record.node.package_name)
        try:
            dependencies = OBJECT_ADAPTER.validate_python(record.raw.get("dependencies", {}))
        except ValidationError:
            truncation_summary_incomplete = True
            return
        for dependency_name in dependencies:
            record_truncated_relationship(
                record.node.package_name,
                canonicalize_name(dependency_name),
            )

    for record in package_records:
        if len(records) >= _PYTHON_GRAPH_MAX_NODES:
            truncated = True
            record_truncated_package(record)
            continue
        records.append(record)
        by_name.setdefault(record.node.package_name, []).append(record)
        if record.condition is not None:
            issues.add(f"conditional Poetry package node: {record.node.instance_id}")
    if truncated:
        issues.add("Poetry dependency graph node limit was reached")

    edges: list[DependencyEdge] = []
    edge_keys: set[tuple[str, str | None, str, str, str, str | None, str | None]] = set()

    def append_reference(
        *,
        consumer_id: str,
        consumer_name: str,
        declared_name: str,
        variant: _PoetryDependencyVariant,
        inherited_condition: str | None = None,
    ) -> None:
        nonlocal truncated
        actual_name = canonicalize_name(declared_name)
        named_candidates = by_name.get(actual_name, [])
        candidates = list(named_candidates)
        if not variant.supported or variant.specifier is None:
            candidates = []
            issues.add(f"unsupported Poetry dependency requirement: {consumer_id} -> {actual_name}")
        else:
            candidates = [
                candidate
                for candidate in candidates
                if candidate.parsed_version is not None
                and candidate.parsed_version in variant.specifier
            ]
            if named_candidates and not candidates:
                issues.add(
                    f"version-incompatible Poetry dependency reference: "
                    f"{consumer_id} -> {actual_name}"
                )
        target_id = candidates[0].node.instance_id if len(candidates) == 1 else None
        if not named_candidates:
            issues.add(f"unresolved Poetry dependency reference: {consumer_id} -> {actual_name}")
        elif len(candidates) > 1:
            issues.add(f"ambiguous Poetry dependency reference: {consumer_id} -> {actual_name}")
        target_condition = candidates[0].condition if len(candidates) == 1 else None
        edge_condition = combined_condition(
            inherited_condition,
            variant.condition,
            target_condition,
        )
        if edge_condition is not None:
            issues.add(f"conditional Poetry dependency edge: {consumer_id} -> {actual_name}")
        edge_key = (
            consumer_id,
            target_id,
            declared_name,
            actual_name,
            variant.kind,
            edge_condition,
            variant.requirement,
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
                declared_name=declared_name,
                actual_name=actual_name,
                kind=variant.kind,
                condition=edge_condition,
                requirement=variant.requirement,
            )
        )

    for record in records:
        raw_dependencies = record.raw.get("dependencies", {})
        try:
            dependencies = OBJECT_ADAPTER.validate_python(raw_dependencies)
        except ValidationError as error:
            raise ValueError("Poetry package dependencies must be a table") from error
        for name, raw_dependency in dependencies.items():
            variants = _poetry_dependency_variants(raw_dependency)
            for variant in variants:
                append_reference(
                    consumer_id=record.node.instance_id,
                    consumer_name=record.node.package_name,
                    declared_name=name,
                    variant=variant,
                    inherited_condition=record.condition,
                )

    for name, variant in _poetry_root_dependencies(pyproject, issues=issues):
        append_reference(
            consumer_id="importer:.",
            consumer_name="<project>",
            declared_name=name,
            variant=variant,
        )
    if truncated:
        issues.add("Poetry dependency graph edge or node limit was reached")
    return (
        DependencyGraph(
            lockfile_version=lock_version,
            nodes=tuple(record.node for record in records),
            edges=tuple(edges),
            issues=bounded_graph_issues(issues),
        ),
        GraphTruncation(
            node_names=tuple(sorted(truncated_node_names)),
            relationships=tuple(sorted(truncated_relationships)),
            incomplete=truncation_summary_incomplete,
        ),
    )


def collect_poetry_evidence(
    repository: Path,
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
        lock_name="poetry.lock",
    )
    pyproject_manifest = f"{prefix}pyproject.toml"
    lock_manifest = f"{prefix}poetry.lock"
    if pyproject_manifest in excluded_paths or lock_manifest in excluded_paths:
        raise ValueError("selected Poetry dependency file was excluded from the snapshot")
    if not pyproject_path.is_file() or not lock_path.is_file():
        raise ValueError("selected Poetry project requires adjacent pyproject.toml and poetry.lock")
    pyproject = bounded_toml_object(pyproject_path, max_dependency_file_bytes)
    lock = bounded_toml_object(lock_path, max_dependency_file_bytes)
    metadata = OBJECT_ADAPTER.validate_python(lock.get("metadata", {}))
    lock_version = metadata.get("lock-version")
    if not isinstance(lock_version, str) or lock_version not in {"1.1", "2.1"}:
        raise ValueError("only Poetry lock formats 1.1 and 2.1 are supported")
    declarations, unsupported_declaration = collect_poetry_declarations(
        pyproject,
        package_name=package_name,
        manifest_path=pyproject_manifest,
    )
    issues = {
        "Poetry support is positive-evidence only",
        "Poetry lock freshness is unverified",
    }
    tool = OBJECT_ADAPTER.validate_python(pyproject.get("tool", {}))
    poetry = OBJECT_ADAPTER.validate_python(tool.get("poetry", {}))
    custom_sources = poetry.get("source")
    if custom_sources:
        issues.add("custom Poetry sources prevent public PyPI authority")
    if unsupported_declaration:
        issues.add("matching Poetry declaration is not an unmarked direct registry dependency")
    unsupported_section_match = _poetry_unsupported_sections_mention_target(
        pyproject,
        package_name=package_name,
    )
    if unsupported_section_match:
        issues.add("matching Poetry dependency appears in an unsupported dependency section")
    if len(declarations) > 1:
        issues.add("multiple matching direct main Poetry declarations are ambiguous")

    package_records, package_issues = _parse_poetry_packages(
        lock,
        lock_version=lock_version,
        lock_manifest=lock_manifest,
    )
    package_identity = canonicalize_name(package_name)
    matches: list[tuple[int, Version]] = []
    matching_record_count = 0
    unsupported_lock_match = False
    for record in package_records:
        if record.node.package_name != package_identity:
            continue
        matching_record_count += 1
        raw_version = record.raw.get("version")
        groups = record.raw.get("groups")
        category = record.raw.get("category")
        marker = record.raw.get("markers")
        legacy_marker = record.raw.get("marker")
        source = record.raw.get("source")
        optional = record.raw.get("optional")
        selected_for_main = (
            isinstance(groups, list) and "main" in groups
            if lock_version == "2.1"
            else category == "main"
        )
        if (
            not isinstance(raw_version, str)
            or not selected_for_main
            or marker is not None
            or legacy_marker is not None
            or source is not None
            or optional is not False
        ):
            unsupported_lock_match = True
            issues.add("matching Poetry lock record has an unsupported profile or source")
            continue
        if record.parsed_version is None:
            issues.add("matching Poetry lock record has an invalid PEP 440 version")
        else:
            matches.append((record.index, record.parsed_version))

    graph, graph_truncation = _build_poetry_graph(
        package_records,
        pyproject,
        lock_version=lock_version,
        package_issues=package_issues,
    )
    target_ids = {node.instance_id for node in graph.nodes if node.package_name == package_identity}
    inbound_target_edges = [edge for edge in graph.edges if edge.actual_name == package_identity]
    unresolved_inbound_target_edge = any(edge.target_id is None for edge in inbound_target_edges)
    conditional_inbound_target_edge = any(
        edge.target_id is not None and (edge.condition is not None or edge.kind == "optional")
        for edge in inbound_target_edges
    )
    if unresolved_inbound_target_edge:
        issues.add(
            "matching Poetry lock record has an ambiguous, unsupported, "
            "or version-incompatible inbound edge"
        )
    if conditional_inbound_target_edge:
        issues.add("matching Poetry lock record has a conditional or optional inbound edge")
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
    if (conditional_inbound_target_edge or conditional_ancestry) and not unconditional_runtime_path:
        issues.add("matching Poetry target has conditional dependency ancestry")
    elif conditional_inbound_target_edge or conditional_ancestry:
        issues.add("matching Poetry target also has conditional dependency alternatives")
    if paths_truncated:
        issues.add(
            "matching Poetry target graph context was truncated; positive authority withheld"
        )

    instances: tuple[DependencyInstance, ...] = ()
    if matching_record_count != 1 or len(matches) != 1 or unsupported_lock_match:
        if matching_record_count:
            issues.add("matching Poetry lock records are ambiguous")
    elif (
        len(declarations) <= 1
        and not unsupported_declaration
        and not unsupported_section_match
        and not custom_sources
        and not unresolved_inbound_target_edge
        and (not conditional_inbound_target_edge or unconditional_runtime_path)
        and (not conditional_ancestry or unconditional_runtime_path)
        and not paths_truncated
    ):
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
        ecosystem="pip",
        package_manager="poetry",
        version_scheme="pep440",
        lockfile_version=lock_version,
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
