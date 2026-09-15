"""Static safety rules for production code and declarative assets."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import cast

PACKAGE_ROOT = Path(__file__).parents[1] / "src" / "dependabot_validator_grunt"

UNSAFE_SDK_PATTERNS = {
    "blanket permission approval": re.compile(r"\bPermissionHandler\.approve_all\b"),
    "wildcard built-in tools": re.compile(r"\.add_(?:builtin|mcp|custom)\(\s*[\"']\*[\"']"),
    "wildcard agent tools": re.compile(
        r"(?:^tools\s*:|[\"']tools[\"']\s*:)\s*"
        r"(?:\[[^\]]*[\"']\*[\"']|(?:\n[ \t]+.*)*\n[ \t]*-[ \t]*[\"']?\*[\"']?)",
        re.MULTILINE,
    ),
}


def test_production_code_avoids_permissive_sdk_configuration() -> None:
    """Reject Copilot SDK settings that bypass least-privilege review."""
    violations: list[str] = []
    for path in PACKAGE_ROOT.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for description, pattern in UNSAFE_SDK_PATTERNS.items():
            if pattern.search(source):
                violations.append(f"{path.relative_to(PACKAGE_ROOT)}: {description}")

    for directory in ("agents", "system-prompts", "prompts", "skills", "tools", "policies"):
        for path in (PACKAGE_ROOT / directory).rglob("*"):
            if not path.is_file():
                continue
            source = path.read_text(encoding="utf-8")
            for description, pattern in UNSAFE_SDK_PATTERNS.items():
                if pattern.search(source):
                    violations.append(f"{path.relative_to(PACKAGE_ROOT)}: {description}")

    assert not violations, "Unsafe SDK configuration:\n" + "\n".join(violations)


def call_name(call: ast.Call) -> str | None:
    """Return the called function or method name."""
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def keyword_values(call: ast.Call) -> dict[str, ast.expr]:
    """Return explicit keyword arguments for a call."""
    return {keyword.arg: keyword.value for keyword in call.keywords if keyword.arg is not None}


def string_sequence(
    expression: ast.expr,
    constants: dict[str, tuple[str, ...]],
) -> tuple[str, ...] | None:
    """Resolve a literal or named tuple/list of strings used by a safety call."""
    if isinstance(expression, (ast.List, ast.Tuple)):
        if all(
            isinstance(element, ast.Constant) and isinstance(element.value, str)
            for element in expression.elts
        ):
            return tuple(
                cast(str, cast(ast.Constant, element).value) for element in expression.elts
            )
        return None
    if isinstance(expression, ast.Name):
        return constants.get(expression.id)
    if (
        isinstance(expression, ast.Call)
        and isinstance(expression.func, ast.Name)
        and expression.func.id in {"list", "tuple"}
        and len(expression.args) == 1
    ):
        return string_sequence(expression.args[0], constants)
    return None


def test_sdk_calls_require_empty_mode_tools_and_permissions() -> None:
    """Require SDK call sites to use the project's least-privilege defaults."""
    violations: list[str] = []

    for path in PACKAGE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        constants: dict[str, tuple[str, ...]] = {}
        for statement in tree.body:
            if (
                isinstance(statement, ast.Assign)
                and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name)
            ):
                resolved = string_sequence(statement.value, constants)
                if resolved is not None:
                    constants[statement.targets[0].id] = resolved
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = call_name(node)
            keywords = keyword_values(node)
            location = f"{path.relative_to(PACKAGE_ROOT)}:{node.lineno}"

            if name == "CopilotClient":
                mode = keywords.get("mode")
                if not isinstance(mode, ast.Constant) or mode.value != "empty":
                    violations.append(f"{location}: CopilotClient must use mode='empty'")

            if name in {"create_session", "create_agent_session"}:
                available_tools = keywords.get("available_tools")
                resolved_tools = (
                    string_sequence(available_tools, constants)
                    if available_tools is not None
                    else None
                )
                no_tool_session = resolved_tools == ()
                required = {
                    "available_tools",
                    "custom_agents",
                    "on_permission_request",
                    "skill_directories",
                    "tools",
                }
                if not no_tool_session:
                    required.update({"agent", "on_event"})
                missing = required - keywords.keys()
                if missing:
                    violations.append(f"{location}: {name} missing {', '.join(sorted(missing))}")
                if available_tools is not None:
                    uses_tool_names = (
                        isinstance(available_tools, ast.Call)
                        and isinstance(available_tools.func, ast.Name)
                        and available_tools.func.id == "list"
                        and len(available_tools.args) == 1
                        and isinstance(available_tools.args[0], ast.Name)
                        and available_tools.args[0].id == "TOOL_NAMES"
                    )
                    if resolved_tools is None and not uses_tool_names:
                        violations.append(
                            f"{location}: {name} available_tools is not statically resolvable"
                        )
                    elif resolved_tools is not None and resolved_tools not in {
                        (),
                        ("list_files", "read_file", "search"),
                    }:
                        violations.append(
                            f"{location}: {name} available_tools is not an approved exact set"
                        )

    assert not violations, "Unsafe SDK call sites:\n" + "\n".join(violations)


def test_declarative_asset_directories_contain_no_executable_python() -> None:
    """Keep agent definitions, prompts, and skills as data."""
    forbidden_suffixes = {".py", ".pyc", ".pth"}
    violations: list[str] = []

    for directory in ("agents", "system-prompts", "prompts", "skills", "tools", "policies"):
        asset_root = PACKAGE_ROOT / directory
        assert asset_root.is_dir(), f"Missing asset directory: {directory}"
        for path in asset_root.rglob("*"):
            if path.is_file() and (path.suffix in forbidden_suffixes or path.name == "conftest.py"):
                violations.append(str(path.relative_to(PACKAGE_ROOT)))

    assert not violations, "Executable files found in asset directories:\n" + "\n".join(violations)
