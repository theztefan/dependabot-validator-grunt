"""Package-manager-neutral dependency graph normalization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from dependabot_validator_grunt.models import NpmDeclaration, NpmInstance

DependencyEdgeKind = Literal["runtime", "development", "optional", "peer", "transitive"]


@dataclass(frozen=True)
class DependencyNode:
    instance_id: str
    package_name: str
    version: str | None
    comparable: bool


@dataclass(frozen=True)
class DependencyEdge:
    consumer_id: str
    target_id: str | None
    declared_name: str
    actual_name: str
    kind: DependencyEdgeKind


@dataclass(frozen=True)
class DependencyGraph:
    package_manager: Literal["yarn-classic", "pnpm"]
    lockfile_version: str
    nodes: tuple[DependencyNode, ...]
    edges: tuple[DependencyEdge, ...]
    issues: tuple[str, ...] = ()


def project_target(
    graph: DependencyGraph,
    *,
    package_name: str,
    declarations: tuple[NpmDeclaration, ...],
) -> tuple[tuple[NpmInstance, ...], tuple[str, ...], tuple[str, ...]]:
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
    instances: list[NpmInstance] = []
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
            NpmInstance(
                path=instance_id,
                version=node.version,
                relationship=relationship,
                comparable=node.comparable,
                development_only=False,
            )
        )
    return tuple(instances), tuple(sorted(consumers)), tuple(sorted(issues))
