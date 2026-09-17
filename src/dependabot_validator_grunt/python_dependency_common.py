"""Shared bounded helpers for concrete Python dependency collectors."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePath, PurePosixPath

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from pydantic import TypeAdapter, ValidationError

from dependabot_validator_grunt.dependency_graph import DependencyGraph, project_paths
from dependabot_validator_grunt.models import DependencyPath, canonical_json

OBJECT_ADAPTER = TypeAdapter(dict[str, object])
OBJECT_LIST_ADAPTER = TypeAdapter(list[object])
STRING_LIST_ADAPTER = TypeAdapter(list[str])
_PYTHON_GRAPH_MAX_ISSUES = 200
DEFAULT_MAX_DEPENDENCY_PATHS = 20
DEFAULT_MAX_DEPENDENCY_PATH_DEPTH = 20
DEFAULT_MAX_DEPENDENCY_PATH_BYTES = 64 * 1024


@dataclass(frozen=True)
class GraphTruncation:
    node_names: tuple[str, ...] = ()
    relationships: tuple[tuple[str, str], ...] = ()
    incomplete: bool = False


def normalized_manifest_path(repository: Path, manifest_path: str) -> tuple[Path, str]:
    normalized = PurePosixPath(PurePath(manifest_path).as_posix())
    if normalized.is_absolute() or ".." in normalized.parts:
        raise ValueError("unsupported Python alert manifest path")
    resolved_repository = repository.resolve(strict=True)
    selected = repository.joinpath(*normalized.parts)
    resolved_selected = selected.resolve(strict=False)
    if resolved_repository not in resolved_selected.parents:
        raise ValueError("Python project path escapes the repository snapshot")
    if any(
        repository.joinpath(*normalized.parts[:index]).is_symlink()
        for index in range(1, len(normalized.parts) + 1)
    ):
        raise ValueError("Python project path contains a symlink")
    return selected, normalized.as_posix()


def selected_project_paths(
    repository: Path,
    manifest_path: str,
    *,
    lock_name: str,
) -> tuple[Path, Path, str]:
    normalized = PurePosixPath(PurePath(manifest_path).as_posix())
    if (
        normalized.is_absolute()
        or ".." in normalized.parts
        or normalized.name not in {"pyproject.toml", lock_name}
    ):
        raise ValueError("unsupported Python project manifest path")
    resolved_repository = repository.resolve(strict=True)
    project_relative = normalized.parent
    project = repository.joinpath(*project_relative.parts)
    resolved_project = project.resolve(strict=False)
    if (
        resolved_project != resolved_repository
        and resolved_repository not in resolved_project.parents
    ):
        raise ValueError("Python project path escapes the repository snapshot")
    if any(
        repository.joinpath(*normalized.parts[:index]).is_symlink()
        for index in range(1, len(normalized.parts) + 1)
    ):
        raise ValueError("Python project path contains a symlink")
    prefix = "" if project_relative == PurePosixPath(".") else f"{project_relative.as_posix()}/"
    return project / "pyproject.toml", project / lock_name, prefix


def pep440_specifier(value: str, *, allow_empty: bool = False) -> SpecifierSet | None:
    if not value and not allow_empty:
        return None
    try:
        return SpecifierSet(value)
    except InvalidSpecifier:
        return None


def combined_condition(*conditions: str | None) -> str | None:
    parts = [condition for condition in conditions if condition]
    return "; ".join(parts) if parts else None


def condition_value(name: str, value: object) -> str:
    rendered = value if isinstance(value, str) else canonical_json(value)
    return f"{name}={rendered}"


def bounded_graph_issues(issues: set[str]) -> tuple[str, ...]:
    ordered = sorted(issues)
    if len(ordered) <= _PYTHON_GRAPH_MAX_ISSUES:
        return tuple(ordered)
    return (
        *ordered[:_PYTHON_GRAPH_MAX_ISSUES],
        f"{len(ordered) - _PYTHON_GRAPH_MAX_ISSUES} additional graph issues omitted",
    )


def requirement_list_mentions(
    value: object,
    *,
    package_identity: str,
    context: str,
) -> bool:
    try:
        requirements = OBJECT_LIST_ADAPTER.validate_python(value)
    except ValidationError as error:
        raise ValueError(f"{context} must be an array") from error
    for raw_requirement in requirements:
        if not isinstance(raw_requirement, str):
            raise ValueError(f"{context} entries must be strings")
        try:
            requirement = Requirement(raw_requirement)
        except InvalidRequirement as error:
            raise ValueError(f"{context} contains a malformed dependency") from error
        if canonicalize_name(requirement.name) == package_identity:
            return True
    return False


def graph_target_context(
    graph: DependencyGraph,
    *,
    target_ids: set[str],
    candidate_name: str | None = None,
    graph_truncation: GraphTruncation,
    max_dependency_paths: int,
    max_dependency_path_depth: int,
    max_dependency_path_bytes: int,
) -> tuple[tuple[str, ...], tuple[DependencyPath, ...], bool, bool]:
    consumers = tuple(
        sorted(
            {
                edge.consumer_id
                for edge in graph.edges
                if (
                    edge.target_id in target_ids
                    or (candidate_name is not None and edge.actual_name == candidate_name)
                )
                and not edge.consumer_id.startswith("importer:")
            }
        )
    )
    if not target_ids:
        target_truncated = _graph_truncation_affects_target(
            graph,
            graph_truncation=graph_truncation,
            ancestry_ids=frozenset(),
            candidate_name=candidate_name,
        )
        return consumers, (), target_truncated, False
    paths, paths_truncated, conditional_ancestry, ancestry_ids = project_paths(
        graph,
        target_ids=target_ids,
        max_paths=max_dependency_paths,
        max_depth=max_dependency_path_depth,
        max_serialized_bytes=max_dependency_path_bytes,
    )
    target_truncated = _graph_truncation_affects_target(
        graph,
        graph_truncation=graph_truncation,
        ancestry_ids=ancestry_ids,
        candidate_name=candidate_name,
    )
    return consumers, paths, target_truncated or paths_truncated, conditional_ancestry


def has_unconditional_runtime_path(paths: tuple[DependencyPath, ...]) -> bool:
    """Return whether one complete recorded runtime path selects the target."""
    return any(
        not path.conditional and not path.development_only and not path.cycle_detected
        for path in paths
    )


def _graph_truncation_affects_target(
    graph: DependencyGraph,
    *,
    graph_truncation: GraphTruncation,
    ancestry_ids: frozenset[str],
    candidate_name: str | None,
) -> bool:
    if graph_truncation.incomplete:
        return True
    if not graph_truncation.node_names and not graph_truncation.relationships:
        return False
    nodes = {node.instance_id: node for node in graph.nodes}
    relevant_names = {
        node.package_name
        for instance_id in ancestry_ids
        if (node := nodes.get(instance_id)) is not None
    }
    if candidate_name is not None:
        relevant_names.add(candidate_name)
    affected = any(name in relevant_names for name in graph_truncation.node_names)
    changed = True
    while changed:
        changed = False
        for consumer_name, dependency_name in graph_truncation.relationships:
            if dependency_name not in relevant_names:
                continue
            affected = True
            if consumer_name != "<project>" and consumer_name not in relevant_names:
                relevant_names.add(consumer_name)
                changed = True
    return affected
