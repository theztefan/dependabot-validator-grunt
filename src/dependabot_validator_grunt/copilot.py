"""Copilot model-turn boundary and scripted offline fake."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from copilot import CopilotClient, PermissionRequest
from copilot.generated.rpc import PermissionDecisionReject
from copilot.session import CustomAgentConfig, PermissionInvocation
from copilot.session_events import (
    AssistantMessageData,
    SessionCustomAgentsUpdatedData,
    SessionEvent,
    SessionEventType,
    SessionSkillsLoadedData,
    SkillSource,
    SubagentSelectedData,
)
from pydantic import TypeAdapter, ValidationError

from dependabot_validator_grunt.agentic import RepositoryTools, validate_finding
from dependabot_validator_grunt.copilot_assets import (
    TOOL_NAMES,
    CopilotConfigurationError,
    load_copilot_assets,
    load_judge_assets,
    materialized_skill_root,
    render_task_prompt,
)
from dependabot_validator_grunt.copilot_tools import repository_sdk_tools
from dependabot_validator_grunt.judge import (
    MAX_JUDGE_OUTPUT_CHARACTERS,
    render_judge_prompt,
)
from dependabot_validator_grunt.models import (
    AgentFinding,
    AgentTask,
    JudgeFailure,
    JudgeReview,
)

RUNTIME_ENVIRONMENT_NAMES = (
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "TMPDIR",
    "TMP",
    "TEMP",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
)
ASSET_LOAD_TIMEOUT_SECONDS = 5.0
DISABLED_BUILTIN_SKILLS = (
    "customize-cloud-agent",
    "github-pr-media",
)


class ModelTurn(Protocol):
    """Boundary replaced by the scripted fake in default offline tests."""

    identity: str

    async def run(
        self,
        task: AgentTask,
        tools: RepositoryTools,
        *,
        max_attempts: int,
        wall_clock_seconds: int,
    ) -> dict[str, object]:
        """Run one bounded investigation turn."""
        ...


class ScriptedModelTurn:
    """Execute fixture-declared tool calls and return the complete raw response."""

    identity = "scripted-fixture"

    def __init__(self, response_path: Path) -> None:
        self.response_path = response_path

    async def run(
        self,
        task: AgentTask,
        tools: RepositoryTools,
        *,
        max_attempts: int,
        wall_clock_seconds: int,
    ) -> dict[str, object]:
        del max_attempts, wall_clock_seconds
        raw = TypeAdapter(dict[str, object]).validate_python(
            json.loads(self.response_path.read_text(encoding="utf-8"))
        )
        calls = TypeAdapter(list[dict[str, object]]).validate_python(raw.get("tool_calls", []))
        observations: list[dict[str, object]] = []
        call_adapter = TypeAdapter(dict[str, object])
        for call in calls:
            name, arguments = call.get("name"), call.get("arguments", {})
            arguments = call_adapter.validate_python(arguments)
            if name == "list_files":
                tools.list_files(str(arguments.get("path", ".")))
            elif name == "read_file":
                tools.read_file(str(arguments["path"]))
            elif name == "search":
                facts = tools.search(
                    str(arguments["query"]),
                    str(arguments.get("path", ".")),
                )
                observations.extend(fact.model_dump(mode="json") for fact in facts)
            elif name == "analyze_reachability":
                tools.analyze_reachability(
                    snapshot_id=task.snapshot_id,
                    package_name=task.package_name,
                )
            else:
                raise ValueError(f"unlisted tool requested: {name}")
        raw_finding = raw.get("finding")
        if not isinstance(raw_finding, dict):
            return raw
        finding = call_adapter.validate_python(raw_finding)
        replacements: dict[str, object] = {
            "$task.workflow_mode": task.workflow_mode,
            "$task.correlation_id": task.correlation_id,
            "$task.repository_id": task.repository_id,
            "$task.alert_number": task.alert_number,
            "$task.request_id": task.request_id,
            "$task.snapshot_id": task.snapshot_id,
            "$task.policy_digest": task.policy_digest,
        }
        for key, value in tuple(finding.items()):
            if isinstance(value, str) and value in replacements:
                finding[key] = replacements[value]
        if finding.get("citations") == "$observations":
            finding["citations"] = observations
        raw["finding"] = finding
        return raw


AttemptOutcome = Literal[
    "success",
    "timeout",
    "missing_response",
    "malformed_output",
    "sdk_failure",
]


def parse_model_output(content: str) -> dict[str, object]:
    """Extract exactly one JSON object from an otherwise untrusted response."""
    try:
        complete = json.loads(content)
    except json.JSONDecodeError:
        pass
    else:
        if not isinstance(complete, dict):
            raise ValueError("response JSON must be an object")
        return TypeAdapter(dict[str, object]).validate_python(complete)
    decoder = json.JSONDecoder()
    parsed: dict[str, object] | None = None
    parsed_end = 0
    for index, character in enumerate(content):
        if character != "{":
            continue
        try:
            candidate, end = decoder.raw_decode(content, index)
        except json.JSONDecodeError:
            continue
        if not isinstance(candidate, dict):
            continue
        parsed = TypeAdapter(dict[str, object]).validate_python(candidate)
        parsed_end = end
        break
    if parsed is None:
        raise json.JSONDecodeError("response contains no JSON object", content, 0)
    for index in range(parsed_end, len(content)):
        if content[index] != "{":
            continue
        try:
            candidate, _ = decoder.raw_decode(content, index)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            raise json.JSONDecodeError("response contains multiple JSON objects", content, index)
    return parsed


@dataclass(frozen=True)
class CopilotAttempt:
    """One classified real-Copilot attempt."""

    number: int
    outcome: AttemptOutcome


class MissingResponseError(ValueError):
    """The SDK session became idle without a final assistant message."""


class CopilotTurnError(ValueError):
    """Exhausted real-Copilot attempts with safe diagnostic state."""

    def __init__(
        self,
        message: str,
        attempts: tuple[CopilotAttempt, ...],
        raw_outputs: tuple[str, ...],
    ) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.raw_outputs = raw_outputs

    def artifact(self) -> dict[str, object]:
        """Return a JSON-safe raw failure artifact."""
        return {
            "attempts": [
                {"number": attempt.number, "outcome": attempt.outcome} for attempt in self.attempts
            ],
            "raw_outputs": list(self.raw_outputs),
        }


def allowlisted_copilot_environment(
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return only non-secret runtime variables needed by the SDK child."""
    environment = os.environ if source is None else source
    return {name: environment[name] for name in RUNTIME_ENVIRONMENT_NAMES if name in environment}


