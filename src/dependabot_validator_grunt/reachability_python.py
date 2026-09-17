"""Trusted Python reachability interpretation."""

from __future__ import annotations

import ast
import re
import textwrap

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

PYTHON_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def interpret_python(
    operations: OperationMatches,
    sources: dict[str, bytes],
    *,
    target_identifiers: tuple[str, ...],
    max_findings: int,
) -> tuple[list[ReachabilityFinding], bool]:
    """Interpret fixed ast-grep operations using Python import semantics."""

    findings: list[ReachabilityFinding] = []
    aliases: dict[str, dict[str, str | None]] = {}
    calls: dict[str, list[dict[str, object]]] = {}

    for raw in operations.get("import_statement", ()):
        language = match_language(raw)
        if language.casefold() != "python":
            continue
        relative = match_file(raw)
        for target, binding in _import_bindings(match_text(raw), target_identifiers):
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

    for raw in operations.get("import_from_statement", ()):
        language = match_language(raw)
        if language.casefold() != "python":
            continue
        relative = match_file(raw)
        for target, binding in _import_bindings(match_text(raw), target_identifiers):
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

    for raw in operations.get("call", ()):
        language = match_language(raw)
        if language.casefold() != "python":
            continue
        relative = match_file(raw)
        calls.setdefault(relative, []).append(raw)
        text = match_text(raw)
        target = _dynamic_target(text, target_identifiers)
        if target is None:
            continue
        binding = _assignment_binding(match_lines(raw), text)
        _register_alias(aliases, relative, binding, target)
        findings.append(
            build_finding(
                sources,
                raw,
                kind="dynamic_import",
                language=language,
                matched_target=target,
                binding=binding,
            )
        )

    for relative, file_aliases in aliases.items():
        for alias, target in sorted(file_aliases.items()):
            if target is None or PYTHON_IDENTIFIER.fullmatch(alias) is None:
                continue
            for raw in calls.get(relative, []):
                if _call_root(match_text(raw)) == alias:
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


def _import_bindings(
    text: str,
    targets: tuple[str, ...],
) -> tuple[tuple[str, str | None], ...]:
    try:
        parsed = ast.parse(text)
    except SyntaxError:
        return ()
    if len(parsed.body) != 1:
        return ()
    statement = parsed.body[0]
    bindings: list[tuple[str, str | None]] = []
    if isinstance(statement, ast.Import):
        for imported in statement.names:
            target = _matched_module_target(imported.name, targets)
            if target is None:
                continue
            binding = imported.asname or imported.name.partition(".")[0]
            bindings.append((target, binding))
    elif isinstance(statement, ast.ImportFrom) and statement.level == 0 and statement.module:
        target = _matched_module_target(statement.module, targets)
        if target is None:
            return ()
        for imported in statement.names:
            binding = None if imported.name == "*" else imported.asname or imported.name
            bindings.append((target, binding))
    return tuple(bindings)


def _matched_module_target(module: str, targets: tuple[str, ...]) -> str | None:
    ordered = sorted(enumerate(targets), key=lambda item: (-len(item[1]), item[0]))
    for _, target in ordered:
        if module == target or module.startswith(f"{target}."):
            return target
    return None


def _dynamic_target(text: str, targets: tuple[str, ...]) -> str | None:
    try:
        expression = ast.parse(text, mode="eval").body
    except SyntaxError:
        return None
    if not isinstance(expression, ast.Call) or not expression.args:
        return None
    loader = expression.func
    is_dunder_import = isinstance(loader, ast.Name) and loader.id == "__import__"
    supported_loader = is_dunder_import or (
        isinstance(loader, ast.Attribute)
        and loader.attr == "import_module"
        and isinstance(loader.value, ast.Name)
        and loader.value.id == "importlib"
    )
    argument = expression.args[0]
    if (
        not supported_loader
        or not isinstance(argument, ast.Constant)
        or not isinstance(argument.value, str)
    ):
        return None
    if is_dunder_import and not _is_absolute_dunder_import(expression):
        return None
    return _matched_module_target(argument.value, targets)


def _is_absolute_dunder_import(expression: ast.Call) -> bool:
    if any(isinstance(argument, ast.Starred) for argument in expression.args[1:]):
        return False
    if any(keyword.arg is None for keyword in expression.keywords):
        return False
    level_values = [keyword.value for keyword in expression.keywords if keyword.arg == "level"]
    if len(level_values) > 1:
        return False
    if len(expression.args) >= 5 and level_values:
        return False
    level = (
        expression.args[4]
        if len(expression.args) >= 5
        else (level_values[0] if level_values else None)
    )
    return level is None or (
        isinstance(level, ast.Constant) and isinstance(level.value, int) and level.value == 0
    )


def _assignment_binding(line: str, expression: str) -> str | None:
    source = textwrap.dedent(line)
    try:
        parsed = ast.parse(source)
    except SyntaxError:
        return None
    for node in ast.walk(parsed):
        binding: str | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            binding = target.id if isinstance(target, ast.Name) else None
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            binding = node.target.id if isinstance(node.target, ast.Name) else None
            value = node.value
        if (
            binding is not None
            and value is not None
            and ast.get_source_segment(source, value) == expression
        ):
            return binding
    return None


def _call_root(text: str) -> str | None:
    try:
        expression = ast.parse(text, mode="eval").body
    except SyntaxError:
        return None
    if not isinstance(expression, ast.Call):
        return None
    target = expression.func
    while isinstance(target, ast.Attribute):
        target = target.value
    return target.id if isinstance(target, ast.Name) else None


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
