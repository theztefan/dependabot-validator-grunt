"""Package resource tests."""

import re
import tomllib
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

from dependabot_validator_grunt.agent_capabilities import CAPABILITY_CATALOG_ASSET
from dependabot_validator_grunt.copilot_assets import (
    AGENT_MANIFEST_ASSET,
    AGENT_PROMPT_ASSET,
    JAVASCRIPT_TYPESCRIPT_SKILL_ASSET,
    JUDGE_AGENT_MANIFEST_ASSET,
    JUDGE_AGENT_PROMPT_ASSET,
    JUDGE_PROMPT_TEMPLATE_ASSET,
    JUDGE_SKILL_ASSET,
    JUDGE_SYSTEM_PROMPT_ASSET,
    PROMPT_TEMPLATE_ASSET,
    PYTHON_SKILL_ASSET,
    SYSTEM_PROMPT_ASSET,
    TOOL_DEFINITIONS_ASSET,
)

ASSET_DIRECTORIES = (
    "agents",
    "system-prompts",
    "prompts",
    "skills",
    "tools",
    "policies",
)
EXPECTED_ASSETS = {
    CAPABILITY_CATALOG_ASSET,
    AGENT_MANIFEST_ASSET,
    AGENT_PROMPT_ASSET,
    SYSTEM_PROMPT_ASSET,
    PROMPT_TEMPLATE_ASSET,
    JAVASCRIPT_TYPESCRIPT_SKILL_ASSET,
    TOOL_DEFINITIONS_ASSET,
    PYTHON_SKILL_ASSET,
    JUDGE_AGENT_MANIFEST_ASSET,
    JUDGE_AGENT_PROMPT_ASSET,
    JUDGE_PROMPT_TEMPLATE_ASSET,
    JUDGE_SKILL_ASSET,
    JUDGE_SYSTEM_PROMPT_ASSET,
    "policies/default.json",
}
ROOT = Path(__file__).parents[1]
PYTHON_OFFLINE_FIXTURES = {
    "python-poetry-transitive-import",
    "python-uv-parent-only",
    "python-pip-compile-provenance",
    "python-distribution-import-mismatch",
}


def _asset_paths(directory: Traversable, prefix: str) -> list[str]:
    entries = directory.iterdir()
    assets: list[str] = []
    for entry in entries:
        if entry.is_dir():
            assets.extend(_asset_paths(entry, f"{prefix}/{entry.name}"))
        elif entry.name.casefold() != "readme.md":
            assets.append(f"{prefix}/{entry.name}")
    return assets


def test_declarative_asset_inventory_is_exact() -> None:
    """Reject missing and orphaned declarative package assets."""
    package = files("dependabot_validator_grunt")
    actual: set[str] = set()

    for directory in ASSET_DIRECTORIES:
        assets = _asset_paths(package.joinpath(directory), directory)
        assert assets, f"{directory} contains no packaged assets"
        actual.update(assets)

    assert actual == EXPECTED_ASSETS


def test_expected_agent_assets_are_packaged() -> None:
    """Require every explicit asset selected by the Copilot boundary."""
    package = files("dependabot_validator_grunt")
    for relative in sorted(EXPECTED_ASSETS):
        asset = package.joinpath(relative)
        assert asset.is_file(), f"missing packaged asset: {asset}"
        assert asset.read_text(encoding="utf-8").strip()


def test_prompt_template_has_one_supported_placeholder() -> None:
    """Keep prompt rendering literal and structurally bounded."""
    package = files("dependabot_validator_grunt")
    template = package.joinpath("prompts/dependency-investigation.md.tmpl").read_text(
        encoding="utf-8"
    )

    assert re.findall(r"\{\{([^{}]+)\}\}", template) == ["task_json"]
    assert template.count("```json") == 1


def test_python_offline_fixtures_are_included_in_source_distribution() -> None:
    """Keep production-shaped offline examples available from source releases."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    includes = project["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]

    assert "examples/offline-cases" in includes
    for fixture in PYTHON_OFFLINE_FIXTURES:
        root = ROOT / "examples" / "offline-cases" / fixture
        assert (root / "case.json").is_file()
        assert (root / "alert.json").is_file()
        assert (root / "request.json").is_file()
        assert (root / "agent-response.json").is_file()
        assert (root / "repository").is_dir()
