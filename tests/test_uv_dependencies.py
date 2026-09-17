"""uv dependency evidence tests."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from python_dependency_test_support import (
    CASES,
    python_agent_response,
    write_uv_project,
)

import dependabot_validator_grunt.uv_dependencies as uv_dependencies_module
from dependabot_validator_grunt.python_dependencies import collect_python_evidence
from dependabot_validator_grunt.uv_dependencies import collect_uv_evidence
from dependabot_validator_grunt.workflow import (
    triage_offline_fixture,
)


def test_uv_direct_main_lock_record_is_positive_partial_evidence(tmp_path: Path) -> None:
    write_uv_project(tmp_path)

    evidence = collect_uv_evidence(
        tmp_path,
        "uv",
        "Requests",
        "uv.lock",
        max_dependency_file_bytes=32 * 1024 * 1024,
        excluded_paths=(),
        max_dependency_paths=20,
        max_dependency_path_depth=20,
        max_dependency_path_bytes=64 * 1024,
    )

    assert evidence.ecosystem == "uv"
    assert evidence.package_manager == "uv"
    assert evidence.lockfile_version == "1.3"
    assert evidence.proof_capabilities == ("resolved_instances",)
    assert evidence.instances[0].version == "2.31.0"
    assert evidence.instances[0].source_kind == "registry"
    assert evidence.instances[0].source_locator == "https://pypi.org/simple"


def test_uv_unique_transitive_lock_record_is_positive_evidence(tmp_path: Path) -> None:
    write_uv_project(tmp_path, dependency='"httpx>=0.28"')

    evidence = collect_python_evidence(
        tmp_path,
        "pip",
        "requests",
        "uv.lock",
    )

    assert evidence.instances[0].version == "2.31.0"
    assert evidence.instances[0].relationship == "transitive"
    assert evidence.proof_capabilities == ("resolved_instances",)


def test_uv_unconditional_path_retains_authority_with_conditional_alternative(
    tmp_path: Path,
) -> None:
    write_uv_project(
        tmp_path,
        dependency=('"parent-a==1.0.0; python_version < \'3.13\'", "parent-b==1.0.0"'),
        package="""
[[package]]
name = "parent-a"
version = "1.0.0"
source = { registry = "https://pypi.org/simple" }
dependencies = [{ name = "requests" }]

[[package]]
name = "parent-b"
version = "1.0.0"
source = { registry = "https://pypi.org/simple" }
dependencies = [{ name = "requests" }]

[[package]]
name = "requests"
version = "2.31.0"
source = { registry = "https://pypi.org/simple" }
""",
    )

    evidence = collect_python_evidence(tmp_path, "uv", "requests", "uv.lock")

    assert evidence.instances[0].version == "2.31.0"
    assert evidence.proof_capabilities == ("resolved_instances",)
    assert evidence.dependency_consumers == (
        "uv.lock:package[0]",
        "uv.lock:package[1]",
    )
    assert {
        tuple(node.package_name for node in path.nodes) for path in evidence.dependency_paths
    } == {
        ("<project>", "parent-a", "requests"),
        ("<project>", "parent-b", "requests"),
    }
    assert {path.conditional for path in evidence.dependency_paths} == {False, True}
    assert {path.edge_requirements for path in evidence.dependency_paths} == {
        ("==1.0.0", None),
    }
    assert any(
        'python_version < "3.13"' in condition
        for path in evidence.dependency_paths
        for condition in path.conditions
        if condition is not None
    )
    assert "conditional dependency alternatives" in " ".join(evidence.issues)


def test_uv_path_preserves_explicit_package_requirement(tmp_path: Path) -> None:
    write_uv_project(
        tmp_path,
        dependency='"parent==1.0.0"',
        package="""
[[package]]
name = "parent"
version = "1.0.0"
source = { registry = "https://pypi.org/simple" }
dependencies = [{ name = "requests" }]

[package.metadata]
requires-dist = [{ name = "requests", specifier = ">=2,<3" }]

[[package]]
name = "requests"
version = "2.31.0"
source = { registry = "https://pypi.org/simple" }
""",
    )

    evidence = collect_python_evidence(tmp_path, "uv", "requests", "uv.lock")

    assert evidence.proof_capabilities == ("resolved_instances",)
    assert evidence.dependency_paths[0].edge_requirements == (
        "==1.0.0",
        ">=2,<3",
    )


def test_uv_ambiguous_reference_is_a_graph_issue_not_a_guessed_path(
    tmp_path: Path,
) -> None:
    write_uv_project(
        tmp_path,
        dependency='"parent>=1"',
        package="""
