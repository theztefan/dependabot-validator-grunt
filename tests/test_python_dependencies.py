"""Python dependency facade dispatch tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest
from python_dependency_test_support import (
    write_poetry_project,
    write_uv_project,
)

import dependabot_validator_grunt.python_dependencies as python_dependencies_module
from dependabot_validator_grunt.python_dependencies import collect_python_evidence


@pytest.mark.parametrize("manifest_path", ("uv.lock", "pyproject.toml"))
def test_pip_reported_uv_project_preserves_alert_ecosystem(
    manifest_path: str,
    tmp_path: Path,
) -> None:
    write_uv_project(tmp_path)

    evidence = collect_python_evidence(
        tmp_path,
        "pip",
        "requests",
        manifest_path,
    )

    assert evidence.ecosystem == "pip"
    assert evidence.package_manager == "uv"
    assert evidence.instances[0].relationship == "direct"


def test_facade_dispatches_pip_requirements(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "requirements.txt").write_text("requests==2.31.0\n", encoding="utf-8")
    collector = Mock(wraps=python_dependencies_module.collect_pip_evidence)
    monkeypatch.setattr(python_dependencies_module, "collect_pip_evidence", collector)

    evidence = collect_python_evidence(tmp_path, "pip", "requests", "requirements.txt")

    collector.assert_called_once()
    assert evidence.package_manager == "pip"


def test_facade_dispatches_poetry_project(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    write_poetry_project(tmp_path)
    collector = Mock(wraps=python_dependencies_module.collect_poetry_evidence)
    monkeypatch.setattr(python_dependencies_module, "collect_poetry_evidence", collector)

    evidence = collect_python_evidence(tmp_path, "pip", "requests", "pyproject.toml")

    collector.assert_called_once()
    assert evidence.package_manager == "poetry"


def test_facade_dispatches_uv_project(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    write_uv_project(tmp_path)
    collector = Mock(wraps=python_dependencies_module.collect_uv_evidence)
    monkeypatch.setattr(python_dependencies_module, "collect_uv_evidence", collector)

    evidence = collect_python_evidence(tmp_path, "uv", "requests", "uv.lock")

    collector.assert_called_once()
    assert evidence.package_manager == "uv"


def test_facade_dispatches_unsupported_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "setup.cfg").write_text(
        "[options]\ninstall_requires =\n    requests>=2\n",
        encoding="utf-8",
    )
    collector = Mock(wraps=python_dependencies_module.collect_unsupported_python_evidence)
    monkeypatch.setattr(
        python_dependencies_module,
        "collect_unsupported_python_evidence",
        collector,
    )

    evidence = collect_python_evidence(tmp_path, "pip", "requests", "setup.cfg")

    collector.assert_called_once()
    assert evidence.completeness == "unsupported"
