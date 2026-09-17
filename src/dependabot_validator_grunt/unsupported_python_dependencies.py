"""Declaration-only evidence for unsupported Python manifests."""

from __future__ import annotations

import ast
import configparser
from pathlib import Path, PurePosixPath
from typing import Literal, cast

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from pydantic import ValidationError

from dependabot_validator_grunt.dependency_files import (
    bounded_json_object,
    bounded_text,
    bounded_toml_object,
)
from dependabot_validator_grunt.models import (
    DependencyDeclaration,
    DependencyEvidence,
    Ecosystem,
)
from dependabot_validator_grunt.poetry_dependencies import collect_poetry_declarations
from dependabot_validator_grunt.python_dependency_common import (
    OBJECT_ADAPTER,
    STRING_LIST_ADAPTER,
    normalized_manifest_path,
)
from dependabot_validator_grunt.uv_dependencies import collect_uv_declarations

KNOWN_PYTHON_MANIFESTS = {
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "Pipfile",
    "Pipfile.lock",
}


def collect_unsupported_python_evidence(
    repository: Path,
    ecosystem: Ecosystem,
    package_name: str,
    manifest_path: str,
    *,
    max_dependency_file_bytes: int,
    excluded_paths: tuple[str, ...],
) -> DependencyEvidence:
    selected, normalized_path = normalized_manifest_path(repository, manifest_path)
    if PurePosixPath(normalized_path).name not in KNOWN_PYTHON_MANIFESTS:
        raise ValueError("unsupported pip alert manifest path")
    if normalized_path in excluded_paths:
        raise ValueError("selected Python dependency file was excluded from the snapshot")
    if not selected.is_file():
        raise ValueError("selected Python dependency file is missing")
    declarations: tuple[DependencyDeclaration, ...] = ()
    manifest_name = PurePosixPath(normalized_path).name
    package_identity = canonicalize_name(package_name)
    if manifest_name == "pyproject.toml":
        pyproject = bounded_toml_object(selected, max_dependency_file_bytes)
        tool = OBJECT_ADAPTER.validate_python(pyproject.get("tool", {}))
        if OBJECT_ADAPTER.validate_python(tool.get("poetry", {})):
            declarations, _ = collect_poetry_declarations(
                pyproject,
                package_name=package_name,
                manifest_path=normalized_path,
            )
        elif OBJECT_ADAPTER.validate_python(pyproject.get("project", {})):
            declarations, _ = collect_uv_declarations(
                pyproject,
                package_name=package_name,
                manifest_path=normalized_path,
            )
    elif manifest_name == "Pipfile":
        pipfile = bounded_toml_object(selected, max_dependency_file_bytes)
        found: list[DependencyDeclaration] = []
        for section, relationship in (("packages", "direct"), ("dev-packages", "development")):
            dependencies = OBJECT_ADAPTER.validate_python(pipfile.get(section, {}))
            for name, raw_spec in dependencies.items():
                if canonicalize_name(name) != package_identity:
                    continue
                spec = raw_spec if isinstance(raw_spec, str) else ""
                if isinstance(raw_spec, dict):
                    value = OBJECT_ADAPTER.validate_python(raw_spec).get("version")
                    spec = value if isinstance(value, str) else ""
                found.append(
                    DependencyDeclaration(
                        manifest_path=normalized_path,
                        name=name,
                        spec=spec,
                        relationship=cast(Literal["direct", "development"], relationship),
                    )
                )
        declarations = tuple(found)
    elif manifest_name == "Pipfile.lock":
        lock = bounded_json_object(selected, max_dependency_file_bytes)
        found = []
        for section, relationship in (("default", "direct"), ("develop", "development")):
            dependencies = OBJECT_ADAPTER.validate_python(lock.get(section, {}))
            for name, raw_spec in dependencies.items():
                if canonicalize_name(name) != package_identity:
                    continue
                dependency = OBJECT_ADAPTER.validate_python(raw_spec)
                raw_version = dependency.get("version")
                raw_marker = dependency.get("markers")
                found.append(
                    DependencyDeclaration(
                        manifest_path=normalized_path,
                        name=name,
                        spec=raw_version if isinstance(raw_version, str) else "",
                        relationship=cast(Literal["direct", "development"], relationship),
                        marker=raw_marker if isinstance(raw_marker, str) else None,
                    )
                )
        declarations = tuple(found)
    elif manifest_name == "setup.py":
        text = bounded_text(selected, max_dependency_file_bytes)
        try:
            tree = ast.parse(text, filename=normalized_path)
        except SyntaxError as error:
            raise ValueError("selected setup.py is malformed") from error
        found = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not (
                isinstance(node.func, ast.Name) and node.func.id == "setup"
            ):
                continue
            for keyword in node.keywords:
                if keyword.arg not in {"install_requires", "tests_require", "setup_requires"}:
                    continue
                try:
                    raw_values = ast.literal_eval(keyword.value)
                except (ValueError, TypeError):
                    continue
                try:
                    values = STRING_LIST_ADAPTER.validate_python(raw_values)
                except ValidationError:
                    continue
                for value in values:
                    try:
                        requirement = Requirement(value)
                    except InvalidRequirement:
                        continue
                    if canonicalize_name(requirement.name) != package_identity:
                        continue
                    found.append(
                        DependencyDeclaration(
                            manifest_path=normalized_path,
                            name=requirement.name,
                            spec=str(requirement.specifier),
                            relationship=(
                                "direct" if keyword.arg == "install_requires" else "development"
                            ),
                            marker=(
                                str(requirement.marker) if requirement.marker is not None else None
                            ),
                        )
                    )
        declarations = tuple(found)
    elif manifest_name == "setup.cfg":
        text = bounded_text(selected, max_dependency_file_bytes)
        parser = configparser.ConfigParser(interpolation=None)
        try:
            parser.read_string(text)
        except configparser.Error as error:
            raise ValueError("selected setup.cfg is malformed") from error
        found = []
        for section, option, relationship in (
            ("options", "install_requires", "direct"),
            ("options", "setup_requires", "development"),
        ):
            if not parser.has_option(section, option):
                continue
            for value in parser.get(section, option).splitlines():
                value = value.strip()
                if not value:
                    continue
                try:
                    requirement = Requirement(value)
                except InvalidRequirement:
                    continue
                if canonicalize_name(requirement.name) == package_identity:
                    found.append(
                        DependencyDeclaration(
                            manifest_path=normalized_path,
                            name=requirement.name,
                            spec=str(requirement.specifier),
                            relationship=cast(
                                Literal["direct", "development"],
                                relationship,
                            ),
                            marker=(
                                str(requirement.marker) if requirement.marker is not None else None
                            ),
                        )
                    )
        declarations = tuple(found)
    return DependencyEvidence(
        ecosystem=ecosystem,
        package_manager="pip",
        version_scheme="pep440",
        lockfile_version=None,
        lockfile_path=None,
        proof_capabilities=(),
        package_name=package_name,
        instances=(),
        manifest_paths=(normalized_path,),
        completeness="unsupported",
        declarations=declarations,
        issues=(f"selected Python manifest has partial declaration-only support: {manifest_name}",),
    )
