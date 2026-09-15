"""Deterministic npm lockfile and SemVer evidence."""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePath, PurePosixPath
from typing import Literal, cast
from urllib.parse import urlparse

from pydantic import TypeAdapter, ValidationError

from dependabot_validator_grunt.dependency_graph import project_target
from dependabot_validator_grunt.models import (
    NpmDeclaration,
    NpmEvidence,
    NpmInstance,
    validate_safe_identifier,
)
from dependabot_validator_grunt.pnpm import parse_pnpm_v9
from dependabot_validator_grunt.yarn import parse_yarn_classic

SEMVER = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<pre>[0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$"
)
COMPARATOR = re.compile(r"^(<=|>=|<|>|=)?\s*(\S+)$")
DEPENDENCY_SECTIONS: dict[
    str,
    Literal["direct", "development", "optional", "peer"],
] = {
    "dependencies": "direct",
    "devDependencies": "development",
    "optionalDependencies": "optional",
    "peerDependencies": "peer",
}


def _bounded_text(path: Path, max_bytes: int) -> str:
    if path.is_symlink():
        raise ValueError("dependency file symlinks are denied")
    before = path.stat()
    with path.open("rb") as file:
        data = file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("dependency file exceeds the configured byte limit")
    after = path.stat()
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise ValueError("dependency file changed while it was read")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("dependency file is not valid UTF-8") from error


def _bounded_json_object(path: Path, max_bytes: int) -> dict[str, object]:
    decoded = _bounded_text(path, max_bytes)
    try:
        raw = json.loads(decoded)
    except json.JSONDecodeError as error:
        raise ValueError("dependency file contains malformed JSON") from error
    return TypeAdapter(dict[str, object]).validate_python(raw)


def _project_paths(
    repository: Path,
    manifest_path: str,
) -> tuple[Path, Path, str, Literal["npm", "yarn-classic", "pnpm"]]:
    normalized = PurePosixPath(PurePath(manifest_path).as_posix())
    supported_names = {"package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"}
    if (
        normalized.is_absolute()
        or ".." in normalized.parts
        or normalized.name not in supported_names
    ):
        raise ValueError("unsupported npm alert manifest path")
    project_relative = normalized.parent
    project = repository.joinpath(*project_relative.parts)
    resolved_repository = repository.resolve(strict=True)
    resolved_project = project.resolve(strict=False)
    if (
        resolved_project != resolved_repository
        and resolved_repository not in resolved_project.parents
    ):
        raise ValueError("npm project path escapes the repository snapshot")
    if any(
        repository.joinpath(*normalized.parts[:index]).is_symlink()
        for index in range(1, len(normalized.parts))
    ):
        raise ValueError("npm project path contains a symlink")
    prefix = "" if project_relative == PurePosixPath(".") else f"{project_relative.as_posix()}/"
    if normalized.name == "package.json":
        candidates = tuple(
            path
            for path in (
                project / "package-lock.json",
                project / "yarn.lock",
                project / "pnpm-lock.yaml",
            )
            if path.exists()
        )
        if len(candidates) > 1:
            raise ValueError("multiple npm ecosystem lockfiles match the selected manifest")
        lock_path = candidates[0] if candidates else project / "package-lock.json"
    else:
        lock_path = project / normalized.name
    manager = cast(
        Literal["npm", "yarn-classic", "pnpm"],
        {
            "package-lock.json": "npm",
            "yarn.lock": "yarn-classic",
            "pnpm-lock.yaml": "pnpm",
        }[lock_path.name],
    )
    return project / "package.json", lock_path, prefix, manager


def _alias_target(spec: str) -> str | None:
    if not spec.startswith("npm:"):
        return None
    body = spec.removeprefix("npm:")
    if body.startswith("@"):
        slash = body.find("/")
        separator = body.find("@", slash + 1) if slash >= 0 else -1
    else:
        separator = body.find("@")
    target = body if separator < 0 else body[:separator]
    return validate_safe_identifier(target)


