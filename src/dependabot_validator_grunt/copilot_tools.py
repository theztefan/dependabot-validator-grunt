"""Typed executable tools exposed to the Copilot SDK."""

from __future__ import annotations

import json

from copilot import Tool, ToolInvocation, define_tool
from pydantic import BaseModel, ConfigDict

from dependabot_validator_grunt.agentic import RepositoryTools
from dependabot_validator_grunt.copilot_assets import TOOL_NAMES, ToolDefinition
from dependabot_validator_grunt.models import AgentTask


class ListFilesInput(BaseModel):
    """Validated list-files tool input."""

    model_config = ConfigDict(extra="forbid")
    path: str = "."


class ReadFileInput(BaseModel):
    """Validated read-file tool input."""

    model_config = ConfigDict(extra="forbid")
    path: str


class SearchInput(BaseModel):
    """Validated repository-search tool input."""

    model_config = ConfigDict(extra="forbid")
    query: str
    path: str = "."


class AnalyzeReachabilityInput(BaseModel):
    """Parameter-free task-bound structural analysis request."""

    model_config = ConfigDict(extra="forbid")


def repository_sdk_tools(
    tools: RepositoryTools,
    definitions: tuple[ToolDefinition, ...],
    task: AgentTask,
) -> list[Tool]:
    """Wrap the trusted bounded repository handlers as SDK custom tools."""
    descriptions = {definition.name: definition.description for definition in definitions}
    if tuple(descriptions) != TOOL_NAMES:
        raise ValueError("repository tool definitions do not match trusted handlers")

    def list_files(parameters: ListFilesInput, invocation: ToolInvocation) -> str:
        del invocation
        return json.dumps(tools.list_files(parameters.path))

    def read_file(parameters: ReadFileInput, invocation: ToolInvocation) -> str:
        del invocation
        return tools.read_file(parameters.path)

    def search(parameters: SearchInput, invocation: ToolInvocation) -> str:
        del invocation
        facts = tools.search(parameters.query, parameters.path)
        return json.dumps([fact.model_dump(mode="json") for fact in facts])

    def analyze_reachability(
        parameters: AnalyzeReachabilityInput,
        invocation: ToolInvocation,
    ) -> str:
        del parameters, invocation
        evidence = tools.analyze_reachability(
            snapshot_id=task.snapshot_id,
            package_name=task.package_name,
        )
        return evidence.model_dump_json()

    return [
        define_tool(
            "list_files",
            description=descriptions["list_files"],
            handler=list_files,
            params_type=ListFilesInput,
            overrides_built_in_tool=True,
            skip_permission=True,
            defer="never",
        ),
        define_tool(
            "read_file",
            description=descriptions["read_file"],
            handler=read_file,
            params_type=ReadFileInput,
            overrides_built_in_tool=True,
            skip_permission=True,
            defer="never",
        ),
        define_tool(
            "search",
            description=descriptions["search"],
            handler=search,
            params_type=SearchInput,
            overrides_built_in_tool=True,
            skip_permission=True,
            defer="never",
        ),
        define_tool(
            "analyze_reachability",
            description=descriptions["analyze_reachability"],
            handler=analyze_reachability,
            params_type=AnalyzeReachabilityInput,
            overrides_built_in_tool=True,
            skip_permission=True,
            defer="never",
        ),
    ]
