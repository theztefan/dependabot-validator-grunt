"""Validated declarative assets for the Copilot SDK boundary."""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Generator
from contextlib import contextmanager
from importlib.resources import as_file, files
from importlib.resources.abc import Traversable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, TypeAdapter

from dependabot_validator_grunt.models import AgentTask, canonical_json

AGENT_MANIFEST_ASSET = "agents/dependency-risk-investigator/agent.json"
AGENT_PROMPT_ASSET = "agents/dependency-risk-investigator/prompt.md"
SYSTEM_PROMPT_ASSET = "system-prompts/dependency-risk-session.md"
PROMPT_TEMPLATE_ASSET = "prompts/dependency-investigation.md.tmpl"
SKILL_ASSET = "skills/dependency-risk-analysis/SKILL.md"
JUDGE_AGENT_MANIFEST_ASSET = "agents/dependency-risk-judge/agent.json"
JUDGE_AGENT_PROMPT_ASSET = "agents/dependency-risk-judge/prompt.md"
JUDGE_SYSTEM_PROMPT_ASSET = "system-prompts/dependency-risk-judge.md"
JUDGE_PROMPT_TEMPLATE_ASSET = "prompts/dependency-judge.md.tmpl"
JUDGE_SKILL_ASSET = "skills/dependency-risk-review/SKILL.md"
SKILLS_ASSET_ROOT = "skills"
TOOL_DEFINITIONS_ASSET = "tools/repository-tools.json"
TASK_PLACEHOLDER = "{{task_json}}"
JUDGE_PLACEHOLDER = "{{judge_json}}"
TOOL_NAMES = ("list_files", "read_file", "search", "analyze_reachability")
JUDGE_TOOL_NAMES: tuple[str, ...] = ()
SKILL_NAME = "dependency-risk-analysis"
JUDGE_SKILL_NAME = "dependency-risk-review"
AGENT_NAME = "dependency-risk-investigator"
JUDGE_AGENT_NAME = "dependency-risk-judge"
MAX_STATIC_INSTRUCTION_CHARACTERS = 8_192
_TASK_BLOCK = re.compile(r"```json\n(?P<task>.*?)\n```", re.DOTALL)


class CopilotConfigurationError(ValueError):
    """Invalid real-Copilot configuration discovered at runtime."""


class AgentManifest(BaseModel):
    """Declarative SDK custom-agent configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    display_name: str
    description: str
    prompt_asset: str
    tools: tuple[str, ...]
    skills: tuple[str, ...]
    infer: bool


class ToolDefinition(BaseModel):
    """Model-facing metadata for one trusted Python tool handler."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    description: str


