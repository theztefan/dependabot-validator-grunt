"""Package resource tests."""

import re
from importlib.resources import files
from importlib.resources.abc import Traversable

from dependabot_validator_grunt.copilot_assets import (
    AGENT_MANIFEST_ASSET,
    AGENT_PROMPT_ASSET,
    JUDGE_AGENT_MANIFEST_ASSET,
    JUDGE_AGENT_PROMPT_ASSET,
    JUDGE_PROMPT_TEMPLATE_ASSET,
    JUDGE_SKILL_ASSET,
    JUDGE_SYSTEM_PROMPT_ASSET,
    PROMPT_TEMPLATE_ASSET,
    SKILL_ASSET,
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
    AGENT_MANIFEST_ASSET,
    AGENT_PROMPT_ASSET,
    SYSTEM_PROMPT_ASSET,
    PROMPT_TEMPLATE_ASSET,
    SKILL_ASSET,
    TOOL_DEFINITIONS_ASSET,
    JUDGE_AGENT_MANIFEST_ASSET,
    JUDGE_AGENT_PROMPT_ASSET,
    JUDGE_PROMPT_TEMPLATE_ASSET,
    JUDGE_SKILL_ASSET,
    JUDGE_SYSTEM_PROMPT_ASSET,
    "policies/default.json",
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