def _manifest_declarations(
    package_json: dict[str, object],
    *,
    package_name: str,
    manifest_path: str,
) -> tuple[NpmDeclaration, ...]:
    adapter = TypeAdapter(dict[str, object])
    declarations: list[NpmDeclaration] = []
    for section, relationship in DEPENDENCY_SECTIONS.items():
        mapping = adapter.validate_python(package_json.get(section, {}))
        for name, raw_spec in mapping.items():
            if not isinstance(raw_spec, str):
                raise ValueError(f"npm dependency declaration is invalid: {section}")
            alias_target = _alias_target(raw_spec)
            if name != package_name and alias_target != package_name:
                continue
            declarations.append(
                NpmDeclaration(
                    manifest_path=manifest_path,
                    name=name,
                    spec=raw_spec,
                    relationship=relationship,
                    alias_target=alias_target,
                    exact_version=raw_spec if SEMVER.fullmatch(raw_spec) else None,
                )
            )
    return tuple(declarations)


def _version_key(value: str) -> tuple[int, int, int, tuple[tuple[int, int | str], ...]]:
    match = SEMVER.fullmatch(value)
    if not match:
        raise ValueError(f"invalid npm SemVer: {value}")
    pre = match.group("pre")
    if pre is None:
        pre_key = ((2, ""),)
    else:
        parts: list[tuple[int, int | str]] = []
        for part in pre.split("."):
            parts.append((0, int(part)) if part.isdigit() else (1, part))
        pre_key = tuple(parts)
    return int(match.group("major")), int(match.group("minor")), int(match.group("patch")), pre_key


def compare_versions(left: str, right: str) -> int:
    """Compare npm SemVer precedence."""
    left_key, right_key = _version_key(left), _version_key(right)
    return (left_key > right_key) - (left_key < right_key)


def version_is_vulnerable(version: str, vulnerable_range: str) -> bool:
    """Evaluate an AND list of GitHub advisory comparators."""
    for raw in vulnerable_range.split(","):
        match = COMPARATOR.fullmatch(raw.strip())
        if not match:
            raise ValueError(f"unsupported comparator: {raw}")
        operator, target = match.group(1) or "=", match.group(2)
        comparison = compare_versions(version, target)
        if not {
            "<": comparison < 0,
            "<=": comparison <= 0,
            ">": comparison > 0,
            ">=": comparison >= 0,
            "=": comparison == 0,
        }[operator]:
            return False
    return True


