"""Package-manager-neutral dependency path projection tests."""

import pytest
from pydantic import ValidationError

from dependabot_validator_grunt.dependency_graph import (
    DependencyEdge,
    DependencyGraph,
    DependencyNode,
    project_paths,
)
from dependabot_validator_grunt.models import DependencyDeclaration, DependencyPath


def test_project_paths_records_root_to_transitive_target() -> None:
    graph = DependencyGraph(
        lockfile_version="2.1",
        nodes=(
            DependencyNode("poetry:parent@1", "parent", "1", True),
            DependencyNode("poetry:target@2", "target", "2", True),
        ),
        edges=(
            DependencyEdge(
                "importer:.",
                "poetry:parent@1",
                "parent",
                "parent",
                "runtime",
                requirement=">=1,<2",
            ),
            DependencyEdge(
                "poetry:parent@1",
                "poetry:target@2",
                "target",
                "target",
                "transitive",
                requirement=None,
            ),
        ),
    )

    paths, truncated, conditional_ancestry, ancestry_ids = project_paths(
        graph,
        target_ids={"poetry:target@2"},
    )

    assert not truncated
    assert not conditional_ancestry
    assert ancestry_ids == frozenset({"poetry:parent@1", "poetry:target@2"})
    assert [node.package_name for node in paths[0].nodes] == ["<project>", "parent", "target"]
    assert paths[0].edge_kinds == ("runtime", "transitive")
    assert paths[0].edge_requirements == (">=1,<2", None)
    assert not paths[0].conditional


def test_project_paths_propagates_conditions() -> None:
    graph = DependencyGraph(
        lockfile_version="1",
        nodes=(
            DependencyNode("uv:parent@1", "parent", "1", True),
            DependencyNode("uv:target@2", "target", "2", True),
        ),
        edges=(
            DependencyEdge(
                "importer:.",
                "uv:parent@1",
                "parent",
                "parent",
                "runtime",
                condition="python_version >= '3.12'",
            ),
            DependencyEdge(
                "uv:parent@1",
                "uv:target@2",
                "target",
                "target",
                "transitive",
            ),
        ),
    )

    paths, truncated, conditional_ancestry, _ancestry_ids = project_paths(
        graph,
        target_ids={"uv:target@2"},
    )

    assert not truncated
    assert conditional_ancestry
    assert paths[0].conditions == ("python_version >= '3.12'", None)
    assert paths[0].conditional


def test_project_paths_bounds_serialized_edge_requirements() -> None:
    graph = DependencyGraph(
        lockfile_version="1",
        nodes=(DependencyNode("target", "target", "1", True),),
        edges=(
            DependencyEdge(
                "importer:.",
                "target",
                "target",
                "target",
                "runtime",
                requirement=">=1",
            ),
        ),
    )

    paths, truncated, conditional_ancestry, _ancestry_ids = project_paths(
        graph,
        target_ids={"target"},
        max_serialized_bytes=1,
    )

    assert paths == ()
    assert truncated
    assert not conditional_ancestry


def test_project_paths_truncates_oversized_edge_requirement() -> None:
    graph = DependencyGraph(
        lockfile_version="1",
        nodes=(DependencyNode("target", "target", "1", True),),
        edges=(
            DependencyEdge(
                "importer:.",
                "target",
                "target",
                "target",
                "runtime",
                requirement="x" * 513,
            ),
        ),
    )

    paths, truncated, conditional_ancestry, _ancestry_ids = project_paths(
        graph,
        target_ids={"target"},
    )

    assert paths == ()
    assert truncated
    assert not conditional_ancestry


def test_project_paths_truncates_unreachable_branching_dag_by_traversal_budget() -> None:
    levels = tuple(
        tuple(
            DependencyNode(f"node:{level}:{branch}", f"level-{level}", "1", True)
            for branch in range(2)
        )
        for level in range(10)
    )
    nodes = (DependencyNode("target", "target", "1", True),) + tuple(
        node for level in levels for node in level
    )
    edges = [
        DependencyEdge(node.instance_id, "target", "target", "target", "transitive")
        for node in levels[0]
    ]
    for lower_level, upper_level in zip(levels, levels[1:], strict=False):
        edges.extend(
            DependencyEdge(
                consumer.instance_id,
                dependency.instance_id,
                dependency.package_name,
                dependency.package_name,
                "transitive",
            )
            for dependency in lower_level
            for consumer in upper_level
        )
    graph = DependencyGraph(
        lockfile_version="2.1",
        nodes=nodes,
        edges=tuple(edges),
    )

    paths, truncated, conditional_ancestry, _ancestry_ids = project_paths(
        graph,
        target_ids={"target"},
        max_depth=20,
        max_traversal_steps=50,
    )

    assert paths == ()
    assert truncated
    assert not conditional_ancestry


def test_project_paths_preserves_cycle_edge_alignment() -> None:
    graph = DependencyGraph(
        lockfile_version="2.1",
        nodes=(
            DependencyNode("parent", "parent", "1", True),
            DependencyNode("target", "target", "2", True),
        ),
        edges=(
            DependencyEdge(
                "parent",
                "target",
                "target",
                "target",
                "transitive",
                requirement=">=2",
            ),
            DependencyEdge(
                "target",
                "parent",
                "parent",
                "parent",
                "transitive",
                requirement=">=1",
            ),
        ),
    )

    paths, truncated, conditional_ancestry, _ancestry_ids = project_paths(
        graph,
        target_ids={"target"},
    )

    assert truncated
    assert not conditional_ancestry
    assert len(paths) == 1
    assert paths[0].cycle_detected
    assert len(paths[0].edge_requirements) == len(paths[0].nodes) - 1
    assert paths[0].edge_requirements == (">=1", ">=2")


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("edge_kinds", ()),
        ("edge_requirements", ()),
        ("conditions", ()),
    ),
)
def test_dependency_path_rejects_misaligned_edge_shapes(
    field: str,
    value: tuple[object, ...],
) -> None:
    data: dict[str, object] = {
        "nodes": (
            {"instance_id": "importer:.", "package_name": "<project>"},
            {"instance_id": "target", "package_name": "target"},
        ),
        "edge_kinds": ("runtime",),
        "edge_requirements": (None,),
        "conditions": (None,),
    }
    data[field] = value

    with pytest.raises(ValidationError, match="connect every adjacent node"):
        DependencyPath.model_validate(data)


def test_dependency_path_rejects_oversized_edge_requirement() -> None:
    with pytest.raises(ValidationError, match="bounded text"):
        DependencyPath.model_validate(
            {
                "nodes": (
                    {"instance_id": "importer:.", "package_name": "<project>"},
                    {"instance_id": "target", "package_name": "target"},
                ),
                "edge_kinds": ("runtime",),
                "edge_requirements": ("x" * 513,),
                "conditions": (None,),
            }
        )


def test_removed_serialized_model_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        DependencyPath.model_validate(
            {
                "nodes": ({"instance_id": "target", "package_name": "target"},),
                "edge_kinds": (),
                "edge_requirements": (),
                "conditions": (),
                "truncated": True,
            }
        )
    with pytest.raises(ValidationError):
        DependencyDeclaration.model_validate(
            {
                "manifest_path": "pyproject.toml",
                "name": "target",
                "spec": ">=1",
                "relationship": "direct",
                "groups": ("main",),
            }
        )
