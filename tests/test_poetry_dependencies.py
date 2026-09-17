"""Poetry dependency evidence tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from python_dependency_test_support import (
    write_poetry_project,
)

import dependabot_validator_grunt.poetry_dependencies as poetry_dependencies_module
from dependabot_validator_grunt.poetry_dependencies import collect_poetry_evidence
from dependabot_validator_grunt.python_dependencies import collect_python_evidence


def test_poetry_direct_main_lock_record_is_positive_partial_evidence(
    tmp_path: Path,
) -> None:
    write_poetry_project(tmp_path)

    evidence = collect_poetry_evidence(
        tmp_path,
        "Requests",
        "pyproject.toml",
        max_dependency_file_bytes=32 * 1024 * 1024,
        excluded_paths=(),
        max_dependency_paths=20,
        max_dependency_path_depth=20,
        max_dependency_path_bytes=64 * 1024,
    )

    assert evidence.package_manager == "poetry"
    assert evidence.lockfile_version == "2.1"
    assert evidence.proof_capabilities == ("resolved_instances",)
    assert evidence.instances[0].version == "2.31.0"
    assert evidence.instances[0].source_kind == "registry"
    assert evidence.instances[0].source_locator == "https://pypi.org/simple"


@pytest.mark.parametrize(
    ("dependency", "package", "extra_pyproject"),
    (
        (
            'requests = {version = "^2.31", source = "private"}',
            """
[[package]]
name = "requests"
version = "2.31.0"
optional = false
groups = ["main"]
""",
            "",
        ),
        (
            'requests = "^2.31"',
            """
[[package]]
name = "requests"
version = "2.31.0"
optional = false
groups = ["main"]
markers = "python_version < '3.12'"
""",
            "",
        ),
        (
            'requests = "^2.31"',
            """
[[package]]
name = "requests"
version = "2.31.0"
optional = false
groups = ["dev"]
""",
            "",
        ),
        (
            'requests = "^2.31"',
            """
[[package]]
name = "requests"
version = "2.31.0"
optional = "false"
groups = ["main"]
""",
            "",
        ),
        (
            'requests = {version = "^2.31", extras = ["socks"]}',
            """
[[package]]
name = "requests"
version = "2.31.0"
optional = false
groups = ["main"]
""",
            "",
        ),
        (
            'requests = "^2.31"',
            """
[[package]]
name = "requests"
version = "2.31.0"
optional = false
groups = ["main"]
""",
            '\n[[tool.poetry.source]]\nname = "private"\nurl = "https://example.com/simple"\n',
        ),
    ),
)
def test_poetry_unsupported_profiles_and_sources_withhold_positive_authority(
    dependency: str,
    package: str,
    extra_pyproject: str,
    tmp_path: Path,
) -> None:
    write_poetry_project(
        tmp_path,
        dependency=dependency,
        package=package,
        extra_pyproject=extra_pyproject,
    )

    evidence = collect_python_evidence(
        tmp_path,
        "pip",
        "requests",
        "poetry.lock",
    )

    assert evidence.instances == ()
    assert evidence.proof_capabilities == ()


def test_poetry_mixed_supported_and_unsupported_lock_records_are_ambiguous(
    tmp_path: Path,
) -> None:
    write_poetry_project(
        tmp_path,
        package="""
[[package]]
name = "requests"
version = "2.31.0"
optional = false
groups = ["main"]

[[package]]
name = "requests"
version = "2.32.0"
optional = false
groups = ["main"]
markers = "python_version >= '3.12'"
""",
    )

    evidence = collect_python_evidence(
        tmp_path,
        "pip",
        "requests",
        "poetry.lock",
    )

    assert evidence.instances == ()
    assert evidence.proof_capabilities == ()


def test_poetry_pep621_extras_withhold_positive_authority(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "example"
version = "0.1.0"
dependencies = ["requests[socks]>=2"]

[tool.poetry]
name = "example"
version = "0.1.0"
""",
        encoding="utf-8",
    )
    (tmp_path / "poetry.lock").write_text(
        """
[[package]]
name = "requests"
version = "2.31.0"
optional = false
groups = ["main"]

[metadata]
lock-version = "2.1"
""",
        encoding="utf-8",
    )

    evidence = collect_python_evidence(
        tmp_path,
        "pip",
        "requests",
        "pyproject.toml",
    )

    assert evidence.instances == ()
    assert evidence.proof_capabilities == ()