def reject_permission_request(
    request: PermissionRequest,
    invocation: PermissionInvocation,
) -> PermissionDecisionReject:
    """Reject every permission request; custom read tools require no escalation."""
    del request, invocation
    return PermissionDecisionReject(feedback="permission is not allowlisted")


@dataclass(eq=False)
class SessionAssetObserver:
    """Capture SDK events required before dispatch and response acceptance."""

    expected_agent: str
    expected_tools: tuple[str, ...]
    expected_skill: str
    agent_id: str | None = None
    agent_selected: bool = False
    skills_seen: bool = False
    deselected: bool = False
    error: str | None = None
    agent_ready: asyncio.Event = field(default_factory=asyncio.Event)
    ready: asyncio.Event = field(default_factory=asyncio.Event)

    def __call__(self, event: SessionEvent) -> None:
        if event.type is SessionEventType.SESSION_CUSTOM_AGENTS_UPDATED:
            if not isinstance(event.data, SessionCustomAgentsUpdatedData):
                self.error = "Copilot custom-agent event is invalid"
            elif event.data.errors or event.data.warnings or len(event.data.agents) != 1:
                self.error = "Copilot custom-agent loading failed"
            else:
                agent = event.data.agents[0]
                if (
                    agent.name != self.expected_agent
                    or agent.source != "custom"
                    or agent.tools != list(self.expected_tools)
                ):
                    self.error = "Copilot loaded the wrong custom agent"
                else:
                    self.agent_id = agent.id
        elif event.type is SessionEventType.SUBAGENT_SELECTED:
            if not isinstance(event.data, SubagentSelectedData):
                self.error = "Copilot selected-agent event is invalid"
            elif event.data.agent_name != self.expected_agent or event.data.tools != list(
                self.expected_tools
            ):
                self.error = "Copilot selected the wrong custom agent"
            else:
                self.agent_selected = True
        elif event.type is SessionEventType.SESSION_SKILLS_LOADED:
            self.skills_seen = True
            if not isinstance(event.data, SessionSkillsLoadedData):
                self.error = "Copilot skills event is invalid"
            else:
                enabled_skills = [skill for skill in event.data.skills if skill.enabled]
                disabled_skills = [skill for skill in event.data.skills if not skill.enabled]
                if len(enabled_skills) != 1:
                    self.error = "Copilot loaded unexpected skills"
                elif (
                    enabled_skills[0].name != self.expected_skill
                    or enabled_skills[0].source is not SkillSource.CUSTOM
                ):
                    self.error = "Copilot loaded an untrusted skill"
                elif any(skill.source is not SkillSource.BUILTIN for skill in disabled_skills) or (
                    len(disabled_skills) != len(DISABLED_BUILTIN_SKILLS)
                    or {skill.name for skill in disabled_skills} != set(DISABLED_BUILTIN_SKILLS)
                ):
                    self.error = "Copilot reported unexpected disabled skills"
        elif event.type is SessionEventType.SUBAGENT_DESELECTED:
            self.deselected = True
        if self.error is not None or self.deselected or self.agent_selected:
            self.agent_ready.set()
        if self.error is not None or self.deselected:
            self.ready.set()
        if self.agent_selected and self.skills_seen:
            self.ready.set()

    def validate_agent_selected(self) -> None:
        """Require the exact selected custom agent before task dispatch."""
        if self.error is not None:
            raise CopilotConfigurationError(self.error)
        if not self.agent_selected:
            raise CopilotConfigurationError("Copilot custom-agent selection was not confirmed")
        if self.deselected:
            raise CopilotConfigurationError("Copilot custom agent was deselected")

    def validate_loaded(self) -> None:
        """Require exact selected-agent and skill state before accepting output."""
        self.validate_agent_selected()
        if not self.skills_seen:
            raise CopilotConfigurationError("Copilot skill load was not confirmed")

    async def wait_until_agent_selected(self, timeout_seconds: float) -> None:
        """Wait for selected-agent confirmation before task dispatch."""
        try:
            async with asyncio.timeout(min(timeout_seconds, ASSET_LOAD_TIMEOUT_SECONDS)):
                await self.agent_ready.wait()
        except TimeoutError:
            self.validate_agent_selected()
            raise CopilotConfigurationError(
                "Copilot custom-agent selection did not complete"
            ) from None
        self.validate_agent_selected()

    async def wait_until_loaded(self, timeout_seconds: float) -> None:
        """Wait for selected-agent and skill confirmation before accepting output."""
        try:
            async with asyncio.timeout(min(timeout_seconds, ASSET_LOAD_TIMEOUT_SECONDS)):
                await self.ready.wait()
        except TimeoutError:
            self.validate_loaded()
            raise CopilotConfigurationError("Copilot asset loading did not complete") from None
        self.validate_loaded()


