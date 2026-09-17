"""Unsupported Python manifest evidence tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from dependabot_validator_grunt.python_dependencies import collect_python_evidence
from dependabot_validator_grunt.unsupported_python_dependencies import (
    collect_unsupported_python_evidence,
)


@pytest.mark.parametrize(
    ("manifest_name", "content"),
    (
        (
            "pyproject.toml",
            '[project]\nname = "example"\nversion = "0.1.0"\ndependencies = ["requests>=2"]\n',
        ),
        ("Pipfile", '[packages]\nrequests = ">=2"\n'),
        (
            "Pipfile.lock",
            '{"default":{"requests":{"version":"==2.31.0"}},"develop":{}}',
        ),
        ("setup.py", 'from setuptools import setup\nsetup(install_requires=["requests>=2"])\n'),
        ("setup.cfg", "[options]\ninstall_requires =\n    requests>=2\n"),
    ),
)
def test_known_unsupported_python_manifest_returns_declaration_evidence(
    manifest_name: str,
    content: str,
    tmp_path: Path,
) -> None:
    (tmp_path / manifest_name).write_text(content, encoding="utf-8")

    evidence = collect_unsupported_python_evidence(
        tmp_path,
        "pip",
        "requests",
        manifest_name,
        max_dependency_file_bytes=32 * 1024 * 1024,
        excluded_paths=(),
    )

    assert evidence.completeness == "unsupported"
    assert evidence.proof_capabilities == ()
    assert evidence.declarations[0].name.casefold() == "requests"


@pytest.mark.parametrize(
    "content",
    (
        '[tool.poetry]\nname = "example"\nversion = "0.1.0"\n'
        '[tool.poetry.dependencies]\npython = "^3.12"\nrequests = "^2"\n',
        '[build-system]\nrequires = ["setuptools"]\nbuild-backend = "setuptools.build_meta"\n',
    ),
)
def test_other_readable_pyprojects_return_unsupported_evidence(
    content: str,
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text(content, encoding="utf-8")

    evidence = collect_python_evidence(
        tmp_path,
        "pip",
        "requests",
        "pyproject.toml",
    )

    assert evidence.completeness == "unsupported"
    assert evidence.proof_capabilities == ()


@pytest.mark.parametrize(
    ("manifest_name", "content", "message"),
    (
        ("setup.py", "setup(\n", "setup.py is malformed"),
        ("setup.cfg", "not a section\n", "setup.cfg is malformed"),
    ),
)
def test_malformed_setup_metadata_is_a_collection_error(
    manifest_name: str,
    content: str,
    message: str,
    tmp_path: Path,
) -> None:
    (tmp_path / manifest_name).write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        collect_python_evidence(
            tmp_path,
            "pip",
            "requests",
            manifest_name,
        )