[[package]]
name = "parent"
version = "1.0.0"
source = { registry = "https://pypi.org/simple" }
dependencies = [{ name = "requests" }]

[[package]]
name = "parent"
version = "2.0.0"
source = { registry = "https://pypi.org/simple" }
dependencies = [{ name = "requests" }]

[[package]]
name = "requests"
version = "2.31.0"
source = { registry = "https://pypi.org/simple" }
""",
    )

    evidence = collect_python_evidence(tmp_path, "uv", "requests", "uv.lock")

    assert evidence.proof_capabilities == ("resolved_instances",)
    assert evidence.dependency_consumers == (
        "uv.lock:package[0]",
        "uv.lock:package[1]",
    )
    assert evidence.dependency_paths == ()
    assert any("ambiguous uv dependency reference" in issue for issue in evidence.issues)


def test_uv_reference_version_and_source_select_one_candidate_node(
    tmp_path: Path,
) -> None:
    write_uv_project(
        tmp_path,
        dependency='"root==1.0.0"',
        package="""
[[package]]
name = "root"
version = "1.0.0"
source = { registry = "https://pypi.org/simple" }
dependencies = [
    { name = "parent", version = "1.0.0", source = { registry = "https://pypi.org/simple" } },
]

[[package]]
name = "parent"
version = "1.0.0"
source = { registry = "https://pypi.org/simple" }
dependencies = [{ name = "requests" }]

[[package]]
name = "parent"
version = "2.0.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "requests"
version = "2.31.0"
source = { registry = "https://pypi.org/simple" }
""",
    )

    evidence = collect_python_evidence(tmp_path, "uv", "requests", "uv.lock")

    assert [node.package_name for node in evidence.dependency_paths[0].nodes] == [
        "<project>",
        "root",
        "parent",
        "requests",
    ]
    assert not any("root -> parent" in issue and "ambiguous" in issue for issue in evidence.issues)


def test_uv_marked_inbound_dependency_edge_withholds_authority(tmp_path: Path) -> None:
    write_uv_project(
        tmp_path,
        dependency='"httpx>=0.28"',
        package="""
[[package]]
name = "example"
version = "0.1.0"
source = { virtual = "." }
dependencies = [
    { name = "requests", marker = "sys_platform == 'win32'" },
]

[[package]]
name = "requests"
version = "2.31.0"
source = { registry = "https://pypi.org/simple" }
""",
    )

    evidence = collect_python_evidence(tmp_path, "pip", "requests", "uv.lock")

    assert evidence.instances == ()
    assert evidence.proof_capabilities == ()
    assert "conditional or optional inbound edge" in " ".join(evidence.issues)


@pytest.mark.parametrize("lock_version", ("true", "1.0"))
def test_uv_non_integer_lock_major_is_rejected(
    lock_version: str,
    tmp_path: Path,
) -> None:
    write_uv_project(tmp_path, lock_version=lock_version)

    with pytest.raises(ValueError, match="lock major version 1"):
        collect_python_evidence(tmp_path, "uv", "requests", "uv.lock")


@pytest.mark.parametrize(
    ("dependency", "extra_pyproject"),
    (
        ('"requests>=2", "requests<3"', ""),
        ('"requests>=2"', '[dependency-groups]\ndev = ["requests>=2"]'),
        ('"requests>=2"', '[tool.uv]\ndev-dependencies = ["requests>=2"]'),
    ),
)
def test_uv_duplicate_or_unsupported_target_declarations_withhold_authority(
    dependency: str,
    extra_pyproject: str,
    tmp_path: Path,
) -> None:
    write_uv_project(
        tmp_path,
        dependency=dependency,
        extra_pyproject=extra_pyproject,
    )

    evidence = collect_python_evidence(tmp_path, "uv", "requests", "uv.lock")

    assert evidence.instances == ()
    assert evidence.proof_capabilities == ()


@pytest.mark.parametrize(
    ("dependency", "package", "extra_pyproject", "revision"),
    (
        (
            '"requests[socks]>=2"',
            """
[[package]]
name = "requests"
version = "2.31.0"
source = { registry = "https://pypi.org/simple" }
""",
            "",
            3,
        ),
        (
            "\"requests>=2; python_version < '3.12'\"",
            """
[[package]]
name = "requests"
version = "2.31.0"
source = { registry = "https://pypi.org/simple" }
""",
            "",
            3,
        ),
        (
            '"requests>=2"',
            """
[[package]]
name = "requests"
version = "2.31.0"
source = { registry = "https://example.com/simple" }
""",
            "",
            3,
        ),
        (
            '"requests>=2"',
            """