def test_poetry_rejects_unsupported_lock_version(tmp_path: Path) -> None:
    write_poetry_project(tmp_path)
    (tmp_path / "poetry.lock").write_text(
        '[metadata]\nlock-version = "1.0"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="1.1 and 2.1"):
        collect_python_evidence(tmp_path, "pip", "requests", "poetry.lock")


def test_poetry_unique_transitive_main_lock_record_is_positive_evidence(
    tmp_path: Path,
) -> None:
    write_poetry_project(tmp_path, dependency='httpx = "^0.28"')

    evidence = collect_python_evidence(
        tmp_path,
        "pip",
        "requests",
        "poetry.lock",
    )

    assert evidence.instances[0].version == "2.31.0"
    assert evidence.instances[0].relationship == "transitive"
    assert evidence.proof_capabilities == ("resolved_instances",)


def test_poetry_unconditional_path_retains_authority_with_conditional_alternative(
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.poetry]
name = "example"
version = "0.1.0"

[tool.poetry.dependencies]
python = "^3.12"
parent-a = ">=1,<2"
parent-b = ">=1,<2"
""",
        encoding="utf-8",
    )
    (tmp_path / "poetry.lock").write_text(
        """
[[package]]
name = "parent-a"
version = "1.0.0"
optional = false
groups = ["main"]

[package.dependencies]
requests = ">=2"

[[package]]
name = "parent-b"
version = "1.0.0"
optional = false
groups = ["main"]

[package.dependencies]
requests = { version = ">=2", markers = "python_version < '3.13'" }

[[package]]
name = "requests"
version = "2.31.0"
optional = false
groups = ["main"]

[metadata]
lock-version = "2.1"
""",
        encoding="utf-8",
    )

    evidence = collect_python_evidence(tmp_path, "pip", "requests", "poetry.lock")

    assert evidence.instances[0].version == "2.31.0"
    assert evidence.proof_capabilities == ("resolved_instances",)
    assert evidence.dependency_consumers == (
        "poetry.lock:package[0]",
        "poetry.lock:package[1]",
    )
    assert {
        tuple(node.package_name for node in path.nodes) for path in evidence.dependency_paths
    } == {
        ("<project>", "parent-a", "requests"),
        ("<project>", "parent-b", "requests"),
    }
    assert {path.conditional for path in evidence.dependency_paths} == {False, True}
    assert {path.edge_requirements for path in evidence.dependency_paths} == {
        (">=1,<2", ">=2"),
        (">=1,<2", ">=2"),
    }
    assert any(
        "markers=python_version < '3.13'" in condition
        for path in evidence.dependency_paths
        for condition in path.conditions
        if condition is not None
    )
    assert not evidence.dependency_paths_truncated
    assert "conditional dependency alternatives" in " ".join(evidence.issues)


def test_poetry_unconditional_path_does_not_override_unsupported_alternative(
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.poetry]
name = "example"
version = "0.1.0"

[tool.poetry.dependencies]
python = "^3.12"
parent-a = ">=1,<2"
parent-b = ">=1,<2"
""",
        encoding="utf-8",
    )
    (tmp_path / "poetry.lock").write_text(
        """
[[package]]
name = "parent-a"
version = "1.0.0"
optional = false
groups = ["main"]

[package.dependencies]
requests = ">=2"

[[package]]
name = "parent-b"
version = "1.0.0"
optional = false
groups = ["main"]

[package.dependencies]
requests = "^2"

[[package]]
name = "requests"
version = "2.31.0"
optional = false
groups = ["main"]

[metadata]
lock-version = "2.1"
""",
        encoding="utf-8",
    )

    evidence = collect_python_evidence(tmp_path, "pip", "requests", "poetry.lock")

    assert evidence.instances == ()
    assert evidence.proof_capabilities == ()
    assert "unsupported Poetry dependency requirement" in " ".join(evidence.issues)
    assert "ambiguous, unsupported, or version-incompatible" in " ".join(evidence.issues)


@pytest.mark.parametrize(
    ("reference", "issue_fragment", "path_expected"),
    (
        (
            'requests = { version = ">=2,<3", optional = true }',
            "conditional or optional inbound edge",
            True,
        ),
        (
            'requests = "^2"',
            "unsupported Poetry dependency requirement",
            False,
        ),
        (
            'requests = "<2"',
            "version-incompatible Poetry dependency reference",
            False,
        ),
    ),
)
def test_poetry_unsafe_inbound_target_references_withhold_authority_but_keep_context(
    reference: str,
    issue_fragment: str,
    path_expected: bool,
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.poetry]
name = "example"
version = "0.1.0"

