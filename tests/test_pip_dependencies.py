"""pip requirements evidence tests."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from python_dependency_test_support import (
    CASES,
)

import dependabot_validator_grunt.pip_dependencies as pip_dependencies_module
from dependabot_validator_grunt.pip_dependencies import collect_pip_evidence
from dependabot_validator_grunt.python_dependencies import collect_python_evidence
from dependabot_validator_grunt.workflow import (
    WorkflowError,
    triage_offline_fixture,
)


def test_pip_exact_pin_is_positive_partial_evidence(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text(
        "Requests==2.31.0\n",
        encoding="utf-8",
    )

    evidence = collect_pip_evidence(
        tmp_path,
        "requests",
        "requirements.txt",
        max_dependency_file_bytes=32 * 1024 * 1024,
        excluded_paths=(),
    )

    assert evidence.ecosystem == "pip"
    assert evidence.package_manager == "pip"
    assert evidence.package_identity == "requests"
    assert evidence.proof_capabilities == ("resolved_instances",)
    assert evidence.completeness == "partial"
    assert [(instance.version, instance.relationship) for instance in evidence.instances] == [
        ("2.31.0", "direct")
    ]
    assert evidence.instances[0].source_kind == "registry"
    assert evidence.instances[0].source_locator == "https://pypi.org/simple"


@pytest.mark.parametrize(
    "requirement",
    (
        'requests==2.31.0; python_version < "3.12"',
        "requests>=2",
        "requests==2.*",
        "requests @ https://example.com/requests.whl",
        "-e git+https://example.com/requests.git",
        "requests==2.31.0 --hash=sha256:abc",
    ),
)
def test_pip_unsupported_records_cannot_authorize_positive_evidence(
    requirement: str,
    tmp_path: Path,
) -> None:
    (tmp_path / "requirements.txt").write_text(f"{requirement}\n", encoding="utf-8")

    evidence = collect_python_evidence(
        tmp_path,
        "pip",
        "requests",
        "requirements.txt",
    )

    assert evidence.instances == ()
    assert evidence.proof_capabilities == ()
    assert evidence.issues


def test_pip_conflicting_pins_cannot_authorize_positive_evidence(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text(
        "requests==2.31.0\nrequests==2.32.0\n",
        encoding="utf-8",
    )

    evidence = collect_python_evidence(
        tmp_path,
        "pip",
        "requests",
        "requirements.txt",
    )

    assert evidence.instances == ()
    assert evidence.proof_capabilities == ()
    assert "matching pip requirements contain conflicting exact pins" in evidence.issues


@pytest.mark.parametrize(
    "unsupported_match",
    (
        "requests>=2",
        'requests==2.31.0; python_version < "3.12"',
        "requests @ https://example.com/requests.whl",
    ),
)
def test_pip_mixed_unsupported_target_records_block_positive_evidence(
    unsupported_match: str,
    tmp_path: Path,
) -> None:
    (tmp_path / "requirements.txt").write_text(
        f"requests==2.31.0\n{unsupported_match}\n",
        encoding="utf-8",
    )

    evidence = collect_python_evidence(
        tmp_path,
        "pip",
        "requests",
        "requirements.txt",
    )

    assert evidence.instances == ()
    assert evidence.proof_capabilities == ()


def test_pip_records_recursive_include_constraint_and_cycle_provenance(
    tmp_path: Path,
) -> None:
    (tmp_path / "requirements.txt").write_text(
        "-r base.in\n-c constraints.txt\n",
        encoding="utf-8",
    )
    (tmp_path / "base.in").write_text("requests==2.31.0\n", encoding="utf-8")
    (tmp_path / "constraints.txt").write_text(
        "-c requirements.txt\nrequests==2.31.0\n",
        encoding="utf-8",
    )

    evidence = collect_python_evidence(tmp_path, "pip", "requests", "requirements.txt")

    assert evidence.instances == ()
    assert evidence.proof_capabilities == ()
    assert evidence.manifest_paths == (
        "requirements.txt",
        "base.in",
        "constraints.txt",
    )
    assert [record.kind for record in evidence.dependency_provenance] == [
        "requirement_include",
        "constraint_include",
        "constraint_include",
    ]
    assert any("include cycle detected" in issue for issue in evidence.issues)
    assert evidence.dependency_consumers == ()
    assert evidence.dependency_paths == ()


@pytest.mark.parametrize("directive", ("-r missing.in", "-c missing.txt"))
def test_pip_missing_included_files_fail_closed(directive: str, tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text(f"{directive}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="included pip requirements file is missing"):
        collect_python_evidence(tmp_path, "pip", "requests", "requirements.txt")


def test_pip_include_path_escape_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text(
        "-r ../outside-repository.in\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsafe pip requirements include path"):
        collect_python_evidence(tmp_path, "pip", "requests", "requirements.txt")


def test_pip_compile_via_is_advisory_provenance_only(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text(
        "requests==2.31.0  # via httpx\n",
        encoding="utf-8",
    )

    evidence = collect_python_evidence(tmp_path, "pip", "requests", "requirements.txt")

    assert evidence.proof_capabilities == ("resolved_instances",)
    assert evidence.instances[0].version == "2.31.0"
    assert [record.model_dump() for record in evidence.dependency_provenance] == [
        {
            "kind": "pip_compile_via",
            "source_path": "requirements.txt",
            "line": 1,
            "target": "httpx",
            "authoritative": False,
        }
    ]
    assert evidence.dependency_consumers == ()
    assert evidence.dependency_paths == ()


def test_pip_equivalent_pep440_pins_are_not_conflicts(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text(
        "requests==1.0\nrequests==1.0.0\n",
        encoding="utf-8",
    )

    evidence = collect_python_evidence(
        tmp_path,
        "pip",
        "requests",
        "requirements.txt",
    )

    assert evidence.proof_capabilities == ("resolved_instances",)
    assert len(evidence.instances) == 1


@pytest.mark.parametrize(
    ("limit_name", "requirements", "message"),
    (
        (
            "_PIP_MAX_PROCESSED_LINES",
            "requests==2.31.0\nother==1.0.0\n",
            "processed line count",
        ),
        (
            "_PIP_MAX_DECLARATIONS",
            "requests==2.31.0\nrequests==2.31.0\n",
            "declaration count",
        ),
        (
            "_PIP_MAX_EXACT_RECORDS",
            "requests==2.31.0\nrequests==2.31.0\n",
            "exact record count",
        ),
        (
            "_PIP_MAX_PROVENANCE_RECORDS",
            "requests==2.31.0  # via parent-a\nrequests==2.31.0  # via parent-b\n",
            "provenance record count",
        ),
    ),
)
def test_pip_requirements_record_and_line_bounds_fail_closed(
    limit_name: str,
    requirements: str,
    message: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(pip_dependencies_module, limit_name, 1)
    (tmp_path / "requirements.txt").write_text(requirements, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        collect_python_evidence(tmp_path, "pip", "requests", "requirements.txt")


def test_pip_requirements_serialized_output_bound_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        pip_dependencies_module,
        "_PIP_MAX_SERIALIZED_OUTPUT_BYTES",
        256,
    )
    (tmp_path / "requirements.txt").write_text(
        f"requests==2.31.0  # via {'parent-' * 40}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="serialized evidence"):
        collect_python_evidence(tmp_path, "pip", "requests", "requirements.txt")


async def test_pip_requirements_bound_failure_is_dependency_evidence_stage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case = tmp_path / "case"
    shutil.copytree(CASES / "python-pip-compile-provenance", case)
    monkeypatch.setattr(pip_dependencies_module, "_PIP_MAX_PROCESSED_LINES", 1)

    with pytest.raises(WorkflowError) as raised:
        await triage_offline_fixture(case, tmp_path / "out")

    assert raised.value.exit_code == 5
    assert raised.value.stage == "dependency_evidence"


@pytest.mark.parametrize(
    "source_option",
    (
        "--index-url https://example.com/simple",
        "--index-url=https://example.com/simple",
        "--extra-index-url https://example.com/simple",
        "--extra-index-url=https://example.com/simple",
        "--no-index",
        "--find-links ./wheels",
        "--find-links=./wheels",
        "--trusted-host example.com",
        "not a valid requirement !!!",
    ),
)
def test_pip_source_options_block_public_pypi_authority(
    source_option: str,
    tmp_path: Path,
) -> None:
    (tmp_path / "requirements.txt").write_text(
        f"{source_option}\nrequests==2.31.0\n",
        encoding="utf-8",
    )

    evidence = collect_python_evidence(
        tmp_path,
        "pip",
        "requests",
        "requirements.txt",
    )

    assert evidence.instances == ()
    assert evidence.proof_capabilities == ()


@pytest.mark.parametrize("manifest_path", ("../requirements.txt", "pyproject.toml"))
def test_pip_rejects_unsafe_or_unsupported_selected_paths(
    manifest_path: str,
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError):
        collect_python_evidence(tmp_path, "pip", "requests", manifest_path)
