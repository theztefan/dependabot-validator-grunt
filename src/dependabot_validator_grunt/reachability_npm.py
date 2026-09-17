"""Trusted npm JavaScript and TypeScript reachability interpretation."""

from __future__ import annotations

import re

from dependabot_validator_grunt.models import ReachabilityFinding
from dependabot_validator_grunt.reachability_ast_grep import (
    OperationMatches,
    build_finding,
    limit_findings,
    match_file,
    match_language,
    match_lines,
    match_text,
)

IDENTIFIER = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
JAVASCRIPT_LANGUAGES = frozenset({"javascript", "jsx", "typescript", "tsx"})


def interpret_npm(
    operations: OperationMatches,
    sources: dict[str, bytes],
    *,
    target_identifiers: tuple[str, ...],
    max_findings: int,
) -> tuple[list[ReachabilityFinding], bool]:
    """Interpret fixed ast-grep operations using npm usage semantics."""

    findings: list[ReachabilityFinding] = []
    aliases: dict[str, dict[str, str | None]] = {}
    calls: dict[str, list[dict[str, object]]] = {}

    for raw in operations.get("import_statement", ()):
        language = match_language(raw)
        if language.casefold() not in JAVASCRIPT_LANGUAGES:
            continue
        text = match_text(raw)
        target = _matched_literal(text, target_identifiers)
        if target is None:
            continue
        relative = match_file(raw)
        binding = _import_binding(text)
        _register_alias(aliases, relative, binding, target)
        findings.append(
            build_finding(
                sources,
                raw,
                kind="static_import",
                language=language,
                matched_target=target,
                binding=binding,
            )
        )

    for raw in operations.get("call_expression", ()):
        language = match_language(raw)
        if language.casefold() not in JAVASCRIPT_LANGUAGES:
            continue
        relative = match_file(raw)
        calls.setdefault(relative, []).append(raw)
        text = match_text(raw)
        target = _matched_literal(text, target_identifiers)
        kind: str | None = None
        if target is not None and re.match(
            r"^require\s*(?:/\*.*?\*/\s*)?\(",
            text,
            re.DOTALL,
        ):
            kind = "runtime_require"
        elif target is not None and re.match(
            r"^import\s*(?:/\*.*?\*/\s*)?\(",
            text,
            re.DOTALL,
        ):
            kind = "dynamic_import"
        if kind not in {"runtime_require", "dynamic_import"} or target is None:
            continue
        binding = _assignment_binding(match_lines(raw), text)
        _register_alias(aliases, relative, binding, target)
        findings.append(
            build_finding(
                sources,
                raw,
                kind=kind,
                language=language,
                matched_target=target,
                binding=binding,
            )
        )

    for relative, file_aliases in aliases.items():
        for alias, target in sorted(file_aliases.items()):
            if target is None or IDENTIFIER.fullmatch(alias) is None:
                continue
            bound_call = re.compile(rf"^{re.escape(alias)}(?:\.[A-Za-z_$][A-Za-z0-9_$]*)?\s*\(")
            for raw in calls.get(relative, []):
                if bound_call.match(match_text(raw)):
                    findings.append(
                        build_finding(
                            sources,
                            raw,
                            kind="bound_call",
                            language=match_language(raw),
                            matched_target=target,
                            binding=alias,
                        )
                    )

    return limit_findings(findings, max_findings)


def _matched_literal(text: str, targets: tuple[str, ...]) -> str | None:
    ordered = sorted(enumerate(targets), key=lambda item: (-len(item[1]), item[0]))
    for _, target in ordered:
        literal = re.compile(rf"""(?P<quote>["']){re.escape(target)}(?:/[^"']+)?(?P=quote)""")
        if literal.search(text) is not None:
            return target
    return None


def _import_binding(text: str) -> str | None:
    match = re.match(r"\s*import\s+(?P<binding>[A-Za-z_$][A-Za-z0-9_$]*)\s+from\b", text)
    if match:
        return match.group("binding")
    namespace = re.match(
        r"\s*import\s+\*\s+as\s+(?P<binding>[A-Za-z_$][A-Za-z0-9_$]*)\s+from\b",
        text,
    )
    return namespace.group("binding") if namespace else None


def _assignment_binding(line: str, expression: str) -> str | None:
    match = re.search(
        rf"\b(?:const|let|var)\s+(?P<binding>[A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*"
        rf"{re.escape(expression)}",
        line,
    )
    return match.group("binding") if match else None


def _register_alias(
    aliases: dict[str, dict[str, str | None]],
    relative: str,
    binding: str | None,
    target: str,
) -> None:
    if binding is None:
        return
    file_aliases = aliases.setdefault(relative, {})
    existing = file_aliases.get(binding)
    if existing is None and binding not in file_aliases:
        file_aliases[binding] = target
    elif existing != target:
        file_aliases[binding] = None
