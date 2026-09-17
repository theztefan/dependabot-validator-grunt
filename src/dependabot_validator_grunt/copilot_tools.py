"""Typed executable tools exposed to the Copilot SDK."""

from __future__ import annotations

import json

from copilot import Tool, ToolInvocation, define_tool
from pydantic import BaseModel, ConfigDict

from dependabot_validator_grunt.agentic import RepositoryTools
from dependabot_validator_grunt.copilot_assets import (
    TOOL_NAMES,
    ToolDefinition,
)
from dependabot_validator_grunt.models import (
    AgentTask,
    ReachabilityEvidence,
    ReachabilityProfile,
    analysis_family,
)

type AnalyzerToolResult = ReachabilityEvidence | dict[str, object]


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


def task_analyzer_targets(task: AgentTask) -> tuple[str, ...]:
    """Return application-selected analyzer targets for one assigned task."""
    match analysis_family(task.ecosystem):
        case "javascript_typescript":
            return (task.package_name,)
        case "python":
            return tuple(target.value for target in task.import_targets)


def task_analyzer_profile(task: AgentTask) -> ReachabilityProfile:
    """Return the application-selected structural usage profile."""
    match analysis_family(task.ecosystem):
        case "javascript_typescript":
            return "npm"
        case "python":
            return "python"


def task_requires_analyzer(task: AgentTask) -> bool:
    """Return whether an accepted real-model attempt must invoke the analyzer."""
    match analysis_family(task.ecosystem):
        case "javascript_typescript":
            return True
        case "python":
            return any(target.authoritative for target in task.import_targets)


def validate_task_reachability(task: AgentTask, tools: RepositoryTools) -> None:
    """Validate the attempt-local analyzer ledger and task binding."""
    required = task_requires_analyzer(task)
    if required and tools.reachability_invocation_count < 1:
        raise ValueError("required reachability analysis was not invoked")
    evidence = tools.reachability_evidence
    if evidence is None:
        if required:
            raise ValueError("reachability evidence is missing")
        return
    if tools.reachability_invocation_count < 1:
        raise ValueError("reachability evidence has no invocation")
    if (
        evidence.snapshot_id != task.snapshot_id
        or evidence.package_name != task.package_name
        or evidence.profile != task_analyzer_profile(task)
        or evidence.target_identifiers != task_analyzer_targets(task)
        or evidence.analysis_root != task.analysis_root
    ):
        raise ValueError("reachability evidence does not match the assigned task")


def analyze_task_reachability(
    tools: RepositoryTools,
    task: AgentTask,
) -> AnalyzerToolResult:
    """Run task-bound analysis or return a fixed inapplicable result."""
    targets = task_analyzer_targets(task)
    if not targets:
        tools.reachability_invocation_count += 1
        return {
            "status": "inapplicable",
            "snapshot_id": task.snapshot_id,
            "package_name": task.package_name,
            "target_identifiers": [],
            "limitations": [
                "The task has no application-selected Python import target.",
                "This result cannot authorize applicability or non-applicability.",
            ],
        }
    return tools.analyze_reachability(
        snapshot_id=task.snapshot_id,
        package_name=task.package_name,
        profile=task_analyzer_profile(task),
        analysis_root=task.analysis_root,
        target_identifiers=targets,
    )


def repository_sdk_tools(
    tools: RepositoryTools,
    definitions: tuple[ToolDefinition, ...],
    task: AgentTask,
) -> list[Tool]:
    """Wrap the trusted bounded repository handlers as SDK custom tools."""
    descriptions = {definition.name: definition.description for definition in definitions}
    tool_names = tuple(descriptions)
    if tool_names != TOOL_NAMES:
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
        result = analyze_task_reachability(tools, task)
        if isinstance(result, ReachabilityEvidence):
            return result.model_dump_json()
        return json.dumps(result)

    registered = [
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
    ]
    if "analyze_reachability" in descriptions:
        registered.append(
            define_tool(
                "analyze_reachability",
                description=descriptions["analyze_reachability"],
                handler=analyze_reachability,
                params_type=AnalyzeReachabilityInput,
                overrides_built_in_tool=True,
                skip_permission=True,
                defer="never",
            )
        )
    return [tool for tool in registered if tool.name in tool_names]