class CopilotModelTurn:
    """Real least-privilege Copilot SDK implementation of one model turn."""

    def __init__(
        self,
        github_token: str,
        *,
        model: str | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        if not github_token:
            raise CopilotConfigurationError("COPILOT_GITHUB_TOKEN is required")
        self.github_token = github_token
        self.model = model
        self.environment = allowlisted_copilot_environment(environment)
        self.assets = load_copilot_assets()
        self.identity = f"copilot:{model or 'runtime-default'}"
        self.attempts: tuple[CopilotAttempt, ...] = ()

    async def run(
        self,
        task: AgentTask,
        tools: RepositoryTools,
        *,
        max_attempts: int,
        wall_clock_seconds: int,
    ) -> dict[str, object]:
        prompt = render_task_prompt(self.assets.prompt_template, task)
        deadline = time.monotonic() + wall_clock_seconds
        attempts: list[CopilotAttempt] = []
        raw_outputs: list[str] = []
        last_error = "Copilot turn failed"

        for attempt_number in range(1, max_attempts + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                attempts.append(CopilotAttempt(attempt_number, "timeout"))
                last_error = "Copilot wall-clock limit exceeded"
                break
            try:
                attempt_tools = RepositoryTools(
                    tools.root,
                    max_read_bytes=tools.max_read_bytes,
                    max_results=tools.max_results,
                    max_session_bytes=tools.max_session_bytes,
                    max_proof_scan_bytes=tools.max_proof_scan_bytes,
                    reachability_runner=tools.reachability_runner,
                    analyzer_wall_seconds=tools.analyzer_wall_seconds,
                    max_analyzer_files=tools.max_analyzer_files,
                    max_analyzer_input_bytes=tools.max_analyzer_input_bytes,
                    max_analyzer_output_bytes=tools.max_analyzer_output_bytes,
                    max_analyzer_stderr_bytes=tools.max_analyzer_stderr_bytes,
                    max_analyzer_findings=tools.max_analyzer_findings,
                )
                async with asyncio.timeout(remaining):
                    content, observed_model = await self._run_attempt(
                        prompt,
                        attempt_tools,
                        task,
                        remaining,
                    )
                raw_outputs.append(content)
                raw = parse_model_output(content)
                if attempt_tools.reachability_invocation_count < 1:
                    raise ValueError("required reachability analysis was not invoked")
                raw_finding = TypeAdapter(dict[str, object]).validate_python(raw.get("finding"))
                validate_finding(raw_finding, task, attempt_tools)
                if attempt_tools.reachability_evidence is None:
                    raise ValueError("reachability evidence is missing")
            except asyncio.CancelledError:
                self.attempts = tuple(attempts)
                raise
            except TimeoutError:
                attempts.append(CopilotAttempt(attempt_number, "timeout"))
                last_error = "Copilot attempt timed out"
                continue
            except CopilotConfigurationError:
                self.attempts = tuple(attempts)
                raise
            except MissingResponseError as error:
                attempts.append(CopilotAttempt(attempt_number, "missing_response"))
                last_error = str(error)
                continue
            except json.JSONDecodeError:
                attempts.append(CopilotAttempt(attempt_number, "malformed_output"))
                last_error = "Copilot returned malformed JSON"
                continue
            except ValueError:
                attempts.append(CopilotAttempt(attempt_number, "malformed_output"))
                last_error = "Copilot returned a non-object JSON response"
                continue
            except Exception as error:
                attempts.append(CopilotAttempt(attempt_number, "sdk_failure"))
                last_error = f"Copilot SDK failure ({type(error).__name__})"
                continue

            attempts.append(CopilotAttempt(attempt_number, "success"))
            self.attempts = tuple(attempts)
            tools.observations.update(attempt_tools.observations)
            tools.reachability_invoked = attempt_tools.reachability_invoked
            tools.reachability_invocation_count = attempt_tools.reachability_invocation_count
            tools.reachability_evidence = attempt_tools.reachability_evidence
            if observed_model:
                self.identity = f"copilot:{observed_model}"
            return {**raw, "raw_content": content}

        self.attempts = tuple(attempts)
        raise CopilotTurnError(last_error, self.attempts, tuple(raw_outputs))

    async def _run_attempt(
        self,
        prompt: str,
        tools: RepositoryTools,
        task: AgentTask,
        remaining_seconds: float,
    ) -> tuple[str, str | None]:
        with tempfile.TemporaryDirectory(prefix="dependabot-validator-copilot-") as state_dir:
            state_path = Path(state_dir)
            with materialized_skill_root(state_path, self.assets.skill_name) as skill_root:
                async with CopilotClient(
                    mode="empty",
                    env=self.environment,
                    github_token=self.github_token,
                    base_directory=state_dir,
                    use_logged_in_user=False,
                    builtin_plugin_directories=[],
                    enable_remote_sessions=False,
                ) as client:
                    models = await client.list_models()
                    available_model_ids = {model.id for model in models}
                    if self.model is not None and self.model not in available_model_ids:
                        raise CopilotConfigurationError(
                            f"requested Copilot model is unavailable: {self.model}"
                        )
                    sdk_tools = repository_sdk_tools(tools, self.assets.tool_definitions, task)
                    if tuple(tool.name for tool in sdk_tools) != TOOL_NAMES:
                        raise CopilotConfigurationError(
                            "constructed Copilot tools do not match the allowlist"
                        )
                    observer = SessionAssetObserver(
                        expected_agent=self.assets.agent.name,
                        expected_tools=TOOL_NAMES,
                        expected_skill=self.assets.skill_name,
                    )
                    custom_agent: CustomAgentConfig = {
                        "name": self.assets.agent.name,
                        "display_name": self.assets.agent.display_name,
                        "description": self.assets.agent.description,
                        "prompt": self.assets.agent_prompt,
                        "tools": list(self.assets.agent.tools),
                        "skills": list(self.assets.agent.skills),
                        "infer": self.assets.agent.infer,
                    }
                    async with await client.create_session(
                        model=self.model,
                        tools=sdk_tools,
                        available_tools=list(TOOL_NAMES),
                        on_permission_request=reject_permission_request,
                        on_event=observer,
                        system_message={
                            "mode": "append",
                            "content": self.assets.system_prompt,
                        },
                        tool_search={"enabled": False},
                        working_directory=str(tools.root),
                        enable_experimental_mode=False,
                        enable_session_telemetry=False,
                        enable_citations=False,
                        enable_file_change_tracking=False,
                        skip_custom_instructions=True,
                        custom_agents_local_only=True,
                        coauthor_enabled=False,
                        manage_schedule_enabled=False,
                        mcp_servers={},
                        mcp_oauth_token_storage="in-memory",
                        embedding_cache_storage="in-memory",
                        custom_agents=[custom_agent],
                        default_agent={"excluded_tools": list(TOOL_NAMES)},
                        agent=self.assets.agent.name,
                        commands=[],
                        enable_config_discovery=False,
                        skip_embedding_retrieval=True,
                        organization_custom_instructions="",
                        enable_on_demand_instruction_discovery=False,
                        enable_file_hooks=False,
                        enable_host_git_operations=False,
                        enable_session_store=False,
                        enable_skills=True,
                        skill_directories=[str(skill_root)],
                        plugin_directories=[],
                        instruction_directories=[],
                        disabled_skills=list(DISABLED_BUILTIN_SKILLS),
                        large_output={"enabled": False},
                        memory={"enabled": False},
                        enable_mcp_apps=False,
                        request_canvas_renderer=False,
                        request_extensions=False,
                        enable_managed_settings=False,
                    ) as session:
                        await observer.wait_until_agent_selected(remaining_seconds)
                        event = await session.send_and_wait(
                            prompt,
                            timeout=remaining_seconds,
                        )
                        await observer.wait_until_loaded(remaining_seconds)
                    if event is None or not isinstance(event.data, AssistantMessageData):
                        raise MissingResponseError("Copilot returned no final assistant message")
                    if observer.agent_id is not None and event.agent_id != observer.agent_id:
                        raise CopilotConfigurationError(
                            "Copilot response came from the wrong agent"
                        )
                    return event.data.content, event.data.model


class CopilotFindingJudge:
    """Strict no-tool Copilot session for the two-critic judge forum."""

    def __init__(
        self,
        github_token: str,
        *,
        model: str | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        if not github_token:
            raise CopilotConfigurationError("COPILOT_GITHUB_TOKEN is required")
        self.github_token = github_token
        self.model = model
        self.environment = allowlisted_copilot_environment(environment)
        self.assets = load_judge_assets()

    async def review(
        self,
        *,
        task: AgentTask,
        finding: AgentFinding,
        tools: RepositoryTools,
        timeout_seconds: float,
    ) -> JudgeReview | JudgeFailure:
        try:
            prompt = render_judge_prompt(self.assets.prompt_template, task, finding, tools)
            async with asyncio.timeout(timeout_seconds):
                content = await self._run_judge(prompt, timeout_seconds)
            if len(content) > MAX_JUDGE_OUTPUT_CHARACTERS:
                return JudgeFailure(
                    reason="malformed_output",
                    message="Judge response exceeded the configured output limit.",
                )
            raw = parse_model_output(content)
            return JudgeReview.model_validate(raw)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            return JudgeFailure(
                reason="timeout",
                message="Judge forum did not complete within its bounded deadline.",
            )
        except MissingResponseError:
            return JudgeFailure(
                reason="missing_response",
                message="Judge forum returned no final assistant response.",
            )
        except CopilotConfigurationError:
            return JudgeFailure(
                reason="sdk_failure",
                message="Judge forum asset validation failed; primary finding retained.",
            )
        except (json.JSONDecodeError, ValidationError, ValueError):
            return JudgeFailure(
                reason="malformed_output",
                message="Judge forum returned an invalid structured review.",
            )
        except Exception:
            return JudgeFailure(
                reason="sdk_failure",
                message="Judge forum was unavailable; primary finding retained.",
            )

    async def _run_judge(self, prompt: str, timeout_seconds: float) -> str:
        with tempfile.TemporaryDirectory(prefix="dependabot-validator-judge-") as state_dir:
            state_path = Path(state_dir)
            with materialized_skill_root(state_path, self.assets.skill_name) as skill_root:
                async with CopilotClient(
                    mode="empty",
                    env=self.environment,
                    github_token=self.github_token,
                    base_directory=state_dir,
                    use_logged_in_user=False,
                    builtin_plugin_directories=[],
                    enable_remote_sessions=False,
                ) as client:
                    models = await client.list_models()
                    available_model_ids = {model.id for model in models}
                    if self.model is not None and self.model not in available_model_ids:
                        raise CopilotConfigurationError(
                            f"requested Copilot model is unavailable: {self.model}"
                        )
                    observer = SessionAssetObserver(
                        expected_agent=self.assets.agent.name,
                        expected_tools=self.assets.agent.tools,
                        expected_skill=self.assets.skill_name,
                    )
                    custom_agent: CustomAgentConfig = {
                        "name": self.assets.agent.name,
                        "display_name": self.assets.agent.display_name,
                        "description": self.assets.agent.description,
                        "prompt": self.assets.agent_prompt,
                        "tools": list(self.assets.agent.tools),
                        "skills": list(self.assets.agent.skills),
                        "infer": self.assets.agent.infer,
                    }
                    async with await client.create_session(
                        model=self.model,
                        tools=[],
                        available_tools=[],
                        on_permission_request=reject_permission_request,
                        on_event=observer,
                        system_message={
                            "mode": "append",
                            "content": self.assets.system_prompt,
                        },
                        tool_search={"enabled": False},
                        working_directory=state_dir,
                        enable_experimental_mode=False,
                        enable_session_telemetry=False,
                        enable_citations=False,
                        enable_file_change_tracking=False,
                        skip_custom_instructions=True,
                        custom_agents_local_only=True,
                        coauthor_enabled=False,
                        manage_schedule_enabled=False,
                        mcp_servers={},
                        mcp_oauth_token_storage="in-memory",
                        embedding_cache_storage="in-memory",
                        custom_agents=[custom_agent],
                        default_agent={"excluded_tools": []},
                        agent=self.assets.agent.name,
                        commands=[],
                        enable_config_discovery=False,
                        skip_embedding_retrieval=True,
                        organization_custom_instructions="",
                        enable_on_demand_instruction_discovery=False,
                        enable_file_hooks=False,
                        enable_host_git_operations=False,
                        enable_session_store=False,
                        enable_skills=True,
                        skill_directories=[str(skill_root)],
                        plugin_directories=[],
                        instruction_directories=[],
                        disabled_skills=list(DISABLED_BUILTIN_SKILLS),
                        large_output={"enabled": False},
                        memory={"enabled": False},
                        enable_mcp_apps=False,
                        request_canvas_renderer=False,
                        request_extensions=False,
                        enable_managed_settings=False,
                    ) as session:
                        await observer.wait_until_agent_selected(timeout_seconds)
                        event = await session.send_and_wait(prompt, timeout=timeout_seconds)
                        await observer.wait_until_loaded(timeout_seconds)
                    if event is None or not isinstance(event.data, AssistantMessageData):
                        raise MissingResponseError("Copilot returned no final judge message")
                    if observer.agent_id is not None and event.agent_id != observer.agent_id:
                        raise CopilotConfigurationError(
                            "Copilot judge response came from the wrong agent"
                        )
                    return event.data.content