[tool.poetry.dependencies]
python = "^3.12"
parent = ">=1,<2"
""",
        encoding="utf-8",
    )
    (tmp_path / "poetry.lock").write_text(
        f"""
[[package]]
name = "parent"
version = "1.0.0"
optional = false
groups = ["main"]

[package.dependencies]
{reference}

[[package]]
name = "requests"
version = "2.31.0"
optional = false
groups = ["main"]

[metadata]
lock-version = "2.1"
""",
        encoding="utf-8",
    )

    evidence = collect_python_evidence(tmp_path, "pip", "requests", "poetry.lock")

    assert evidence.instances == ()
    assert evidence.proof_capabilities == ()
    assert evidence.dependency_consumers == ("poetry.lock:package[0]",)
    assert bool(evidence.dependency_paths) is path_expected
    assert issue_fragment in " ".join(evidence.issues)


def test_poetry_ambiguous_inbound_target_reference_remains_candidate_context(
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.poetry]
name = "example"
version = "0.1.0"

[tool.poetry.dependencies]
python = "^3.12"
parent = ">=1,<2"
""",
        encoding="utf-8",
    )
    (tmp_path / "poetry.lock").write_text(
        """
[[package]]
name = "parent"
version = "1.0.0"
optional = false
groups = ["main"]
dependencies = { requests = ">=2,<4" }

[[package]]
name = "requests"
version = "2.31.0"
optional = false
groups = ["main"]

[[package]]
name = "requests"
version = "3.0.0"
optional = false
groups = ["main"]

[metadata]
lock-version = "2.1"
""",
        encoding="utf-8",
    )

    evidence = collect_python_evidence(tmp_path, "pip", "requests", "poetry.lock")

    assert evidence.instances == ()
    assert evidence.proof_capabilities == ()
    assert evidence.dependency_consumers == ("poetry.lock:package[0]",)
    assert evidence.dependency_paths == ()
    assert "ambiguous Poetry dependency reference" in " ".join(evidence.issues)


def test_poetry_pep440_requirement_selects_compatible_candidate_node(
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.poetry]
name = "example"
version = "0.1.0"

[tool.poetry.dependencies]
python = "^3.12"
parent = ">=2,<3"
""",
        encoding="utf-8",
    )
    (tmp_path / "poetry.lock").write_text(
        """
[[package]]
name = "parent"
version = "1.0.0"
optional = false
groups = ["main"]

[[package]]
name = "parent"
version = "2.0.0"
optional = false
groups = ["main"]
dependencies = { requests = ">=2,<3" }

[[package]]
name = "requests"
version = "2.31.0"
optional = false
groups = ["main"]

[metadata]
lock-version = "2.1"
""",
        encoding="utf-8",
    )

    evidence = collect_python_evidence(tmp_path, "pip", "requests", "poetry.lock")

    assert evidence.proof_capabilities == ("resolved_instances",)
    assert [(node.package_name, node.version) for node in evidence.dependency_paths[0].nodes] == [
        ("<project>", None),
        ("parent", "2.0.0"),
        ("requests", "2.31.0"),
    ]
    assert not any(
        "ambiguous Poetry dependency reference: importer:. -> parent" in issue
        for issue in evidence.issues
    )


def test_poetry_lock_1_1_records_transitive_candidate_path(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.poetry]
name = "example"
version = "0.1.0"

[tool.poetry.dependencies]
python = "^3.9"
parent = "==1.0.0"
""",
        encoding="utf-8",
    )
    (tmp_path / "poetry.lock").write_text(
        """
[[package]]
name = "parent"
version = "1.0.0"
category = "main"
optional = false

[package.dependencies]
requests = "==2.31.0"

[[package]]
name = "requests"
version = "2.31.0"
category = "main"
optional = false

[metadata]
lock-version = "1.1"
""",
        encoding="utf-8",
    )

    evidence = collect_python_evidence(tmp_path, "pip", "requests", "poetry.lock")

    assert [node.package_name for node in evidence.dependency_paths[0].nodes] == [
        "<project>",
        "parent",
        "requests",
    ]