[[package]]
name = "requests"
version = "2.31.0"
source = { registry = "https://pypi.org/simple" }
resolution-markers = ["python_version >= '3.12'"]
""",
            "",
            3,
        ),
        (
            '"requests>=2"',
            """
[[package]]
name = "requests"
version = "2.31.0"
source = { registry = "https://pypi.org/simple" }
""",
            '[tool.uv.workspace]\nmembers = ["packages/*"]',
            3,
        ),
        (
            '"requests>=2"',
            """
[[package]]
name = "requests"
version = "2.31.0"
source = { registry = "https://pypi.org/simple" }
""",
            "",
            4,
        ),
    ),
)
def test_uv_unsupported_selection_and_sources_withhold_positive_authority(
    dependency: str,
    package: str,
    extra_pyproject: str,
    revision: int,
    tmp_path: Path,
) -> None:
    write_uv_project(
        tmp_path,
        dependency=dependency,
        package=package,
        extra_pyproject=extra_pyproject,
        revision=revision,
    )

    evidence = collect_python_evidence(
        tmp_path,
        "uv",
        "requests",
        "pyproject.toml",
    )

    assert evidence.instances == ()
    assert evidence.proof_capabilities == ()


def test_uv_mixed_matching_lock_records_are_ambiguous(tmp_path: Path) -> None:
    write_uv_project(
        tmp_path,
        package="""
[[package]]
name = "requests"
version = "2.31.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "requests"
version = "2.32.0"
source = { registry = "https://pypi.org/simple" }
resolution-markers = ["python_version >= '3.12'"]
""",
    )

    evidence = collect_python_evidence(
        tmp_path,
        "uv",
        "requests",
        "uv.lock",
    )

    assert evidence.instances == ()
    assert evidence.proof_capabilities == ()


@pytest.mark.parametrize(
    "package",
    (
        """
[[package]]
name = "requests"
version = "2.31.0"
source = { registry = "https://pypi.org/simple" }
groups = ["dev"]
""",
        """
[[package]]
name = "requests"
version = "2.31.0"
source = { registry = "https://pypi.org/simple", fork = "alternate" }
""",
    ),
)
def test_uv_conditional_instance_keeps_candidate_path_without_authority(
    package: str,
    tmp_path: Path,
) -> None:
    write_uv_project(tmp_path, package=package)

    evidence = collect_python_evidence(tmp_path, "uv", "requests", "uv.lock")

    assert evidence.instances == ()
    assert evidence.proof_capabilities == ()
    assert evidence.dependency_consumers == ()
    assert len(evidence.dependency_paths) == 1
    assert [node.package_name for node in evidence.dependency_paths[0].nodes] == [
        "<project>",
        "requests",
    ]
    assert evidence.dependency_paths[0].conditional
    assert any(evidence.dependency_paths[0].conditions)


def test_uv_conditional_parent_propagates_to_child_edge_and_withholds_authority(
    tmp_path: Path,
) -> None:
    write_uv_project(
        tmp_path,
        dependency='"parent==1.0.0"',
        package="""
[[package]]
name = "parent"
version = "1.0.0"
source = { registry = "https://pypi.org/simple" }
groups = ["dev"]
dependencies = [{ name = "requests" }]

[[package]]
name = "requests"
version = "2.31.0"
source = { registry = "https://pypi.org/simple" }
""",
    )

    evidence = collect_python_evidence(tmp_path, "uv", "requests", "uv.lock")

    assert evidence.instances == ()
    assert evidence.proof_capabilities == ()
    assert len(evidence.dependency_paths) == 1
    path = evidence.dependency_paths[0]
    assert path.edge_requirements == ("==1.0.0", None)
    assert path.conditional
    assert path.conditions[-1] is not None
    assert 'groups=["dev"]' in path.conditions[-1]
    assert "conditional dependency ancestry" in " ".join(evidence.issues)


def test_uv_truncated_matching_nodes_keep_candidate_consumer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(uv_dependencies_module, "_PYTHON_GRAPH_MAX_NODES", 1)
    write_uv_project(
        tmp_path,
        dependency='"parent==1.0.0"',
        package="""
[[package]]
name = "parent"
version = "1.0.0"
source = { registry = "https://pypi.org/simple" }
dependencies = [{ name = "requests" }]

[[package]]
name = "requests"
version = "2.31.0"
source = { registry = "https://pypi.org/simple" }
""",
    )

    evidence = collect_python_evidence(tmp_path, "uv", "requests", "uv.lock")

    assert evidence.instances == ()
    assert evidence.proof_capabilities == ()
    assert evidence.dependency_consumers == ("uv.lock:package[0]",)
    assert evidence.dependency_paths == ()
    assert evidence.dependency_paths_truncated
    assert "target graph context was truncated" in " ".join(evidence.issues)


def test_uv_unrelated_graph_truncation_preserves_target_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(uv_dependencies_module, "_PYTHON_GRAPH_MAX_NODES", 3)
    write_uv_project(
        tmp_path,
        dependency='"parent==1.0.0"',
        package="""