def collect_npm_evidence(
    repository: Path,
    package_name: str,
    manifest_path: str = "package-lock.json",
    *,
    max_dependency_file_bytes: int = 32 * 1024 * 1024,
    excluded_paths: tuple[str, ...] = (),
) -> NpmEvidence:
    """Collect every installed instance from a package-lock v2/v3 file."""
    package_json_path, lock_path, prefix, package_manager = _project_paths(
        repository, manifest_path
    )
    project_root = package_json_path.parent
    package_manifest = f"{prefix}package.json"
    lock_manifest = f"{prefix}{lock_path.name}"
    if package_manifest in excluded_paths or lock_manifest in excluded_paths:
        raise ValueError("selected npm dependency file was excluded from the snapshot")
    package_json = _bounded_json_object(package_json_path, max_dependency_file_bytes)
    declarations = _manifest_declarations(
        package_json,
        package_name=package_name,
        manifest_path=package_manifest,
    )
    if lock_path.is_symlink():
        raise ValueError("dependency file symlinks are denied")
    if not lock_path.is_file():
        return NpmEvidence(
            package_manager=package_manager,
            lockfile_version=None,
            lockfile_path=None,
            proof_capabilities=(),
            package_name=package_name,
            instances=(),
            manifest_paths=(package_manifest,),
            completeness="partial",
            declarations=declarations,
            issues=(f"project {lock_path.name} is missing; manifest declarations only",),
        )
    if package_manager != "npm":
        lock_text = _bounded_text(lock_path, max_dependency_file_bytes)
        graph = (
            parse_yarn_classic(lock_text, declarations=declarations)
            if package_manager == "yarn-classic"
            else parse_pnpm_v9(lock_text, declarations=declarations)
        )
        projected_instances, consumers, graph_issues = project_target(
            graph,
            package_name=package_name,
            declarations=declarations,
        )
        positive_issues = (
            f"{package_manager} {graph.lockfile_version} support is positive-evidence only",
            *graph_issues,
        )
        return NpmEvidence(
            package_manager=package_manager,
            lockfile_version=graph.lockfile_version,
            lockfile_path=lock_manifest,
            proof_capabilities=(
                ("resolved_instances",)
                if any(instance.comparable for instance in projected_instances)
                else ()
            ),
            package_name=package_name,
            instances=projected_instances,
            manifest_paths=(package_manifest, lock_manifest),
            completeness="partial",
            declarations=declarations,
            dependency_consumers=consumers,
            issues=tuple(sorted(set(positive_issues))),
        )
    adapter = TypeAdapter(dict[str, object])
    raw = _bounded_json_object(lock_path, max_dependency_file_bytes)
    raw_version_number = raw.get("lockfileVersion")
    if raw_version_number not in {2, 3} or not isinstance(raw.get("packages"), dict):
        raise ValueError("only package-lock versions 2 and 3 with packages are supported")
    lockfile_version = "2" if raw_version_number == 2 else "3"
    packages = adapter.validate_python(raw["packages"])
    dependencies = adapter.validate_python(package_json.get("dependencies", {}))
    dev_dependencies = adapter.validate_python(package_json.get("devDependencies", {}))
    optional_dependencies = adapter.validate_python(package_json.get("optionalDependencies", {}))
    instances: list[NpmInstance] = []
    issues: list[str] = []
    manifest_paths = {package_manifest, lock_manifest}
    dependency_consumers: set[str] = set()
    resolved_workspace_targets: set[str] = set()
    declared_scopes: set[str] = set()
    if package_name in {
        key
        for mapping in (dependencies, dev_dependencies, optional_dependencies)
        for key in mapping
    }:
        declared_scopes.add(package_manifest)
    for package_path, raw_package_entry in packages.items():
        if not package_path or "node_modules" in package_path:
            continue
        try:
            package_entry = adapter.validate_python(raw_package_entry)
            workspace_maps = (
                adapter.validate_python(package_entry.get("dependencies", {})),
                adapter.validate_python(package_entry.get("devDependencies", {})),
                adapter.validate_python(package_entry.get("optionalDependencies", {})),
            )
        except ValidationError:
            continue
        if any(package_name in mapping for mapping in workspace_maps):
            declared_scopes.add(f"{prefix}{package_path}/package.json")
            manifest_paths.add(f"{prefix}{package_path}/package.json")
    suffix = f"node_modules/{package_name}"
    for raw_path, raw_entry in packages.items():
        try:
            entry = adapter.validate_python(raw_entry)
        except ValidationError:
            issues.append(f"malformed package entry: {raw_path}")
            continue
        if raw_path:
            for dependency_key in ("dependencies", "optionalDependencies"):
                dependency_map = adapter.validate_python(entry.get(dependency_key, {}))
                if package_name in dependency_map:
                    dependency_consumers.add(raw_path)
        entry_name = entry.get("name")
        path_matches = raw_path == suffix or raw_path.endswith(f"/{suffix}")
        name_matches = entry_name == package_name
        if entry.get("link") is True and path_matches:
            resolved = entry.get("resolved")
            if not isinstance(resolved, str):
                issues.append(f"unresolved workspace link: {raw_path}")
                continue
            target_path = PurePath(resolved)
            target = target_path.as_posix().removeprefix("./")
            if target_path.is_absolute() or ".." in target_path.parts or target not in packages:
                issues.append(f"unresolved workspace link: {raw_path}")
                continue
            target_entry = adapter.validate_python(packages[target])
            target_name = target_entry.get("name")
            target_version = target_entry.get("version")
            if (
                target_name != package_name
                or not isinstance(target_version, str)
                or SEMVER.fullmatch(target_version) is None
                or not (project_root / target).is_dir()
            ):
                issues.append(f"invalid workspace target: {raw_path}")
                continue
            if target in resolved_workspace_targets:
                continue
            resolved_workspace_targets.add(target)
            manifest_paths.add(f"{prefix}{target}/package.json")
            instances.append(
                NpmInstance(
                    path=raw_path,
                    version=target_version,
                    relationship="workspace",
                    comparable=True,
                )
            )
            continue
        if raw_path in resolved_workspace_targets:
            continue
        if name_matches and not path_matches and "/node_modules/" not in f"/{raw_path}":
            continue
        if not path_matches and not name_matches:
            continue
        raw_version = entry.get("version")
        comparable = isinstance(raw_version, str) and SEMVER.fullmatch(raw_version) is not None
        if (isinstance(entry_name, str) and entry_name != package_name) or (
            name_matches and not path_matches
        ):
            comparable = False
            issues.append(f"unsupported alias instance: {raw_path}")
        if entry.get("link") is True:
            comparable = False
            issues.append(f"unsupported linked instance: {raw_path}")
        resolved_source = entry.get("resolved")
        external_resolved = False
        if isinstance(resolved_source, str):
            if resolved_source.startswith(("git+", "git://", "ssh://", "file:")):
                external_resolved = True
            elif resolved_source.startswith(("http://", "https://")):
                external_resolved = urlparse(resolved_source).hostname != "registry.npmjs.org"
        if (
            isinstance(raw_version, str)
            and raw_version.startswith(("git+", "http:", "https:", "file:", "npm:"))
        ) or external_resolved:
            comparable = False
            issues.append(f"unsupported version source: {raw_path}")
        owner_key = raw_path.split("/node_modules/", 1)[0] if "/node_modules/" in raw_path else ""
        owner = adapter.validate_python(packages.get(owner_key, {}))
        owner_dependencies = adapter.validate_python(
            owner.get("dependencies", {}) if owner_key else dependencies
        )
        owner_dev_dependencies = adapter.validate_python(
            owner.get("devDependencies", {}) if owner_key else dev_dependencies
        )
        owner_optional_dependencies = adapter.validate_python(
            owner.get("optionalDependencies", {}) if owner_key else optional_dependencies
        )
        if owner_key:
            manifest_paths.add(f"{prefix}{owner_key}/package.json")
        if owner_key.startswith("node_modules/"):
            relationship = "transitive"
        elif raw_path == suffix or owner_key:
            if package_name in owner_dependencies:
                relationship = "direct"
            elif package_name in owner_dev_dependencies:
                relationship = "development"
            elif package_name in owner_optional_dependencies:
                relationship = "optional"
            else:
                relationship = "transitive"
        else:
            relationship = "transitive"
        instances.append(
            NpmInstance(
                path=raw_path,
                version=raw_version if isinstance(raw_version, str) else None,
                relationship=relationship,
                comparable=comparable,
                development_only=entry.get("dev") is True,
            )
        )
        if not comparable:
            issues.append(f"uncomparable instance: {raw_path}")
    if declared_scopes and not instances:
        scopes = ", ".join(sorted(declared_scopes))
        issues.append(f"declared dependency is unresolved in package-lock packages: {scopes}")
    if lockfile_version == "2" and isinstance(raw.get("dependencies"), dict):
        legacy = adapter.validate_python(raw["dependencies"])
        legacy_versions: set[object] = set()

        def collect_legacy(entries: dict[str, object]) -> None:
            for name, raw_entry in entries.items():
                entry_data = adapter.validate_python(raw_entry)
                if name == package_name:
                    legacy_versions.add(entry_data.get("version"))
                nested = entry_data.get("dependencies")
                if isinstance(nested, dict):
                    collect_legacy(adapter.validate_python(nested))

        collect_legacy(legacy)
        package_versions = {instance.version for instance in instances}
        if not legacy_versions.issubset(package_versions):
            issues.append("conflicting v2 packages and dependencies data")
    if not issues:
        completeness = "complete"
    elif all(issue.startswith("malformed package entry:") for issue in issues):
        completeness = "partial"
    else:
        completeness = "unsupported"
    capabilities: tuple[
        Literal[
            "resolved_instances",
            "complete_inventory",
            "dependency_consumers_complete",
            "development_scope",
        ],
        ...,
    ] = ()
    if completeness == "complete":
        capabilities = (
            "resolved_instances",
            "complete_inventory",
            "dependency_consumers_complete",
            "development_scope",
        )
    return NpmEvidence(
        package_manager="npm",
        lockfile_version=lockfile_version,
        lockfile_path=lock_manifest,
        proof_capabilities=capabilities,
        package_name=package_name,
        instances=tuple(instances),
        manifest_paths=tuple(sorted(manifest_paths)),
        declarations=declarations,
        dependency_consumers=tuple(sorted(dependency_consumers)),
        completeness=completeness,
        issues=tuple(sorted(set(issues))),
    )