def test_poetry_candidate_paths_are_bounded_by_injected_limit(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.poetry]
name = "example"
version = "0.1.0"

[tool.poetry.dependencies]
python = "^3.12"
parent-a = ">=1,<2"
parent-b = ">=1,<2"
""",
        encoding="utf-8",
    )
    (tmp_path / "poetry.lock").write_text(
        """
[[package]]
name = "parent-a"
version = "1.0.0"
optional = false
groups = ["main"]
dependencies = { requests = ">=2" }

[[package]]
name = "parent-b"
version = "1.0.0"
optional = false
groups = ["main"]
dependencies = { requests = ">=2" }

[[package]]
name = "requests"
version = "2.31.0"
optional = false
groups = ["main"]

[metadata]
lock-version = "2.1"
""",
        encoding="utf-8",
    )

    evidence = collect_python_evidence(
        tmp_path,
        "pip",
        "requests",
        "poetry.lock",
        max_dependency_paths=1,
    )

    assert len(evidence.dependency_paths) == 1
    assert evidence.dependency_paths_truncated
    assert evidence.instances == ()
    assert evidence.proof_capabilities == ()
    assert "target graph context was truncated" in " ".join(evidence.issues)


def test_poetry_unrelated_graph_truncation_preserves_target_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(poetry_dependencies_module, "_PYTHON_GRAPH_MAX_NODES", 3)
    write_poetry_project(
        tmp_path,
        dependency='parent = ">=1,<2"',
        package="""
[[package]]
name = "parent"
version = "1.0.0"
optional = false
groups = ["main"]
dependencies = { requests = ">=2" }

[[package]]
name = "requests"
version = "2.31.0"
optional = false
groups = ["main"]

[[package]]
name = "unrelated-a"
version = "1.0.0"
optional = false
groups = ["main"]

[[package]]
name = "unrelated-b"
version = "1.0.0"
optional = false
groups = ["main"]
""",
    )

    evidence = collect_python_evidence(tmp_path, "pip", "requests", "poetry.lock")

    assert evidence.proof_capabilities == ("resolved_instances",)
    assert evidence.instances[0].relationship == "transitive"
    assert not evidence.dependency_paths_truncated
    assert "dependency graph node limit was reached" in " ".join(evidence.issues)


def test_poetry_conditional_ancestor_withholds_target_authority(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.poetry]
name = "example"
version = "0.1.0"

[tool.poetry.dependencies]
python = "^3.12"
ancestor = ">=1,<2"
""",
        encoding="utf-8",
    )
    (tmp_path / "poetry.lock").write_text(
        """
[[package]]
name = "ancestor"
version = "1.0.0"
optional = false
groups = ["main"]
markers = "python_version < '3.13'"
dependencies = { parent = ">=1" }

[[package]]
name = "parent"
version = "1.0.0"
optional = false
groups = ["main"]
dependencies = { requests = ">=2" }

[[package]]
name = "requests"
version = "2.31.0"
optional = false
groups = ["main"]

[metadata]
lock-version = "2.1"
""",
        encoding="utf-8",
    )

    evidence = collect_python_evidence(tmp_path, "pip", "requests", "poetry.lock")

    assert evidence.instances == ()
    assert evidence.proof_capabilities == ()
    assert len(evidence.dependency_paths) == 1
    path = evidence.dependency_paths[0]
    assert [node.package_name for node in path.nodes] == [
        "<project>",
        "ancestor",
        "parent",
        "requests",
    ]
    assert path.edge_requirements == (">=1,<2", ">=1", ">=2")
    assert path.conditional
    assert any(
        "markers=python_version < '3.13'" in condition for condition in path.conditions if condition
    )
    assert "conditional dependency ancestry" in " ".join(evidence.issues)


def test_poetry_cycle_withholds_target_authority_and_preserves_context(
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.poetry]
name = "example"
version = "0.1.0"

[tool.poetry.dependencies]
python = "^3.12"
parent = ">=1,<2"
""",
        encoding="utf-8",
    )
    (tmp_path / "poetry.lock").write_text(
        """
[[package]]
name = "parent"
version = "1.0.0"
optional = false
groups = ["main"]
dependencies = { requests = ">=2" }

[[package]]
name = "requests"
version = "2.31.0"
optional = false
groups = ["main"]
dependencies = { parent = ">=1" }

