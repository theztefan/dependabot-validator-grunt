"""Deterministic positive-only pip requirements evidence."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from dependabot_validator_grunt.dependency_files import bounded_text
from dependabot_validator_grunt.models import (
    DependencyDeclaration,
    DependencyEvidence,
    DependencyInstance,
    DependencyProvenance,
    canonical_json,
)
from dependabot_validator_grunt.python_dependency_common import normalized_manifest_path

_INLINE_COMMENT = re.compile(r"\s+#")
_INCLUDE_DIRECTIVE = re.compile(
    r"^(?P<option>-r|--requirement|-c|--constraint)(?:\s+|=)(?P<target>\S+)$"
)
_INLINE_VIA = re.compile(r"\s+#\s*via(?:\s+(?P<target>.+))?\s*$", re.IGNORECASE)
_PIP_MAX_INCLUDE_DEPTH = 16
_PIP_MAX_FILES = 64
_PIP_MAX_PROCESSED_LINES = 100_000
_PIP_MAX_DECLARATIONS = 10_000
_PIP_MAX_EXACT_RECORDS = 10_000
_PIP_MAX_PROVENANCE_RECORDS = 10_000
_PIP_MAX_SERIALIZED_OUTPUT_BYTES = 2 * 1024 * 1024


def _selected_path(repository: Path, manifest_path: str) -> tuple[Path, str]:
    selected, normalized_path = normalized_manifest_path(repository, manifest_path)
    normalized = PurePosixPath(normalized_path)
    if normalized.suffix not in {".txt", ".in"}:
        raise ValueError("unsupported pip alert manifest path")
    return selected, normalized_path


def _requirement_text(line: str) -> str:
    match = _INLINE_COMMENT.search(line)
    return line[: match.start()].rstrip() if match is not None else line.strip()


def _exact_version(requirement: Requirement) -> Version | None:
    specifiers = tuple(requirement.specifier)
    if requirement.marker is not None or requirement.url is not None or len(specifiers) != 1:
        return None
    specifier = specifiers[0]
    if specifier.operator != "==" or "*" in specifier.version:
        return None
    try:
        return Version(specifier.version)
    except InvalidVersion:
        return None


def _included_requirement_path(
    repository: Path,
    *,
    source_path: str,
    target: str,
) -> tuple[Path, str]:
    if (
        not target
        or "\\" in target
        or "${" in target
        or target.startswith(("http://", "https://", "file:"))
        or target[0] in {'"', "'"}
        or target[-1] in {'"', "'"}
    ):
        raise ValueError("unsafe pip requirements include path")
    target_path = PurePosixPath(target)
    if target_path.is_absolute() or ".." in target_path.parts:
        raise ValueError("unsafe pip requirements include path")
    combined = PurePosixPath(source_path).parent / target_path
    return normalized_manifest_path(repository, combined.as_posix())


def collect_pip_evidence(
    repository: Path,
    package_name: str,
    manifest_path: str,
    *,
    max_dependency_file_bytes: int,
    excluded_paths: tuple[str, ...],
) -> DependencyEvidence:
    selected, normalized_path = _selected_path(repository, manifest_path)
    if normalized_path in excluded_paths:
        raise ValueError("selected Python dependency file was excluded from the snapshot")
    if not selected.is_file():
        raise ValueError("selected pip requirements file is missing")
    package_identity = canonicalize_name(package_name)
    declarations: list[DependencyDeclaration] = []
    exact_records: list[tuple[int, Version]] = []
    provenance: list[DependencyProvenance] = []
    manifest_paths: list[str] = []
    issues: set[str] = set()
    authority_blocked = False
    total_bytes = 0
    processed_lines = 0
    serialized_record_bytes = 0
    visited: set[tuple[str, bool]] = set()
    active_paths: set[str] = set()

    def charge_serialized_record(value: str) -> None:
        nonlocal serialized_record_bytes
        size = len(value.encode("utf-8"))
        if serialized_record_bytes + size > _PIP_MAX_SERIALIZED_OUTPUT_BYTES:
            raise ValueError("pip requirements serialized evidence exceeds the configured limit")
        serialized_record_bytes += size

    def add_issue(message: str) -> None:
        if message in issues:
            return
        charge_serialized_record(canonical_json(message))
        issues.add(message)

    def append_declaration(declaration: DependencyDeclaration) -> None:
        if len(declarations) >= _PIP_MAX_DECLARATIONS:
            raise ValueError("pip requirements declaration count exceeds the configured limit")
        charge_serialized_record(declaration.model_dump_json())
        declarations.append(declaration)

    def append_exact_record(line_number: int, version: Version) -> None:
        if len(exact_records) >= _PIP_MAX_EXACT_RECORDS:
            raise ValueError("pip requirements exact record count exceeds the configured limit")
        charge_serialized_record(canonical_json({"line": line_number, "version": str(version)}))
        exact_records.append((line_number, version))

    def append_provenance(record: DependencyProvenance) -> None:
        if len(provenance) >= _PIP_MAX_PROVENANCE_RECORDS:
            raise ValueError(
                "pip requirements provenance record count exceeds the configured limit"
            )
        charge_serialized_record(record.model_dump_json())
        provenance.append(record)

    add_issue("pip requirements support is positive-evidence only")

    def scan_file(
        path: Path,
        path_text: str,
        *,
        constraint: bool,
        depth: int,
    ) -> None:
        nonlocal authority_blocked, processed_lines, total_bytes
        if depth > _PIP_MAX_INCLUDE_DEPTH:
            raise ValueError("pip requirements include depth exceeds the configured limit")
        if path_text in active_paths:
            add_issue(f"pip requirements include cycle detected at {path_text}")
            return
        visit_key = (path_text, constraint)
        if visit_key in visited:
            return
        if path_text not in manifest_paths:
            if len(manifest_paths) >= _PIP_MAX_FILES:
                raise ValueError("pip requirements file count exceeds the configured limit")
            manifest_paths.append(path_text)
        if path_text in excluded_paths:
            raise ValueError("included Python dependency file was excluded from the snapshot")
        if not path.is_file():
            raise ValueError("included pip requirements file is missing")
        try:
            text = bounded_text(path, max_dependency_file_bytes)
        except OSError as error:
            raise ValueError("included pip requirements file cannot be read") from error
        total_bytes += len(text.encode("utf-8"))
        if total_bytes > max_dependency_file_bytes:
            raise ValueError("pip requirements files exceed the configured byte limit")
        visited.add(visit_key)
        active_paths.add(path_text)
        skipping_continuation = False
        via_block = False
        try:
            for line_number, raw_line in enumerate(text.splitlines(), start=1):
                processed_lines += 1
                if processed_lines > _PIP_MAX_PROCESSED_LINES:
                    raise ValueError(
                        "pip requirements processed line count exceeds the configured limit"
                    )
                stripped = raw_line.strip()
                if skipping_continuation:
                    skipping_continuation = stripped.endswith("\\")
                    continue
                if not stripped:
                    via_block = False
                    continue
                if stripped.startswith("#"):
                    comment = stripped[1:].strip()
                    if comment.casefold() == "via":
                        via_block = True
                        continue
                    if via_block and comment:
                        append_provenance(
                            DependencyProvenance(
                                kind="pip_compile_via",
                                source_path=path_text,
                                line=line_number,
                                target=comment,
                            )
                        )
                        continue
                    via_block = False
                    continue
                via_match = _INLINE_VIA.search(stripped)
                if via_match is not None:
                    via_target = via_match.group("target")
                    if via_target:
                        append_provenance(
                            DependencyProvenance(
                                kind="pip_compile_via",
                                source_path=path_text,
                                line=line_number,
                                target=via_target.strip(),
                            )
                        )
                        via_block = False
                    else:
                        via_block = True
                else:
                    via_block = False
                requirement_text = _requirement_text(stripped)
                include_match = _INCLUDE_DIRECTIVE.fullmatch(requirement_text)
                if include_match is not None:
                    authority_blocked = True
                    option = include_match.group("option")
                    include_constraint = option in {"-c", "--constraint"}
                    include_path, include_text = _included_requirement_path(
                        repository,
                        source_path=path_text,
                        target=include_match.group("target"),
                    )
                    append_provenance(
                        DependencyProvenance(
                            kind=(
                                "constraint_include"
                                if include_constraint
                                else "requirement_include"
                            ),
                            source_path=path_text,
                            line=line_number,
                            target=include_text,
                        )
                    )
                    add_issue("requirements includes and constraints are non-authoritative")
                    scan_file(
                        include_path,
                        include_text,
                        constraint=constraint or include_constraint,
                        depth=depth + 1,
                    )
                    continue
                if requirement_text.startswith(("-r", "--requirement", "-c", "--constraint")):
                    raise ValueError("malformed pip requirements include directive")
                if stripped.endswith("\\"):
                    authority_blocked = True
                    add_issue("line continuations are unsupported for positive evidence")
                    skipping_continuation = True
                    continue
                if "${" in stripped:
                    authority_blocked = True
                    add_issue("environment-variable requirements are unsupported")
                    continue
                if stripped.startswith(("-e ", "--editable ")):
                    authority_blocked = True
                    add_issue("editable requirements are unsupported")
                    continue
                if stripped.startswith("-"):
                    source_options = (
                        "-i",
                        "--index-url",
                        "--extra-index-url",
                        "--no-index",
                        "-f",
                        "--find-links",
                    )
                    if any(
                        stripped == option
                        or stripped.startswith(f"{option} ")
                        or stripped.startswith(f"{option}=")
                        for option in source_options
                    ):
                        add_issue("requirements source options prevent public PyPI authority")
                    else:
                        add_issue("requirements-file options are unsupported")
                    authority_blocked = True
                    continue
                if " --" in requirement_text:
                    authority_blocked = True
                    add_issue("per-requirement options and hashes are unsupported")
                    continue
                try:
                    requirement = Requirement(requirement_text)
                except InvalidRequirement:
                    authority_blocked = True
                    add_issue(f"unsupported requirement syntax at {path_text}:{line_number}")
                    continue
                if canonicalize_name(requirement.name) != package_identity:
                    continue
                exact_version = _exact_version(requirement)
                if not constraint:
                    append_declaration(
                        DependencyDeclaration(
                            manifest_path=path_text,
                            name=requirement.name,
                            spec=str(requirement.specifier),
                            relationship="direct",
                            exact_version=(
                                str(exact_version) if exact_version is not None else None
                            ),
                            marker=(
                                str(requirement.marker) if requirement.marker is not None else None
                            ),
                            source_kind=("url" if requirement.url is not None else "registry"),
                            source_locator=requirement.url,
                        )
                    )
                else:
                    add_issue("matching pip constraint is non-authoritative")
                if exact_version is None:
                    authority_blocked = True
                    add_issue(
                        f"matching requirement at {path_text}:{line_number} "
                        "is not an exact unmarked pin"
                    )
                elif not constraint and path_text == normalized_path:
                    append_exact_record(line_number, exact_version)
        finally:
            active_paths.remove(path_text)

    scan_file(selected, normalized_path, constraint=False, depth=0)

    versions = {version for _, version in exact_records}
    instances: tuple[DependencyInstance, ...] = ()
    if authority_blocked:
        add_issue("unsupported requirements syntax prevents positive authority")
    elif len(versions) > 1:
        add_issue("matching pip requirements contain conflicting exact pins")
    elif exact_records:
        line_number, version = exact_records[0]
        if len(exact_records) > 1:
            add_issue("matching pip requirements contain duplicate exact pins")
        instances = (
            DependencyInstance(
                path=f"{normalized_path}:{line_number}",
                version=str(version),
                relationship="direct",
                source_kind="registry",
                source_locator="https://pypi.org/simple",
            ),
        )

    evidence = DependencyEvidence(
        ecosystem="pip",
        package_manager="pip",
        version_scheme="pep440",
        lockfile_version=None,
        lockfile_path=None,
        proof_capabilities=("resolved_instances",) if instances else (),
        package_name=package_name,
        instances=instances,
        manifest_paths=tuple(manifest_paths),
        completeness="partial",
        declarations=tuple(declarations),
        dependency_provenance=tuple(provenance),
        issues=tuple(sorted(issues)),
    )
    if len(evidence.model_dump_json().encode("utf-8")) > _PIP_MAX_SERIALIZED_OUTPUT_BYTES:
        raise ValueError("pip requirements serialized evidence exceeds the configured limit")
    return evidence