class ToolDefinitions(BaseModel):
    """Declarative repository tool collection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tools: tuple[ToolDefinition, ...]


class CopilotRoleAssets(BaseModel):
    """Validated declarative assets for one explicit Copilot role."""

    model_config = ConfigDict(frozen=True)

    agent: AgentManifest
    agent_prompt: str
    system_prompt: str
    prompt_template: str
    tool_definitions: tuple[ToolDefinition, ...]
    skill_asset: str
    skill_name: str
    static_instruction_characters: int


CopilotAssets = CopilotRoleAssets


def package_resource(relative_path: str) -> Traversable:
    """Return one package resource without assuming a filesystem install."""
    return files("dependabot_validator_grunt").joinpath(*relative_path.split("/"))


def read_package_asset(relative_path: str) -> str:
    """Read one non-empty UTF-8 asset from the installed package."""
    try:
        content = package_resource(relative_path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise CopilotConfigurationError(f"unable to load Copilot asset: {relative_path}") from error
    if not content.strip():
        raise CopilotConfigurationError(f"Copilot asset is empty: {relative_path}")
    return content.replace("\r\n", "\n")


def _load_json_asset(relative_path: str, model: type[BaseModel]) -> BaseModel:
    try:
        return model.model_validate_json(read_package_asset(relative_path))
    except CopilotConfigurationError:
        raise
    except ValueError as error:
        raise CopilotConfigurationError(f"Copilot asset is invalid: {relative_path}") from error


def _skill_metadata(skill: str) -> dict[str, str]:
    if not skill.startswith("---\n"):
        raise CopilotConfigurationError("Copilot skill is missing metadata")
    metadata_text, separator, body = skill[4:].partition("\n---\n")
    if not separator or not body.strip():
        raise CopilotConfigurationError("Copilot skill metadata or body is invalid")
    metadata: dict[str, str] = {}
    for line in metadata_text.splitlines():
        key, separator, value = line.partition(":")
        if not separator or not key.strip() or not value.strip():
            raise CopilotConfigurationError("Copilot skill metadata is invalid")
        metadata[key.strip()] = value.strip()
    if set(metadata) != {"name", "description"}:
        raise CopilotConfigurationError("Copilot skill metadata fields are invalid")
    return metadata


def _validate_prompt_template(template: str, placeholder: str, placeholder_name: str) -> None:
    placeholders = re.findall(r"\{\{([^{}]+)\}\}", template)
    if placeholders != [placeholder_name] or template.count(placeholder) != 1:
        raise CopilotConfigurationError(
            f"Copilot prompt must contain exactly one {placeholder_name} placeholder"
        )
    matches = tuple(_TASK_BLOCK.finditer(template))
    if len(matches) != 1 or matches[0].group("task").strip() != placeholder:
        raise CopilotConfigurationError(
            f"Copilot prompt must contain one fenced {placeholder_name} block"
        )


def _instruction_character_count(*assets: str) -> int:
    return sum(len(asset) for asset in assets)


def _load_role_assets(
    *,
    manifest_asset: str,
    expected_agent_name: str,
    expected_prompt_asset: str,
    system_prompt_asset: str,
    prompt_template_asset: str,
    prompt_placeholder: str,
    prompt_placeholder_name: str,
    skill_asset: str,
    expected_skill_name: str,
    expected_tool_names: tuple[str, ...],
    include_repository_tools: bool,
) -> CopilotRoleAssets:
    agent = AgentManifest.model_validate(_load_json_asset(manifest_asset, AgentManifest))
    tool_definitions: tuple[ToolDefinition, ...] = ()
    declared_tool_names: tuple[str, ...] = ()
    if include_repository_tools:
        tool_collection = ToolDefinitions.model_validate(
            _load_json_asset(TOOL_DEFINITIONS_ASSET, ToolDefinitions)
        )
        tool_definitions = tool_collection.tools
        declared_tool_names = tuple(tool.name for tool in tool_definitions)
    agent_prompt = read_package_asset(agent.prompt_asset)
    system_prompt = read_package_asset(system_prompt_asset)
    prompt_template = read_package_asset(prompt_template_asset)
    skill = read_package_asset(skill_asset)
    _validate_prompt_template(
        prompt_template,
        prompt_placeholder,
        prompt_placeholder_name,
    )
    skill_metadata = _skill_metadata(skill)

    if agent.name != expected_agent_name:
        raise CopilotConfigurationError("Copilot custom-agent name is invalid")
    if agent.prompt_asset != expected_prompt_asset:
        raise CopilotConfigurationError("Copilot custom-agent prompt asset is invalid")
    if agent.infer:
        raise CopilotConfigurationError("Copilot custom-agent inference must be disabled")
    if agent.skills != (expected_skill_name,):
        raise CopilotConfigurationError("Copilot custom-agent skill binding is invalid")
    if skill_metadata["name"] != expected_skill_name:
        raise CopilotConfigurationError("Copilot skill name is invalid")
    if declared_tool_names != expected_tool_names or agent.tools != expected_tool_names:
        raise CopilotConfigurationError("Copilot custom-agent tool declarations do not match")
    if len(set(declared_tool_names)) != len(declared_tool_names):
        raise CopilotConfigurationError("Copilot custom-agent tool names must be unique")
    static_instruction_characters = _instruction_character_count(
        agent.name,
        agent.display_name,
        agent.description,
        *agent.tools,
        *agent.skills,
        agent_prompt,
        system_prompt,
        prompt_template,
        skill,
        *(value for tool in tool_definitions for value in (tool.name, tool.description)),
    )
    if static_instruction_characters > MAX_STATIC_INSTRUCTION_CHARACTERS:
        raise CopilotConfigurationError("Copilot static instructions exceed the character limit")

    return CopilotRoleAssets(
        agent=agent,
        agent_prompt=agent_prompt,
        system_prompt=system_prompt,
        prompt_template=prompt_template,
        tool_definitions=tool_definitions,
        skill_asset=skill_asset,
        skill_name=expected_skill_name,
        static_instruction_characters=static_instruction_characters,
    )


def load_copilot_assets() -> CopilotRoleAssets:
    """Load and validate the explicit investigator role."""
    return _load_role_assets(
        manifest_asset=AGENT_MANIFEST_ASSET,
        expected_agent_name=AGENT_NAME,
        expected_prompt_asset=AGENT_PROMPT_ASSET,
        system_prompt_asset=SYSTEM_PROMPT_ASSET,
        prompt_template_asset=PROMPT_TEMPLATE_ASSET,
        prompt_placeholder=TASK_PLACEHOLDER,
        prompt_placeholder_name="task_json",
        skill_asset=SKILL_ASSET,
        expected_skill_name=SKILL_NAME,
        expected_tool_names=TOOL_NAMES,
        include_repository_tools=True,
    )


def load_judge_assets() -> CopilotRoleAssets:
    """Load and validate the explicit no-tool judge role."""
    return _load_role_assets(
        manifest_asset=JUDGE_AGENT_MANIFEST_ASSET,
        expected_agent_name=JUDGE_AGENT_NAME,
        expected_prompt_asset=JUDGE_AGENT_PROMPT_ASSET,
        system_prompt_asset=JUDGE_SYSTEM_PROMPT_ASSET,
        prompt_template_asset=JUDGE_PROMPT_TEMPLATE_ASSET,
        prompt_placeholder=JUDGE_PLACEHOLDER,
        prompt_placeholder_name="judge_json",
        skill_asset=JUDGE_SKILL_ASSET,
        expected_skill_name=JUDGE_SKILL_NAME,
        expected_tool_names=JUDGE_TOOL_NAMES,
        include_repository_tools=False,
    )


def render_task_prompt(template: str, task: AgentTask) -> str:
    """Render a dispatch prompt and round-trip its fenced task."""
    rendered = template.replace(TASK_PLACEHOLDER, canonical_json(task))
    matches = tuple(_TASK_BLOCK.finditer(rendered))
    if len(matches) != 1:
        raise CopilotConfigurationError("Copilot prompt rendered an invalid task block")
    try:
        rendered_task = AgentTask.model_validate(
            TypeAdapter(dict[str, object]).validate_python(json.loads(matches[0].group("task")))
        )
    except (ValueError, TypeError) as error:
        raise CopilotConfigurationError(
            "Copilot prompt template rendered invalid task JSON"
        ) from error
    if rendered_task != task:
        raise CopilotConfigurationError("Copilot prompt task does not match assigned task")
    return rendered


@contextmanager
def materialized_skill_root(
    destination: Path,
    skill_name: str = SKILL_NAME,
) -> Generator[Path]:
    """Materialize one explicit packaged skill under the isolated state directory."""
    if skill_name not in {SKILL_NAME, JUDGE_SKILL_NAME}:
        raise CopilotConfigurationError("Copilot skill selection is invalid")
    target = destination / "skills"
    selected_skill = target / skill_name
    try:
        target.mkdir()
        with as_file(package_resource(f"{SKILLS_ASSET_ROOT}/{skill_name}")) as source:
            shutil.copytree(source, selected_skill)
    except (OSError, TypeError) as error:
        raise CopilotConfigurationError("unable to materialize Copilot skills") from error
    try:
        yield target
    finally:
        shutil.rmtree(target, ignore_errors=True)
