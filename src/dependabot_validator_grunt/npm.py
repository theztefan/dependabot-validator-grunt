"""Deterministic npm lockfile and SemVer evidence."""

from __future__ import annotations

import re
from pathlib import Path, PurePath, PurePosixPath
from typing import Literal, cast
from urllib.parse import urlparse

from pydantic import TypeAdapter, ValidationError

from dependabot_validator_grunt.dependency_files import bounded_json_object, bounded_text
from dependabot_validator_grunt.dependency_graph import project_target
from dependabot_validator_grunt.models import (
    DependencyDeclaration,
    DependencyEvidence,
    DependencyInstance,
    SourceKind,
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
_PACKAGE_LOCK_V1_MAX_TRAVERSAL_STEPS = 100_000
_PACKAGE_LOCK_V1_MAX_MATCHING_INSTANCES = 10_000
_PACKAGE_LOCK_V1_MAX_CONSUMERS = 10_000
_PACKAGE_LOCK_V1_MAX_SERIALIZED_OUTPUT_BYTES = 2 * 1024 * 1024


def _npm_source_metadata(
    raw_version: object,
    resolved_source: object,
) -> tuple[SourceKind, str | None]:
    def classify(locator: str) -> SourceKind:
        lowered = locator.casefold()
        if lowered.startswith("workspace:"):
            return "workspace"
        if lowered.startswith(
            ("git+", "git://", "ssh://", "git@", "github:", "gitlab:", "bitbucket:")
        ):
            return "vcs"
        if lowered.startswith(("file:", "link:", "./", "../", "/")):
            return "path"
        if lowered.startswith("npm:"):
            return "registry"
        parsed = urlparse(locator)
        if parsed.scheme.casefold() in {"http", "https"}:
            if (parsed.hostname or "").casefold() in {
                "registry.npmjs.org",
                "registry.yarnpkg.com",
            }:
                return "registry"
            return "url"
        return "unknown"

    if isinstance(resolved_source, str):
        return classify(resolved_source), resolved_source
    if isinstance(raw_version, str):
        source_kind = classify(raw_version)
        if source_kind != "unknown":
            return source_kind, raw_version
    return "unknown", None


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
) -> tuple[DependencyDeclaration, ...]:
    adapter = TypeAdapter(dict[str, object])
    declarations: list[DependencyDeclaration] = []
    for section, relationship in DEPENDENCY_SECTIONS.items():
        mapping = adapter.validate_python(package_json.get(section, {}))
        for name, raw_spec in mapping.items():
            if not isinstance(raw_spec, str):
                raise ValueError(f"npm dependency declaration is invalid: {section}")
            alias_target = _alias_target(raw_spec)
            if name != package_name and alias_target != package_name:
                continue
            declarations.append(
                DependencyDeclaration(
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


def _collect_package_lock_v1(
    raw: dict[str, object],
    *,
    package_name: str,
    package_manifest: str,
    lock_manifest: str,
    declarations: tuple[DependencyDeclaration, ...],
) -> DependencyEvidence:
    adapter = TypeAdapter(dict[str, object])
    root_dependencies = raw.get("dependencies")
    if not isinstance(root_dependencies, dict):
        raise ValueError("package-lock version 1 dependencies must be an object")

    instances: list[DependencyInstance] = []
    consumers: set[str] = set()
    issues: set[str] = set()
    traversal_steps = 0
    matching_instance_count = 0
    serialized_record_bytes = 0

    def charge_serialized_record(value: str) -> None:
        nonlocal serialized_record_bytes
        size = len(value.encode("utf-8"))
        if serialized_record_bytes + size > _PACKAGE_LOCK_V1_MAX_SERIALIZED_OUTPUT_BYTES:
            raise ValueError(
                "package-lock version 1 serialized evidence exceeds the configured limit"
            )
        serialized_record_bytes += size

    def add_issue(message: str) -> None:
        if message in issues:
            return
        charge_serialized_record(f"{message!r}")
        issues.add(message)

    def add_consumer(consumer: str) -> None:
        if consumer in consumers:
            return
        if len(consumers) >= _PACKAGE_LOCK_V1_MAX_CONSUMERS:
            raise ValueError("package-lock version 1 consumer count exceeds the configured limit")
        charge_serialized_record(f"{consumer!r}")
        consumers.add(consumer)

    def append_instance(instance: DependencyInstance) -> None:
        charge_serialized_record(instance.model_dump_json())
        instances.append(instance)

    add_issue("package-lock 1 support is positive-evidence only")
    direct_relationships: set[Literal["direct", "development", "optional"]] = set()
    for declaration in declarations:
        if declaration.name == package_name and declaration.relationship != "peer":
            direct_relationships.add(declaration.relationship)
    stack: list[tuple[dict[str, object], str, int]] = [
        (adapter.validate_python(root_dependencies), "", 0)
    ]
    while stack:
        dependencies, parent_path, depth = stack.pop()
        if depth > 256:
            raise ValueError("package-lock version 1 dependency tree is too deep")
        for name, raw_entry in dependencies.items():
            if traversal_steps >= _PACKAGE_LOCK_V1_MAX_TRAVERSAL_STEPS:
                raise ValueError(
                    "package-lock version 1 traversal step count exceeds the configured limit"
                )
            traversal_steps += 1
            path = f"{parent_path}/node_modules/{name}" if parent_path else f"node_modules/{name}"
            if name == package_name:
                if matching_instance_count >= _PACKAGE_LOCK_V1_MAX_MATCHING_INSTANCES:
                    raise ValueError(
                        "package-lock version 1 matching instance count "
                        "exceeds the configured limit"
                    )
                matching_instance_count += 1
            try:
                entry = adapter.validate_python(raw_entry)
            except ValidationError:
                add_issue(f"malformed package entry: {path}")
                continue
            nested = entry.get("dependencies", {})
            if not isinstance(nested, dict):
                add_issue(f"malformed package dependencies: {path}")
            elif nested:
                stack.append((adapter.validate_python(nested), path, depth + 1))
            if name != package_name:
                continue

            raw_version = entry.get("version")
            resolved_source = entry.get("resolved")
            parsed_source = urlparse(resolved_source) if isinstance(resolved_source, str) else None
            comparable = (
                isinstance(raw_version, str)
                and SEMVER.fullmatch(raw_version) is not None
                and parsed_source is not None
                and parsed_source.scheme.lower() in {"http", "https"}
                and parsed_source.hostname == "registry.npmjs.org"
            )
            if not comparable:
                add_issue(f"uncomparable instance: {path}")
            source_kind, source_locator = _npm_source_metadata(
                raw_version,
                resolved_source,
            )

            relationship: Literal["direct", "development", "optional", "transitive"] = "transitive"
            if not parent_path and len(direct_relationships) == 1:
                relationship = next(iter(direct_relationships))
            if parent_path:
                add_consumer(parent_path)
            append_instance(
                DependencyInstance(
                    path=path,
                    version=raw_version if isinstance(raw_version, str) else None,
                    relationship=relationship,
                    comparable=comparable,
                    development_only=entry.get("dev") is True,
                    source_kind=source_kind,
                    source_locator=source_locator,
                )
            )

    capabilities: tuple[Literal["resolved_instances"], ...] = ()
    if any(instance.comparable for instance in instances):
        capabilities = ("resolved_instances",)
    evidence = DependencyEvidence(
        package_manager="npm",
        lockfile_version="1",
        lockfile_path=lock_manifest,
        proof_capabilities=capabilities,
        package_name=package_name,
        instances=tuple(instances),
        manifest_paths=(package_manifest, lock_manifest),
        declarations=declarations,
        dependency_consumers=tuple(sorted(consumers)),
        completeness="partial",
        issues=tuple(sorted(issues)),
    )
    if (
        len(evidence.model_dump_json().encode("utf-8"))
        > _PACKAGE_LOCK_V1_MAX_SERIALIZED_OUTPUT_BYTES
    ):
        raise ValueError("package-lock version 1 serialized evidence exceeds the configured limit")
    return evidence


def collect_npm_evidence(
    repository: Path,
    package_name: str,
    manifest_path: str = "package-lock.json",
    *,
    max_dependency_file_bytes: int = 32 * 1024 * 1024,
    excluded_paths: tuple[str, ...] = (),
) -> DependencyEvidence:
    """Collect dependency evidence from the selected npm ecosystem input."""
    package_json_path, lock_path, prefix, package_manager = _project_paths(
        repository, manifest_path
    )
    project_root = package_json_path.parent
    package_manifest = f"{prefix}package.json"
    lock_manifest = f"{prefix}{lock_path.name}"
    selected_name = PurePosixPath(PurePath(manifest_path).as_posix()).name
    if package_manifest in excluded_paths or lock_manifest in excluded_paths:
        raise ValueError("selected npm dependency file was excluded from the snapshot")
    if lock_path.is_symlink():
        raise ValueError("dependency file symlinks are denied")
    if selected_name != "package.json" and not lock_path.is_file():
        raise ValueError(f"selected npm dependency file is missing: {lock_manifest}")
    if not package_json_path.is_file():
        raise ValueError(f"selected npm project manifest is missing: {package_manifest}")
    package_json = bounded_json_object(package_json_path, max_dependency_file_bytes)
    declarations = _manifest_declarations(
        package_json,
        package_name=package_name,
        manifest_path=package_manifest,
    )
    if not lock_path.is_file():
        return DependencyEvidence(
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
        lock_text = bounded_text(lock_path, max_dependency_file_bytes)
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
        return DependencyEvidence(
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
    raw = bounded_json_object(lock_path, max_dependency_file_bytes)
    raw_version_number = raw.get("lockfileVersion")
    if raw_version_number == 1:
        return _collect_package_lock_v1(
            raw,
            package_name=package_name,
            package_manifest=package_manifest,
            lock_manifest=lock_manifest,
            declarations=declarations,
        )
    if raw_version_number not in {2, 3} or not isinstance(raw.get("packages"), dict):
        raise ValueError(
            "only package-lock version 1 with dependencies or versions 2 and 3 "
            "with packages are supported"
        )
    lockfile_version = "2" if raw_version_number == 2 else "3"
    packages = adapter.validate_python(raw["packages"])
    dependencies = adapter.validate_python(package_json.get("dependencies", {}))
    dev_dependencies = adapter.validate_python(package_json.get("devDependencies", {}))
    optional_dependencies = adapter.validate_python(package_json.get("optionalDependencies", {}))
    instances: list[DependencyInstance] = []
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
            if isinstance(resolved, str):
                target_path = PurePath(resolved)
                target = target_path.as_posix().removeprefix("./")
                if (
                    not target_path.is_absolute()
                    and ".." not in target_path.parts
                    and target in packages
                ):
                    target_entry = adapter.validate_python(packages[target])
                    target_name = target_entry.get("name")
                    target_version = target_entry.get("version")
                    if (
                        target_name == package_name
                        and isinstance(target_version, str)
                        and SEMVER.fullmatch(target_version) is not None
                        and (project_root / target).is_dir()
                    ):
                        if target in resolved_workspace_targets:
                            continue
                        resolved_workspace_targets.add(target)
                        manifest_paths.add(f"{prefix}{target}/package.json")
                        instances.append(
                            DependencyInstance(
                                path=raw_path,
                                version=target_version,
                                relationship="workspace",
                                comparable=True,
                                source_kind="workspace",
                                source_locator=target,
                            )
                        )
                        continue
                    issues.append(f"invalid workspace target: {raw_path}")
                else:
                    issues.append(f"unresolved workspace link: {raw_path}")
            else:
                issues.append(f"unresolved workspace link: {raw_path}")
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
        source_kind, source_locator = _npm_source_metadata(raw_version, resolved_source)
        if entry.get("link") is True and isinstance(resolved_source, str):
            source_kind = "path"
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
            DependencyInstance(
                path=raw_path,
                version=raw_version if isinstance(raw_version, str) else None,
                relationship=relationship,
                comparable=comparable,
                development_only=entry.get("dev") is True,
                source_kind=source_kind,
                source_locator=source_locator,
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
    return DependencyEvidence(
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
