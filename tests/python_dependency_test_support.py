"""Shared fixtures and response builders for Python dependency tests."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
CASES = ROOT / "examples" / "offline-cases"


def write_poetry_project(
    root: Path,
    *,
    dependency: str = 'requests = ">=2.31,<3"',
    package: str = """
[[package]]
name = "requests"
version = "2.31.0"
optional = false
groups = ["main"]
""",
    extra_pyproject: str = "",
) -> None:
    (root / "pyproject.toml").write_text(
        f"""
[tool.poetry]
name = "example"
version = "0.1.0"
{extra_pyproject}

[tool.poetry.dependencies]
python = "^3.12"
{dependency}
""",
        encoding="utf-8",
    )
    (root / "poetry.lock").write_text(
        f"""{package}

[metadata]
lock-version = "2.1"
python-versions = "^3.12"
content-hash = "unverified"
""",
        encoding="utf-8",
    )


def python_agent_response(
    recommendation: str,
    reason_code: str,
    *,
    query: str | None = None,
    analyze: bool = True,
    insufficient_context: bool = False,
) -> dict[str, object]:
    tool_calls: list[dict[str, object]] = []
    if analyze:
        tool_calls.append({"name": "analyze_reachability", "arguments": {}})
    if query is not None:
        tool_calls.append({"name": "search", "arguments": {"query": query, "path": "."}})
    return {
        "tool_calls": tool_calls,
        "finding": {
            "workflow_mode": "$task.workflow_mode",
            "correlation_id": "$task.correlation_id",
            "repository_id": "$task.repository_id",
            "alert_number": "$task.alert_number",
            "request_id": "$task.request_id",
            "snapshot_id": "$task.snapshot_id",
            "policy_digest": "$task.policy_digest",
            "claim": "Repository evidence supports the Python dependency assessment.",
            "citations": "$observations",
            "uncertainty": "Python use remains uncertain." if insufficient_context else "",
            "proposed_recommendation": recommendation,
            "policy_reason_code": reason_code,
            "confidence": 0.9,
            "insufficient_context": insufficient_context,
            "injection_detected": False,
        },
    }


def write_uv_project(
    root: Path,
    *,
    dependency: str = '"requests>=2"',
    package: str = """
[[package]]
name = "requests"
version = "2.31.0"
source = { registry = "https://pypi.org/simple" }
""",
    extra_pyproject: str = "",
    revision: int = 3,
    lock_version: str = "1",
) -> None:
    (root / "pyproject.toml").write_text(
        f"""
[project]
name = "example"
version = "0.1.0"
dependencies = [{dependency}]

{extra_pyproject}
""",
        encoding="utf-8",
    )
    (root / "uv.lock").write_text(
        f"""
version = {lock_version}
revision = {revision}
requires-python = ">=3.12"

{package}
""",
        encoding="utf-8",
    )
