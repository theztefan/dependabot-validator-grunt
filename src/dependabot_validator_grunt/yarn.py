"""Bounded Yarn Classic v1 lockfile parsing."""

from __future__ import annotations

import csv
import re
import shlex
from dataclasses import dataclass, field
from typing import cast
from urllib.parse import urlparse

from dependabot_validator_grunt.dependency_graph import (
    DependencyEdge,
    DependencyEdgeKind,
    DependencyGraph,
    DependencyNode,
)
from dependabot_validator_grunt.models import DependencyDeclaration, SourceKind

_SEMVER = re.compile(
    r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
_MAX_LINES = 500_000
_MAX_LINE_CHARACTERS = 16_384


@dataclass
class _Record:
    selectors: tuple[str, ...]
    version: str | None = None
    resolved: str | None = None
    dependencies: list[tuple[str, str, DependencyEdgeKind]] = field(
        default_factory=lambda: list[tuple[str, str, DependencyEdgeKind]]()
    )
    fields: set[str] = field(default_factory=lambda: set[str]())
    dependency_fields: set[tuple[str, str]] = field(default_factory=lambda: set[tuple[str, str]]())


def _descriptor(selector: str) -> tuple[str, str, str]:
    if selector.startswith("@"):
        slash = selector.find("/")
        separator = selector.find("@", slash + 1)
    else:
        separator = selector.find("@")
    if separator <= 0:
        raise ValueError("Yarn selector is malformed")
    declared_name = selector[:separator]
    specifier = selector[separator + 1 :]
    actual_name = declared_name
    if specifier.startswith("npm:"):
        alias = specifier.removeprefix("npm:")
        if alias.startswith("@"):
            slash = alias.find("/")
            alias_separator = alias.find("@", slash + 1)
        else:
            alias_separator = alias.find("@")
        actual_name = alias if alias_separator < 0 else alias[:alias_separator]
    return declared_name, specifier, actual_name


def _selectors(header: str) -> tuple[str, ...]:
    try:
        values = next(csv.reader([header.removesuffix(":")], skipinitialspace=True))
    except csv.Error as error:
        raise ValueError("Yarn selector list is malformed") from error
    selectors = tuple(value.strip() for value in values)
    if not selectors or any(not value for value in selectors):
        raise ValueError("Yarn selector list is empty")
    return selectors


def _field(line: str) -> tuple[str, str]:
    try:
        parts = shlex.split(line.strip(), posix=True)
    except ValueError as error:
        raise ValueError("Yarn lockfile field is malformed") from error
    if len(parts) != 2:
        raise ValueError("Yarn lockfile field is malformed")
    return parts[0], parts[1]


def _source_metadata(resolved: str | None) -> tuple[SourceKind, str | None]:
    if resolved is None:
        return "unknown", None
    lowered = resolved.casefold()
    if lowered.startswith(("git+", "git://", "ssh://", "git@", "github:", "gitlab:")):
        return "vcs", resolved
    if lowered.startswith(("file:", "link:", "./", "../", "/")):
        return "path", resolved
    parsed = urlparse(resolved)
    if parsed.scheme.casefold() in {"http", "https"}:
        if (parsed.hostname or "").casefold() in {
            "registry.npmjs.org",
            "registry.yarnpkg.com",
        }:
            return "registry", resolved
        return "url", resolved
    return "unknown", resolved


def parse_yarn_classic(
    text: str,
    *,
    declarations: tuple[DependencyDeclaration, ...],
) -> DependencyGraph:
    """Parse the deterministic subset of Yarn Classic lockfile v1."""
    lines = text.splitlines()
    if len(lines) > _MAX_LINES:
        raise ValueError("Yarn lockfile exceeds the configured line limit")
    if not any(line.strip() == "# yarn lockfile v1" for line in lines[:10]):
        raise ValueError("only Yarn Classic lockfile version 1 is supported")
    if any(marker in text for marker in ("<<<<<<<", "=======", ">>>>>>>")):
        raise ValueError("Yarn lockfile contains merge conflict markers")

    records: list[_Record] = []
    current: _Record | None = None
    section: str | None = None
    for raw_line in lines:
        if len(raw_line) > _MAX_LINE_CHARACTERS:
            raise ValueError("Yarn lockfile line exceeds the configured limit")
        if "\t" in raw_line:
            raise ValueError("Yarn lockfile tabs are unsupported")
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if indent == 0:
            if not stripped.endswith(":"):
                raise ValueError("Yarn lockfile record header is malformed")
            current = _Record(selectors=_selectors(stripped))
            records.append(current)
            section = None
            continue
        if current is None:
            raise ValueError("Yarn lockfile field has no record")
        if indent == 2:
            if stripped in {"dependencies:", "optionalDependencies:"}:
                section = stripped.removesuffix(":")
                if section in current.fields:
                    raise ValueError("Yarn lockfile contains duplicate fields")
                current.fields.add(section)
                continue
            key, value = _field(stripped)
            if key in current.fields:
                raise ValueError("Yarn lockfile contains duplicate fields")
            current.fields.add(key)
            if key == "version":
                current.version = value
            elif key == "resolved":
                current.resolved = value
            section = None
            continue
        if indent == 4 and section in {"dependencies", "optionalDependencies"}:
            name, specifier = _field(stripped)
            dependency_field = (section, name)
            if dependency_field in current.dependency_fields:
                raise ValueError("Yarn lockfile contains duplicate dependency fields")
            current.dependency_fields.add(dependency_field)
            kind: DependencyEdgeKind = (
                "optional" if section == "optionalDependencies" else "transitive"
            )
            current.dependencies.append((name, specifier, kind))
            continue
        if indent > 4:
            raise ValueError("Yarn lockfile nesting exceeds the supported grammar")

    selector_index: dict[str, str] = {}
    nodes: list[DependencyNode] = []
    record_names: dict[str, str] = {}
    for index, record in enumerate(records):
        descriptors = tuple(_descriptor(selector) for selector in record.selectors)
        actual_names = {descriptor[2] for descriptor in descriptors}
        if len(actual_names) != 1:
            raise ValueError("Yarn record selectors resolve to different packages")
        actual_name = actual_names.pop()
        instance_id = f"yarn:{actual_name}@{record.version or 'unknown'}:{index}"
        for selector in record.selectors:
            if selector in selector_index:
                raise ValueError("Yarn lockfile contains duplicate selectors")
            selector_index[selector] = instance_id
        registry_source = isinstance(record.resolved, str) and record.resolved.startswith(
            ("https://registry.yarnpkg.com/", "https://registry.npmjs.org/")
        )
        source_kind, source_locator = _source_metadata(record.resolved)
        nodes.append(
            DependencyNode(
                instance_id=instance_id,
                package_name=actual_name,
                version=record.version,
                comparable=bool(
                    registry_source and record.version and _SEMVER.fullmatch(record.version)
                ),
                source_kind=source_kind,
                source_locator=source_locator,
            )
        )
        record_names[instance_id] = actual_name

    edges: list[DependencyEdge] = []
    for index, record in enumerate(records):
        consumer_id = nodes[index].instance_id
        for declared_name, specifier, kind in record.dependencies:
            selector = f"{declared_name}@{specifier}"
            target_id = selector_index.get(selector)
            actual_name = (
                record_names.get(target_id, declared_name)
                if target_id is not None
                else declared_name
            )
            edges.append(
                DependencyEdge(
                    consumer_id=consumer_id,
                    target_id=target_id,
                    declared_name=declared_name,
                    actual_name=actual_name,
                    kind=kind,
                )
            )
    for declaration in declarations:
        selector = f"{declaration.name}@{declaration.spec}"
        edges.append(
            DependencyEdge(
                consumer_id=f"importer:{declaration.manifest_path}",
                target_id=selector_index.get(selector),
                declared_name=declaration.name,
                actual_name=declaration.alias_target or declaration.name,
                kind=cast(
                    DependencyEdgeKind,
                    {
                        "direct": "runtime",
                        "development": "development",
                        "optional": "optional",
                        "peer": "peer",
                    }[declaration.relationship],
                ),
            )
        )
    return DependencyGraph(
        lockfile_version="1",
        nodes=tuple(nodes),
        edges=tuple(edges),
    )