[[package]]
name = "parent"
version = "1.0.0"
source = { registry = "https://pypi.org/simple" }
dependencies = [{ name = "requests" }]

[[package]]
name = "requests"
version = "2.31.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "unrelated-a"
version = "1.0.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "unrelated-b"
version = "1.0.0"
source = { registry = "https://pypi.org/simple" }
""",
    )

    evidence = collect_python_evidence(tmp_path, "uv", "requests", "uv.lock")

    assert evidence.proof_capabilities == ("resolved_instances",)
    assert evidence.instances[0].relationship == "transitive"
    assert not evidence.dependency_paths_truncated
    assert "dependency graph node limit was reached" in " ".join(evidence.issues)


async def test_uv_truncated_target_context_routes_to_human_review(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(uv_dependencies_module, "_PYTHON_GRAPH_MAX_NODES", 1)
    case = tmp_path / "case"
    shutil.copytree(CASES / "triage-absent", case)
    repository = case / "repository"
    write_uv_project(
        repository,
        dependency='"parent==1.0.0"',
        package="""
[[package]]
name = "parent"
version = "1.0.0"
source = { registry = "https://pypi.org/simple" }
dependencies = [{ name = "requests" }]

[[package]]
name = "requests"
version = "2.31.0"
source = { registry = "https://pypi.org/simple" }
""",
    )
    alert = json.loads((case / "alert.json").read_text(encoding="utf-8"))
    alert.update(
        {
            "ecosystem": "uv",
            "package_name": "requests",
            "vulnerable_range": "<2.32.0",
            "manifest_path": "uv.lock",
            "dependency_relationship": "transitive",
        }
    )
    alert.pop("package_identity", None)
    (case / "alert.json").write_text(json.dumps(alert), encoding="utf-8")
    (case / "agent-response.json").write_text(
        json.dumps(
            python_agent_response(
                "human_review",
                "insufficient_context",
                insufficient_context=True,
            )
        ),
        encoding="utf-8",
    )

    output = await triage_offline_fixture(case, tmp_path / "out")
    evidence = json.loads((output / "evidence.json").read_text(encoding="utf-8"))
    task = json.loads((output / "agent-task.json").read_text(encoding="utf-8"))
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))

    assert evidence["dependency"]["instances"] == []
    assert evidence["dependency"]["proof_capabilities"] == []
    assert evidence["dependency"]["dependency_paths_truncated"] is True
    assert task["dependency_paths_truncated"] is True
    assert report["model_identity"] == "scripted-fixture"
    assert report["result"]["assessment"] == "human_review"
    assert report["result"]["reason_code"] == "insufficient_context"


async def test_uv_unconditional_path_routes_vulnerable_instance_deterministically(
    tmp_path: Path,
) -> None:
    case = tmp_path / "case"
    shutil.copytree(CASES / "triage-absent", case)
    repository = case / "repository"
    write_uv_project(
        repository,
        dependency=('"parent-a==1.0.0; python_version < \'3.13\'", "parent-b==1.0.0"'),
        package="""
[[package]]
name = "parent-a"
version = "1.0.0"
source = { registry = "https://pypi.org/simple" }
dependencies = [{ name = "requests" }]

[[package]]
name = "parent-b"
version = "1.0.0"
source = { registry = "https://pypi.org/simple" }
dependencies = [{ name = "requests" }]

[[package]]
name = "requests"
version = "2.31.0"
source = { registry = "https://pypi.org/simple" }
""",
    )
    alert = json.loads((case / "alert.json").read_text(encoding="utf-8"))
    alert.update(
        {
            "ecosystem": "uv",
            "package_name": "requests",
            "vulnerable_range": "<2.32.0",
            "manifest_path": "uv.lock",
            "dependency_relationship": "transitive",
        }
    )
    alert.pop("package_identity", None)
    (case / "alert.json").write_text(json.dumps(alert), encoding="utf-8")

    output = await triage_offline_fixture(case, tmp_path / "out")
    evidence = json.loads((output / "evidence.json").read_text(encoding="utf-8"))
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))

    assert evidence["dependency"]["proof_capabilities"] == ["resolved_instances"]
    assert report["model_identity"] == "not_run"
    assert report["result"]["assessment"] == "applies"
    assert report["result"]["reason_code"] == "triage_vulnerable_applies"
    assert not (output / "agent-task.json").exists()
