"""Resource-bounded pnpm lockfile v9 parsing."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any, cast

import yaml
from pydantic import TypeAdapter, ValidationError
from yaml.nodes import MappingNode, Node, ScalarNode
from yaml.tokens import AliasToken, AnchorToken, TagToken, Token

from dependabot_validator_grunt.dependency_graph import (
    DependencyEdge,
    DependencyEdgeKind,
    DependencyGraph,
    DependencyNode,
)
from dependabot_validator_grunt.models import NpmDeclaration

_SEMVER = re.compile(
    r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
_MAX_NODES = 500_000
_MAX_DEPTH = 100
_MAX_SCALAR_CHARACTERS = 1_000_000


def _mapping(value: object, field: str) -> dict[str, object]:
    if value is None:
        return {}
    try:
        return TypeAdapter(dict[str, object]).validate_python(value)
    except ValidationError as error:
        raise ValueError(f"pnpm lockfile {field} must be a mapping") from error


def _validate_node(node: Node, *, depth: int, counter: list[int]) -> None:
    counter[0] += 1
    if counter[0] > _MAX_NODES:
        raise ValueError("pnpm lockfile exceeds the configured node limit")
    if depth > _MAX_DEPTH:
        raise ValueError("pnpm lockfile exceeds the configured nesting limit")
    if isinstance(node, ScalarNode):
        if len(node.value) > _MAX_SCALAR_CHARACTERS:
            raise ValueError("pnpm lockfile scalar exceeds the configured limit")
        return
    if isinstance(node, MappingNode):
        keys: set[str] = set()
        for key_node, value_node in node.value:
            if not isinstance(key_node, ScalarNode):
                raise ValueError("pnpm lockfile mapping key is not scalar")
            if key_node.value in keys:
                raise ValueError("pnpm lockfile contains duplicate mapping keys")
            keys.add(key_node.value)
            _validate_node(key_node, depth=depth + 1, counter=counter)
            _validate_node(value_node, depth=depth + 1, counter=counter)
        return
    for child in node.value:
        _validate_node(child, depth=depth + 1, counter=counter)


def _yaml_documents(text: str) -> list[dict[str, object]]:
    try:
        raw_tokens: Any = yaml.scan(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            text, Loader=yaml.SafeLoader
        )
        for token in cast(Iterable[Token], raw_tokens):
            if isinstance(token, (AliasToken, AnchorToken, TagToken)):
                raise ValueError("pnpm lockfile YAML aliases and tags are unsupported")
        raw_nodes: Any = yaml.compose_all(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            text, Loader=yaml.SafeLoader
        )
        nodes = list(cast(Iterable[Node | None], raw_nodes))
        if len(nodes) != 1:
            raise ValueError("pnpm lockfile must contain exactly one document")
        counter = [0]
        for node in nodes:
            if node is None:
                raise ValueError("pnpm lockfile document is empty")
            _validate_node(node, depth=1, counter=counter)
        raw_documents: Any = yaml.safe_load_all(text)
        return [
            TypeAdapter(dict[str, object]).validate_python(document)
            for document in cast(Iterable[object], raw_documents)
        ]
    except (yaml.YAMLError, ValidationError) as error:
        raise ValueError("pnpm lockfile contains malformed YAML") from error


def _package_identity(value: str) -> tuple[str, str | None]:
    base = value.split("(", 1)[0]
    separator = base.rfind("@") if base.startswith("@") else base.find("@")
    if separator <= 0:
        return base, None
    return base[:separator], base[separator + 1 :]


def _dependency_target(
    name: str,
    raw_value: object,
    node_ids: set[str],
) -> tuple[str, str | None]:
    if isinstance(raw_value, dict):
        raw_value = _mapping(cast(object, raw_value), "dependency").get("version")
    if not isinstance(raw_value, str):
        return name, None
    actual_name = name
    version = raw_value
    if raw_value.startswith("npm:"):
        alias = raw_value.removeprefix("npm:")
        actual_name, version = _package_identity(alias)
    if version is None:
        return actual_name, None
    exact_candidate = f"{actual_name}@{version}"
    if exact_candidate in node_ids:
        return actual_name, exact_candidate
    base_version = version.split("(", 1)[0]
    candidate = f"{actual_name}@{base_version}"
    if candidate in node_ids:
        return actual_name, candidate
    matches = sorted(node_id for node_id in node_ids if node_id.startswith(f"{candidate}("))
    return actual_name, matches[0] if len(matches) == 1 else None


def parse_pnpm_v9(
    text: str,
    *,
    declarations: tuple[NpmDeclaration, ...],
) -> DependencyGraph:
    """Parse pnpm lockfile v9 into a normalized graph."""
    parsed = _yaml_documents(text)
    project = parsed[-1]
    version = str(project.get("lockfileVersion", ""))
    if version != "9.0":
        raise ValueError("only pnpm lockfile version 9.0 is supported")

    packages = _mapping(project.get("packages"), "packages")
    node_ids = set(packages)
    nodes: list[DependencyNode] = []
    for instance_id, raw_entry in sorted(packages.items()):
        name, version_value = _package_identity(instance_id)
        entry = _mapping(raw_entry, f"package {instance_id}")
        resolution = _mapping(entry.get("resolution"), f"package resolution {instance_id}")
        tarball = resolution.get("tarball")
        integrity = resolution.get("integrity")
        registry_tarball = isinstance(tarball, str) and tarball.startswith(
            ("https://registry.npmjs.org/", "https://registry.yarnpkg.com/")
        )
        registry_integrity = isinstance(integrity, str) and bool(integrity.strip())
        registry_source = registry_tarball or registry_integrity
        nodes.append(
            DependencyNode(
                instance_id=f"pnpm:{instance_id}",
                package_name=name,
                version=version_value,
                comparable=bool(
                    registry_source and version_value and _SEMVER.fullmatch(version_value)
                ),
            )
        )
    prefixed_node_ids = {f"pnpm:{node_id}" for node_id in node_ids}
    edges: list[DependencyEdge] = []
    snapshots = _mapping(project.get("snapshots"), "snapshots")
    for consumer, raw_snapshot in snapshots.items():
        snapshot = _mapping(raw_snapshot, f"snapshot {consumer}")
        for section, kind in (
            ("dependencies", "transitive"),
            ("optionalDependencies", "optional"),
        ):
            for name, raw_value in _mapping(snapshot.get(section), section).items():
                actual_name, target = _dependency_target(name, raw_value, node_ids)
                edges.append(
                    DependencyEdge(
                        consumer_id=f"pnpm:{consumer}",
                        target_id=f"pnpm:{target}" if target is not None else None,
                        declared_name=name,
                        actual_name=actual_name,
                        kind=cast(DependencyEdgeKind, kind),
                    )
                )
    importers = _mapping(project.get("importers"), "importers")
    declaration_by_name = {declaration.name: declaration for declaration in declarations}
    for importer, raw_importer in importers.items():
        importer_data = _mapping(raw_importer, f"importer {importer}")
        for section, kind in (
            ("dependencies", "runtime"),
            ("devDependencies", "development"),
            ("optionalDependencies", "optional"),
        ):
            for name, raw_value in _mapping(importer_data.get(section), section).items():
                actual_name, target = _dependency_target(name, raw_value, node_ids)
                declaration = declaration_by_name.get(name)
                if declaration is not None:
                    actual_name = declaration.alias_target or declaration.name
                edges.append(
                    DependencyEdge(
                        consumer_id=f"importer:{importer}",
                        target_id=f"pnpm:{target}" if target is not None else None,
                        declared_name=name,
                        actual_name=actual_name,
                        kind=cast(DependencyEdgeKind, kind),
                    )
                )
    unknown_targets = sorted(
        edge.target_id
        for edge in edges
        if edge.target_id is not None and edge.target_id not in prefixed_node_ids
    )
    return DependencyGraph(
        package_manager="pnpm",
        lockfile_version=version,
        nodes=tuple(nodes),
        edges=tuple(edges),
        issues=tuple(f"unknown pnpm target: {target}" for target in unknown_targets),
    )