[metadata]
lock-version = "2.1"
""",
        encoding="utf-8",
    )

    evidence = collect_python_evidence(tmp_path, "pip", "requests", "poetry.lock")

    assert evidence.instances == ()
    assert evidence.proof_capabilities == ()
    assert evidence.dependency_paths_truncated
    assert any(path.cycle_detected for path in evidence.dependency_paths)
    assert all(
        len(path.edge_requirements) == len(path.nodes) - 1 for path in evidence.dependency_paths
    )
    assert "target graph context was truncated" in " ".join(evidence.issues)


def test_poetry_pep621_only_project_is_positive_evidence(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "example"
version = "0.1.0"
dependencies = ["requests==2.31.0"]

[build-system]
requires = ["poetry-core>=2.0.0"]
build-backend = "poetry.core.masonry.api"
""",
        encoding="utf-8",
    )
    (tmp_path / "poetry.lock").write_text(
        """
[[package]]
name = "requests"
version = "2.31.0"
optional = false
groups = ["main"]

[metadata]
lock-version = "2.1"
python-versions = ">=3.12"
content-hash = "unverified"
""",
        encoding="utf-8",
    )

    evidence = collect_python_evidence(tmp_path, "pip", "requests", "poetry.lock")

    assert evidence.instances[0].version == "2.31.0"
    assert evidence.instances[0].relationship == "direct"
    assert evidence.lockfile_version == "2.1"


def test_poetry_bare_pep621_requirement_serializes_as_no_edge_requirement(
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "example"
version = "0.1.0"
dependencies = ["requests"]

[build-system]
requires = ["poetry-core>=2.0.0"]
build-backend = "poetry.core.masonry.api"
""",
        encoding="utf-8",
    )
    (tmp_path / "poetry.lock").write_text(
        """
[[package]]
name = "requests"
version = "2.31.0"
optional = false
groups = ["main"]

[metadata]
lock-version = "2.1"
""",
        encoding="utf-8",
    )

    evidence = collect_python_evidence(tmp_path, "pip", "requests", "poetry.lock")

    assert evidence.proof_capabilities == ("resolved_instances",)
    assert evidence.dependency_paths[0].edge_requirements == (None,)
    assert not evidence.dependency_paths_truncated


def test_poetry_lock_1_1_main_record_is_positive_evidence(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.poetry]
name = "example"
version = "0.1.0"

[tool.poetry.dependencies]
python = "^3.9"
h11 = "==0.13.0"
""",
        encoding="utf-8",
    )
    (tmp_path / "poetry.lock").write_text(
        """
[[package]]
name = "h11"
version = "0.13.0"
category = "main"
optional = false
python-versions = ">=3.6"

[metadata]
lock-version = "1.1"
python-versions = "^3.9"
content-hash = "unverified"
""",
        encoding="utf-8",
    )

    evidence = collect_python_evidence(tmp_path, "pip", "h11", "poetry.lock")

    assert evidence.instances[0].version == "0.13.0"
    assert evidence.instances[0].relationship == "direct"
    assert evidence.lockfile_version == "1.1"


def test_poetry_lock_1_1_marker_withholds_authority(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.poetry]
name = "example"
version = "0.1.0"

[tool.poetry.dependencies]
python = "^3.9"
h11 = "==0.13.0"
""",
        encoding="utf-8",
    )
    (tmp_path / "poetry.lock").write_text(
        """
[[package]]
name = "h11"
version = "0.13.0"
category = "main"
optional = false
marker = "python_version < '3.8'"

[metadata]
lock-version = "1.1"
python-versions = "^3.9"
content-hash = "unverified"
""",
        encoding="utf-8",
    )

    evidence = collect_python_evidence(tmp_path, "pip", "h11", "poetry.lock")

    assert evidence.instances == ()
    assert evidence.proof_capabilities == ()


@pytest.mark.parametrize(
    "extra_pyproject",
    (
        """
[project]
dependencies = ["requests>=2"]
""",
        """
[tool.poetry.group.dev.dependencies]
requests = "^2.31"
""",
    ),
)
def test_poetry_duplicate_or_unsupported_target_declarations_withhold_authority(
    extra_pyproject: str,
    tmp_path: Path,
) -> None:
    write_poetry_project(tmp_path, extra_pyproject=extra_pyproject)

    evidence = collect_python_evidence(
        tmp_path,
        "pip",
        "requests",
        "pyproject.toml",
    )

    assert evidence.instances == ()
    assert evidence.proof_capabilities == ()
