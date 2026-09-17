"""Package-manager-neutral dependency graph normalization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from dependabot_validator_grunt.models import (
    DependencyDeclaration,
    DependencyInstance,
    DependencyPath,
    DependencyPathNode,
    SourceKind,
    validate_dependency_edge_requirement,
)

DependencyEdgeKind = Literal["runtime", "development", "optional", "peer", "transitive"]


@dataclass(frozen=True)
class DependencyNode:
    instance_id: str
    package_name: str
    version: str | None
    comparable: bool
    source_kind: SourceKind = "unknown"
    source_locator: str | None = None


@dataclass(frozen=True)
class DependencyEdge:
    consumer_id: str
    target_id: str | None
    declared_name: str
    actual_name: str
    kind: DependencyEdgeKind
    condition: str | None = None
    requirement: str | None = None


@dataclass(frozen=True)
class DependencyGraph:
    lockfile_version: str
    nodes: tuple[DependencyNode, ...]
    edges: tuple[DependencyEdge, ...]
    issues: tuple[str, ...] = ()


def project_paths(
    graph: DependencyGraph,
    *,
    target_ids: set[str],
    max_paths: int = 20,
    max_depth: int = 20,
    max_serialized_bytes: int = 64 * 1024,
    max_traversal_steps: int = 100_000,
) -> tuple[tuple[DependencyPath, ...], bool, bool, frozenset[str]]:
    """Project bounded recorded importer-to-target candidate paths."""
    if max_paths <= 0 or max_depth <= 0 or max_serialized_bytes <= 0 or max_traversal_steps <= 0:
        raise ValueError("dependency path limits must be positive")
    nodes = {node.instance_id: node for node in graph.nodes}
    incoming: dict[str, list[DependencyEdge]] = {}
    for edge in graph.edges:
        if edge.target_id is not None:
            incoming.setdefault(edge.target_id, []).append(edge)

    paths: list[DependencyPath] = []
    serialized_bytes = 0
    truncated = False
    traversal_steps = 0
    traversal_budget_exhausted = False
    conditional_ancestry = False
    ancestry_ids: set[str] = set()

    def charge_traversal_step() -> bool:
        nonlocal traversal_budget_exhausted, traversal_steps, truncated
        if traversal_steps >= max_traversal_steps:
            traversal_budget_exhausted = True
            truncated = True
            return False
        traversal_steps += 1
        return True

    def append_path(
        reversed_nodes: list[DependencyPathNode],
        reversed_edges: list[DependencyEdge],
        *,
        cycle_detected: bool = False,
    ) -> None:
        nonlocal serialized_bytes, truncated
        if len(paths) >= max_paths:
            truncated = True
            return
        ordered_nodes = tuple(reversed(reversed_nodes))
        ordered_edges = tuple(reversed(reversed_edges))
        try:
            for edge in ordered_edges:
                if edge.requirement is not None:
                    validate_dependency_edge_requirement(edge.requirement)
        except ValueError:
            truncated = True
            return
        path = DependencyPath(
            nodes=ordered_nodes,
            edge_kinds=tuple(edge.kind for edge in ordered_edges),
            edge_requirements=tuple(edge.requirement for edge in ordered_edges),
            conditions=tuple(edge.condition for edge in ordered_edges),
            conditional=any(edge.condition is not None for edge in ordered_edges),
            development_only=bool(ordered_edges) and ordered_edges[0].kind == "development",
            cycle_detected=cycle_detected,
        )
        size = len(path.model_dump_json().encode("utf-8"))
        if serialized_bytes + size > max_serialized_bytes:
            truncated = True
            return
        serialized_bytes += size
        paths.append(path)

    def walk(
        current_id: str,
        reversed_nodes: list[DependencyPathNode],
        reversed_edges: list[DependencyEdge],
        visited: set[str],
    ) -> None:
        nonlocal conditional_ancestry, truncated
        ancestry_ids.add(current_id)
        if not charge_traversal_step():
            return
        if len(reversed_edges) >= max_depth:
            truncated = True
            return
        candidate_edges = sorted(
            incoming.get(current_id, ()),
            key=lambda edge: (
                edge.consumer_id,
                edge.target_id or "",
                edge.declared_name,
                edge.kind,
            ),
        )
        if not candidate_edges:
            return
        for edge in candidate_edges:
            if traversal_budget_exhausted or not charge_traversal_step():
                return
            if edge.condition is not None:
                conditional_ancestry = True
            if len(paths) >= max_paths:
                truncated = True
                return
            if edge.consumer_id.startswith("importer:"):
                append_path(
                    [
                        *reversed_nodes,
                        DependencyPathNode(
                            instance_id=edge.consumer_id,
                            package_name="<project>",
                        ),
                    ],
                    [*reversed_edges, edge],
                )
                continue
            consumer = nodes.get(edge.consumer_id)
            if consumer is None:
                continue
            ancestry_ids.add(consumer.instance_id)
            consumer_node = DependencyPathNode(
                instance_id=consumer.instance_id,
                package_name=consumer.package_name,
                version=consumer.version,
            )
            if consumer.instance_id in visited:
                append_path(
                    [*reversed_nodes, consumer_node],
                    [*reversed_edges, edge],
                    cycle_detected=True,
                )
                truncated = True
                continue
            walk(
                consumer.instance_id,
                [*reversed_nodes, consumer_node],
                [*reversed_edges, edge],
                {*visited, consumer.instance_id},
            )

    for target_id in sorted(target_ids):
        if traversal_budget_exhausted:
            break
        target = nodes.get(target_id)
        if target is None:
            continue
        walk(
            target_id,
            [
                DependencyPathNode(
                    instance_id=target.instance_id,
                    package_name=target.package_name,
                    version=target.version,
                )
            ],
            [],
            {target_id},
        )
    return tuple(paths), truncated, conditional_ancestry, frozenset(ancestry_ids)


def project_target(
    graph: DependencyGraph,
    *,
    package_name: str,
    declarations: tuple[DependencyDeclaration, ...],
) -> tuple[tuple[DependencyInstance, ...], tuple[str, ...], tuple[str, ...]]:
    """Project one alerted package from a normalized dependency graph."""
    matching = {node.instance_id: node for node in graph.nodes if node.package_name == package_name}
    incoming: dict[str, list[DependencyEdge]] = {instance_id: [] for instance_id in matching}
    consumers: set[str] = set()
    issues = set(graph.issues)
    for edge in graph.edges:
        if edge.actual_name != package_name:
            continue
        if edge.target_id is None or edge.target_id not in matching:
            issues.add(f"unresolved target dependency edge: {edge.consumer_id}")
            continue
        incoming[edge.target_id].append(edge)
        if not edge.consumer_id.startswith("importer:"):
            consumers.add(edge.consumer_id)

    declaration_relationships = {
        declaration.relationship
        for declaration in declarations
        if declaration.name == package_name or declaration.alias_target == package_name
    }
    instances: list[DependencyInstance] = []
    for instance_id, node in sorted(matching.items()):
        if not incoming[instance_id]:
            issues.add(f"unreferenced target instance: {instance_id}")
            continue
        root_kinds = {
            edge.kind for edge in incoming[instance_id] if edge.consumer_id.startswith("importer:")
        }
        if "runtime" in root_kinds or "direct" in declaration_relationships:
            relationship = "direct"
        elif "optional" in root_kinds or "optional" in declaration_relationships:
            relationship = "optional"
        elif "development" in root_kinds or "development" in declaration_relationships:
            relationship = "development"
        else:
            relationship = "transitive"
        instances.append(
            DependencyInstance(
                path=instance_id,
                version=node.version,
                relationship=relationship,
                comparable=node.comparable,
                development_only=False,
                source_kind=node.source_kind,
                source_locator=node.source_locator,
            )
        )
    return tuple(instances), tuple(sorted(consumers)), tuple(sorted(issues))
