"""Explicit dispatch for deterministic Python dependency evidence."""

from __future__ import annotations

from pathlib import Path, PurePath, PurePosixPath

from dependabot_validator_grunt.models import DependencyEvidence, Ecosystem
from dependabot_validator_grunt.pip_dependencies import collect_pip_evidence
from dependabot_validator_grunt.poetry_dependencies import collect_poetry_evidence
from dependabot_validator_grunt.python_dependency_common import (
    DEFAULT_MAX_DEPENDENCY_PATH_BYTES,
    DEFAULT_MAX_DEPENDENCY_PATH_DEPTH,
    DEFAULT_MAX_DEPENDENCY_PATHS,
    normalized_manifest_path,
)
from dependabot_validator_grunt.unsupported_python_dependencies import (
    collect_unsupported_python_evidence,
)
from dependabot_validator_grunt.uv_dependencies import collect_uv_evidence


def collect_python_evidence(
    repository: Path,
    ecosystem: Ecosystem,
    package_name: str,
    manifest_path: str,
    *,
    max_dependency_file_bytes: int = 32 * 1024 * 1024,
    excluded_paths: tuple[str, ...] = (),
    max_dependency_paths: int = DEFAULT_MAX_DEPENDENCY_PATHS,
    max_dependency_path_depth: int = DEFAULT_MAX_DEPENDENCY_PATH_DEPTH,
    max_dependency_path_bytes: int = DEFAULT_MAX_DEPENDENCY_PATH_BYTES,
) -> DependencyEvidence:
    """Collect supported Python dependency evidence for one selected project."""
    normalized = PurePosixPath(PurePath(manifest_path).as_posix())
    if ecosystem not in {"pip", "uv"}:
        raise ValueError("unsupported Python ecosystem")
    if normalized.name == "uv.lock" or ecosystem == "uv":
        return collect_uv_evidence(
            repository,
            ecosystem,
            package_name,
            manifest_path,
            max_dependency_file_bytes=max_dependency_file_bytes,
            excluded_paths=excluded_paths,
            max_dependency_paths=max_dependency_paths,
            max_dependency_path_depth=max_dependency_path_depth,
            max_dependency_path_bytes=max_dependency_path_bytes,
        )
    if normalized.name == "poetry.lock":
        return collect_poetry_evidence(
            repository,
            package_name,
            manifest_path,
            max_dependency_file_bytes=max_dependency_file_bytes,
            excluded_paths=excluded_paths,
            max_dependency_paths=max_dependency_paths,
            max_dependency_path_depth=max_dependency_path_depth,
            max_dependency_path_bytes=max_dependency_path_bytes,
        )
    if normalized.name == "pyproject.toml":
        selected, _ = normalized_manifest_path(repository, manifest_path)
        poetry_lock = selected.parent / "poetry.lock"
        uv_lock = selected.parent / "uv.lock"
        if poetry_lock.is_file() and uv_lock.is_file():
            raise ValueError("selected Python project has ambiguous adjacent lockfiles")
        if uv_lock.is_file():
            return collect_uv_evidence(
                repository,
                ecosystem,
                package_name,
                manifest_path,
                max_dependency_file_bytes=max_dependency_file_bytes,
                excluded_paths=excluded_paths,
                max_dependency_paths=max_dependency_paths,
                max_dependency_path_depth=max_dependency_path_depth,
                max_dependency_path_bytes=max_dependency_path_bytes,
            )
        if poetry_lock.is_file():
            return collect_poetry_evidence(
                repository,
                package_name,
                manifest_path,
                max_dependency_file_bytes=max_dependency_file_bytes,
                excluded_paths=excluded_paths,
                max_dependency_paths=max_dependency_paths,
                max_dependency_path_depth=max_dependency_path_depth,
                max_dependency_path_bytes=max_dependency_path_bytes,
            )
        return collect_unsupported_python_evidence(
            repository,
            ecosystem,
            package_name,
            manifest_path,
            max_dependency_file_bytes=max_dependency_file_bytes,
            excluded_paths=excluded_paths,
        )
    if normalized.suffix in {".txt", ".in"}:
        return collect_pip_evidence(
            repository,
            package_name,
            manifest_path,
            max_dependency_file_bytes=max_dependency_file_bytes,
            excluded_paths=excluded_paths,
        )
    return collect_unsupported_python_evidence(
        repository,
        ecosystem,
        package_name,
        manifest_path,
        max_dependency_file_bytes=max_dependency_file_bytes,
        excluded_paths=excluded_paths,
    )
