"""CLI tests."""

from __future__ import annotations

# pyright: reportPrivateUsage=false
# This module white-box tests the shared command runner's exception chaining.
import asyncio
import json
import os
import re
import shutil
import subprocess
from collections.abc import Awaitable, Callable, Iterator
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace
from typing import Never, cast

import pytest
import typer
from copilot import Tool, ToolInvocation
from copilot.session_events import (
    AssistantMessageData,
    CustomAgentsUpdatedAgent,
    SessionCustomAgentsUpdatedData,
    SessionEventType,
    SessionSkillsLoadedData,
    SkillsLoadedSkill,
    SkillSource,
    SubagentSelectedData,
)
from github_workflow_support import (
    ALERT,
    OWNER,
    REPO,
    FakeGitHubClient,
)
from github_workflow_support import (
    make_tarball as _tarball,
)
from github_workflow_support import (
    paths as _paths,
)
from github_workflow_support import (
    report as _report,
)
from github_workflow_support import (
    request as _request,
)
from typer.testing import CliRunner

import dependabot_validator_grunt.copilot as copilot_module
import dependabot_validator_grunt.main as main_module
from dependabot_validator_grunt.copilot import (
    DISABLED_BUILTIN_SKILLS,
    CopilotConfigurationError,
)
from dependabot_validator_grunt.copilot_assets import AGENT_NAME, TOOL_NAMES
from dependabot_validator_grunt.judge import JudgedModelTurn
from dependabot_validator_grunt.main import create_app
from dependabot_validator_grunt.models import AgentTask
from dependabot_validator_grunt.workflow import WorkflowError

ROOT = Path(__file__).parents[1]
CASES = ROOT / "examples" / "offline-cases"
runner = CliRunner()


def _finding(task: AgentTask) -> str:
    return json.dumps(
        {
            "finding": {
                "workflow_mode": task.workflow_mode,
                "correlation_id": task.correlation_id,
                "repository_id": task.repository_id,
                "alert_number": task.alert_number,
                "request_id": task.request_id,
                "snapshot_id": task.snapshot_id,
                "policy_digest": task.policy_digest,
                "claim": "No supported conclusion.",
                "citations": [],
                "uncertainty": "No repository fact was cited.",
                "proposed_recommendation": "human_review",
            }
        }
    )


def _task_from_prompt(prompt: str) -> AgentTask:
    match = re.search(r"```json\n(.*?)\n```", prompt, re.DOTALL)
    assert match is not None
    return AgentTask.model_validate(json.loads(match.group(1)))


class FakeSession:
    """Small SDK session fake with one configured response."""

    def __init__(self, response: object, tools: list[Tool]) -> None:
        self.response = response
        self.tools = tools

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: object,
    ) -> None:
        del exception_type, exception, traceback

    async def send_and_wait(self, prompt: str, **options: float) -> object:
        del options
        analyzer = next(tool for tool in self.tools if tool.name == "analyze_reachability")
        assert analyzer.handler is not None
        result = analyzer.handler(
            ToolInvocation(
                session_id="session",
                tool_call_id="reachability",
                tool_name=analyzer.name,
                arguments={},
            )
        )
        if isinstance(result, Awaitable):
            await result
        if isinstance(self.response, BaseException):
            raise self.response
        if self.response == "finding-from-prompt":
            self.response = _finding(_task_from_prompt(prompt))
        return SimpleNamespace(
            agent_id="custom-agent-id",
            data=AssistantMessageData(
                content=cast(str, self.response),
                message_id="message",
                model="fake-model",
            ),
        )


class FakeClient:
    """Small SDK client fake for command-boundary coverage."""

    responses: Iterator[object] = iter(())

    def __init__(self, **kwargs: object) -> None:
        del kwargs
        self.response = next(self.responses)

    async def __aenter__(self) -> FakeClient:
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: object,
    ) -> None:
        del exception_type, exception, traceback

    async def list_models(self) -> list[SimpleNamespace]:
        return [SimpleNamespace(id="fake-model")]

    async def create_session(self, **kwargs: object) -> FakeSession:
        on_event = cast(Callable[[object], None], kwargs["on_event"])
        loop = asyncio.get_running_loop()
        loop.call_soon(
            on_event,
            SimpleNamespace(
                type=SessionEventType.SESSION_CUSTOM_AGENTS_UPDATED,
                data=SessionCustomAgentsUpdatedData(
                    agents=[
                        CustomAgentsUpdatedAgent(
                            description="description",
                            display_name="Dependency Risk Investigator",
                            id="custom-agent-id",
                            name=AGENT_NAME,
                            source="custom",
                            tools=list(TOOL_NAMES),
                            user_invocable=True,
                        )
                    ],
                    errors=[],
                    warnings=[],
                ),
            ),
        )
        loop.call_soon(
            on_event,
            SimpleNamespace(
                type=SessionEventType.SUBAGENT_SELECTED,
                data=SubagentSelectedData(
                    agent_display_name="Dependency Risk Investigator",
                    agent_name=AGENT_NAME,
                    tools=list(TOOL_NAMES),
                ),
            ),
        )
        loop.call_soon(
            on_event,
            SimpleNamespace(
                type=SessionEventType.SESSION_SKILLS_LOADED,
                data=SessionSkillsLoadedData(
                    skills=[
                        SkillsLoadedSkill(
                            description="description",
                            enabled=True,
                            name="dependency-risk-analysis",
                            source=SkillSource.CUSTOM,
                            user_invocable=False,
                        ),
                        *[
                            SkillsLoadedSkill(
                                description="disabled built-in",
                                enabled=False,
                                name=name,
                                source=SkillSource.BUILTIN,
                                user_invocable=False,
                            )
                            for name in DISABLED_BUILTIN_SKILLS
                        ],
                    ]
                ),
            ),
        )
        return FakeSession(self.response, cast(list[Tool], kwargs["tools"]))


@pytest.fixture
def fake_sdk(monkeypatch: pytest.MonkeyPatch) -> type[FakeClient]:
    FakeClient.responses = iter(())
    monkeypatch.setattr(copilot_module, "CopilotClient", FakeClient)
    return FakeClient


def test_version() -> None:
    """The CLI exposes the package version without starting a workflow."""
    package_version = version("dependabot-validator-grunt")
    app = create_app(package_version)
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == package_version


@pytest.mark.parametrize(
    "case",
    [
        "not-used-absent",
        "fix-started",
        "tolerable-risk",
        "agent-approval-downgrade",
        "agent-approved-unused",
    ],
)
def test_demo_cli_runs_without_credentials(case: str, tmp_path: Path) -> None:
    env = os.environ.copy()
    for name in ("DEPENDABOT_GITHUB_TOKEN", "COPILOT_GITHUB_TOKEN", "GITHUB_TOKEN", "GH_TOKEN"):
        env.pop(name, None)
    result = subprocess.run(
        [
            "uv",
            "run",
            "dependabot-validator-grunt",
            "review-dismissal",
            "--offline-fixture",
            str(CASES / case),
            "--output",
            str(tmp_path),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("case", ["triage-vulnerable", "triage-unaffected", "triage-absent"])
def test_triage_cli_runs_without_credentials(case: str, tmp_path: Path) -> None:
    env = os.environ.copy()
    for name in ("DEPENDABOT_GITHUB_TOKEN", "COPILOT_GITHUB_TOKEN", "GITHUB_TOKEN", "GH_TOKEN"):
        env.pop(name, None)
    result = subprocess.run(
        [
            "uv",
            "run",
            "dependabot-validator-grunt",
            "triage-alert",
            "--offline-fixture",
            str(CASES / case),
            "--output",
            str(tmp_path),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("command", "workflow_name"),
    [
        ("review-dismissal", "review_offline_fixture"),
        ("triage-alert", "triage_offline_fixture"),
    ],
)
def test_commands_run_workflow_once_and_print_artifact_directory(
    command: str,
    workflow_name: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    invocations = 0
    artifact_directory = tmp_path / "artifacts"

    async def workflow(*args: object, **kwargs: object) -> Path:
        nonlocal invocations
        del args, kwargs
        invocations += 1
        return artifact_directory

    monkeypatch.setattr(main_module, workflow_name, workflow)

    result = runner.invoke(
        create_app("test"),
        [command, "--offline-fixture", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert result.stdout == f"{artifact_directory}\n"
    assert result.stderr == ""
    assert invocations == 1


@pytest.mark.parametrize(
    ("command", "workflow_name"),
    [
        ("review-dismissal", "review_offline_fixture"),
        ("triage-alert", "triage_offline_fixture"),
    ],
)
def test_commands_preserve_cancellation_error(
    command: str,
    workflow_name: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    invocations = 0

    async def workflow(*args: object, **kwargs: object) -> Path:
        nonlocal invocations
        del args, kwargs
        invocations += 1
        raise asyncio.CancelledError

    monkeypatch.setattr(main_module, workflow_name, workflow)

    result = runner.invoke(
        create_app("test"),
        [command, "--offline-fixture", str(tmp_path)],
    )

    assert result.exit_code == 6
    assert result.stdout == ""
    assert result.stderr == "agentic: Copilot operation cancelled\n"
    assert invocations == 1


@pytest.mark.parametrize(
    ("command", "workflow_name"),
    [
        ("review-dismissal", "review_offline_fixture"),
        ("triage-alert", "triage_offline_fixture"),
    ],
)
def test_commands_preserve_copilot_configuration_error(
    command: str,
    workflow_name: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    invocations = 0

    def workflow(*args: object, **kwargs: object) -> Never:
        nonlocal invocations
        del args, kwargs
        invocations += 1
        raise CopilotConfigurationError("invalid Copilot setup")

    monkeypatch.setattr(main_module, workflow_name, workflow)

    result = runner.invoke(
        create_app("test"),
        [command, "--offline-fixture", str(tmp_path)],
    )

    assert result.exit_code == 2
    assert result.stdout == ""
    assert result.stderr == "configuration: invalid Copilot setup\n"
    assert invocations == 1


@pytest.mark.parametrize(
    ("command", "workflow_name", "live_args", "message"),
    [
        (
            "review-dismissal",
            "review_offline_fixture",
            ["--request", "owner/repository#1"],
            "--offline-fixture is mutually exclusive with live inputs",
        ),
        (
            "triage-alert",
            "triage_offline_fixture",
            ["--repo", "owner/repository", "--alert", "1"],
            "--offline-fixture is mutually exclusive with --repo and --alert",
        ),
    ],
)
def test_commands_preserve_pre_workflow_configuration_validation(
    command: str,
    workflow_name: str,
    live_args: list[str],
    message: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    invocations = 0

    async def workflow(*args: object, **kwargs: object) -> Path:
        nonlocal invocations
        del args, kwargs
        invocations += 1
        return tmp_path

    monkeypatch.setattr(main_module, workflow_name, workflow)

    result = runner.invoke(
        create_app("test"),
        [command, "--offline-fixture", str(tmp_path), *live_args],
    )

    assert result.exit_code == 2
    assert result.stdout == ""
    assert result.stderr == f"configuration: {message}\n"
    assert invocations == 0


@pytest.mark.parametrize(
    ("command", "workflow_name"),
    [
        ("review-dismissal", "review_offline_fixture"),
        ("triage-alert", "triage_offline_fixture"),
    ],
)
def test_commands_preserve_stage_prefixed_workflow_error(
    command: str,
    workflow_name: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    invocations = 0
    workflow_error = WorkflowError(4, "collection", "unable to collect evidence")

    async def workflow(*args: object, **kwargs: object) -> Path:
        nonlocal invocations
        del args, kwargs
        invocations += 1
        raise workflow_error

    monkeypatch.setattr(main_module, workflow_name, workflow)

    result = runner.invoke(
        create_app("test"),
        [command, "--offline-fixture", str(tmp_path)],
    )

    assert result.exit_code == 4
    assert result.stdout == ""
    assert result.stderr == "collection: unable to collect evidence\n"
    assert invocations == 1


@pytest.mark.parametrize(
    ("error", "exit_code"),
    [
        (asyncio.CancelledError(), 6),
        (WorkflowError(4, "collection", "unable to collect evidence"), 4),
    ],
)
def test_workflow_runner_preserves_exception_chaining(
    error: BaseException,
    exit_code: int,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def workflow() -> Path:
        raise error

    with pytest.raises(typer.Exit) as raised:
        main_module._run_workflow(workflow)

    assert raised.value.exit_code == exit_code
    assert raised.value.__cause__ is error
    capsys.readouterr()


def test_cli_offline_model_requires_copilot_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = CliRunner()
    app = create_app("test")
    case = CASES / "tolerable-risk"
    monkeypatch.delenv("COPILOT_GITHUB_TOKEN", raising=False)
    dismissal = runner.invoke(
        app,
        [
            "review-dismissal",
            "--offline-fixture",
            str(case),
            "--output",
            str(tmp_path),
            "--model",
            "fake-model",
        ],
    )
    triage = runner.invoke(
        app,
        [
            "triage-alert",
            "--offline-fixture",
            str(CASES / "triage-vulnerable"),
            "--model",
            "fake-model",
        ],
    )

    assert dismissal.exit_code == 2
    assert "COPILOT_GITHUB_TOKEN is required" in dismissal.stderr
    assert triage.exit_code == 2
    assert "COPILOT_GITHUB_TOKEN is required" in triage.stderr


@pytest.mark.parametrize(
    ("command", "fixture"),
    [
        ("review-dismissal", "tolerable-risk"),
        ("triage-alert", "triage-vulnerable"),
    ],
)
def test_cli_offline_script_ignores_ambient_copilot_token(
    command: str,
    fixture: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "ambient-token")
    output = tmp_path / fixture

    result = CliRunner().invoke(
        create_app("test"),
        [
            command,
            "--offline-fixture",
            str(CASES / fixture),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.stderr
    reports = list(output.rglob("report.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["model_identity"] == "scripted-fixture"


@pytest.mark.parametrize(
    ("command", "fixture"),
    [
        ("review-dismissal", "tolerable-risk"),
        ("triage-alert", "triage-vulnerable"),
    ],
)
def test_cli_offline_missing_script_ignores_ambient_copilot_token(
    command: str,
    fixture: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case = tmp_path / fixture
    shutil.copytree(CASES / fixture, case)
    (case / "agent-response.json").unlink()

    def forbidden_turn(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("ambient credentials must not construct a real model turn")

    monkeypatch.setattr("dependabot_validator_grunt.main.CopilotModelTurn", forbidden_turn)
    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "ambient-token")
    output = tmp_path / "out"

    result = CliRunner().invoke(
        create_app("test"),
        [
            command,
            "--offline-fixture",
            str(case),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 2
    assert "offline agent route requires" in result.stderr
    assert not list(output.rglob("report.json"))


def test_cli_real_copilot_success_and_cancellation_exit(
    fake_sdk: type[FakeClient],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = CliRunner()
    app = create_app("test")
    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "copilot-secret")
    fake_sdk.responses = iter(("finding-from-prompt",))
    success = runner.invoke(
        app,
        [
            "review-dismissal",
            "--offline-fixture",
            str(CASES / "tolerable-risk"),
            "--output",
            str(tmp_path / "success"),
            "--model",
            "fake-model",
        ],
    )
    fake_sdk.responses = iter(("finding-from-prompt",))
    triage = runner.invoke(
        app,
        [
            "triage-alert",
            "--offline-fixture",
            str(CASES / "triage-vulnerable"),
            "--output",
            str(tmp_path / "triage"),
            "--model",
            "fake-model",
        ],
    )
    fake_sdk.responses = iter((asyncio.CancelledError(),))
    cancelled = runner.invoke(
        app,
        [
            "review-dismissal",
            "--offline-fixture",
            str(CASES / "tolerable-risk"),
            "--output",
            str(tmp_path / "cancelled"),
            "--model",
            "fake-model",
        ],
    )

    assert success.exit_code == 0, success.stderr
    report_paths = list((tmp_path / "success").rglob("report.json"))
    assert len(report_paths) == 1
    report = json.loads(report_paths[0].read_text(encoding="utf-8"))
    assert cast(str, report["model_identity"]).startswith("copilot:")
    assert triage.exit_code == 0, triage.stderr
    triage_reports = list((tmp_path / "triage").rglob("report.json"))
    assert len(triage_reports) == 1
    triage_report = json.loads(triage_reports[0].read_text(encoding="utf-8"))
    assert cast(str, triage_report["model_identity"]).startswith("copilot:")
    assert cancelled.exit_code == 6
    assert "Copilot operation cancelled" in cancelled.stderr


def test_triage_cli_model_requires_copilot_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("COPILOT_GITHUB_TOKEN", raising=False)
    result = CliRunner().invoke(
        create_app("test"),
        [
            "triage-alert",
            "--offline-fixture",
            str(CASES / "triage-vulnerable"),
            "--model",
            "model-id",
        ],
    )
    assert result.exit_code == 2
    assert "COPILOT_GITHUB_TOKEN is required" in result.stderr


def test_cli_allows_equal_credentials_for_separate_roles(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    class FakeTurn:
        def __init__(self, token: str, *, model: str | None = None) -> None:
            captured["copilot_token"] = token
            captured["model"] = model

    def client_factory(token: str) -> FakeGitHubClient:
        captured["github_token"] = token
        return FakeGitHubClient()

    async def fake_triage_live_alert(**kwargs: object) -> Path:
        captured["model_turn"] = kwargs["model_turn"]
        return tmp_path

    monkeypatch.setattr(main_module, "GitHubClient", client_factory)
    monkeypatch.setattr(main_module, "CopilotModelTurn", FakeTurn)
    monkeypatch.setattr(main_module, "triage_live_alert", fake_triage_live_alert)
    monkeypatch.setenv("DEPENDABOT_GITHUB_TOKEN", "same-token")
    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "same-token")
    result = CliRunner().invoke(
        create_app("test"),
        [
            "triage-alert",
            "--repo",
            f"{OWNER}/{REPO}",
            "--alert",
            str(ALERT),
        ],
    )

    assert result.exit_code == 0, result.stderr
    assert captured["github_token"] == "same-token"
    assert captured["copilot_token"] == "same-token"
    assert isinstance(captured["model_turn"], JudgedModelTurn)
    assert isinstance(captured["model_turn"].primary, FakeTurn)


def test_load_environment_reads_only_invocation_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    child = tmp_path / "child"
    child.mkdir()
    (tmp_path / ".env").write_text("PARENT_ONLY=parent-secret\n", encoding="utf-8")
    (child / ".env").write_text(
        (
            'DEPENDABOT_GITHUB_TOKEN="shared token"\n'
            "COPILOT_GITHUB_TOKEN=shared-token\n"
            "SSL_CERT_FILE=/untrusted/cert.pem\n"
            "HTTPS_PROXY=https://untrusted.invalid\n"
            "TMPDIR=/untrusted/tmp\n"
            "UNRELATED_SECRET=must-not-load\n"
        ),
        encoding="utf-8",
    )
    excluded = ("PARENT_ONLY", "SSL_CERT_FILE", "HTTPS_PROXY", "TMPDIR", "UNRELATED_SECRET")
    for name in (*excluded, "DEPENDABOT_GITHUB_TOKEN", "COPILOT_GITHUB_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(child)

    main_module.load_environment()

    assert os.environ["DEPENDABOT_GITHUB_TOKEN"] == "shared token"
    assert os.environ["COPILOT_GITHUB_TOKEN"] == "shared-token"
    assert all(name not in os.environ for name in excluded)


@pytest.mark.parametrize("exported", ["exported-token", ""])
def test_load_environment_preserves_exported_values(
    exported: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / ".env").write_text(
        "DEPENDABOT_GITHUB_TOKEN=dotenv-token\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEPENDABOT_GITHUB_TOKEN", exported)

    main_module.load_environment()

    assert os.environ["DEPENDABOT_GITHUB_TOKEN"] == exported


def test_load_environment_missing_file_is_noop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DEPENDABOT_GITHUB_TOKEN", raising=False)

    main_module.load_environment()

    assert "DEPENDABOT_GITHUB_TOKEN" not in os.environ


def test_entrypoint_loads_environment_before_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    def fake_load_environment() -> None:
        events.append("environment")

    def fake_create_app(version_value: str) -> Callable[[], None]:
        assert version_value

        def run() -> None:
            events.append("dispatch")

        return run

    monkeypatch.setattr(main_module, "load_environment", fake_load_environment)
    monkeypatch.setattr(main_module, "create_app", fake_create_app)

    main_module.entrypoint()

    assert events == ["environment", "dispatch"]


def test_create_app_does_not_load_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden_load() -> None:
        raise AssertionError("create_app must remain side-effect-free")

    monkeypatch.setattr(main_module, "load_environment", forbidden_load)

    create_app("test")


def test_dotenv_copilot_token_does_not_change_offline_routing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / ".env").write_text(
        "COPILOT_GITHUB_TOKEN=ambient-dotenv-token\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("COPILOT_GITHUB_TOKEN", raising=False)

    def forbidden_turn(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("dotenv credentials must not replace a scripted fixture")

    monkeypatch.setattr(main_module, "CopilotModelTurn", forbidden_turn)
    main_module.load_environment()
    result = CliRunner().invoke(
        create_app("test"),
        [
            "triage-alert",
            "--offline-fixture",
            str(CASES / "triage-vulnerable"),
            "--output",
            str(tmp_path / "reports"),
        ],
    )

    assert result.exit_code == 0, result.stderr


def test_cli_live_dismissal_and_triage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    clients = iter((FakeGitHubClient(), FakeGitHubClient()))

    def client_factory(token: str) -> FakeGitHubClient:
        del token
        return next(clients)

    monkeypatch.setattr(main_module, "GitHubClient", client_factory)
    monkeypatch.setenv("DEPENDABOT_GITHUB_TOKEN", "github-token")
    monkeypatch.delenv("COPILOT_GITHUB_TOKEN", raising=False)
    runner = CliRunner()
    app = create_app("test")

    dismissal = runner.invoke(
        app,
        [
            "review-dismissal",
            "--request",
            f"https://github.com/{OWNER}/{REPO}/security/dependabot/{ALERT}",
            "--output",
            str(tmp_path / "dismissal"),
        ],
    )
    triage = runner.invoke(
        app,
        [
            "triage-alert",
            "--repo",
            f"{OWNER}/{REPO}",
            "--alert",
            str(ALERT),
            "--output",
            str(tmp_path / "triage"),
        ],
    )

    assert dismissal.exit_code == 0, dismissal.stderr
    assert triage.exit_code == 2
    assert "Copilot credentials are required" in triage.stderr
    assert list((tmp_path / "dismissal").rglob("report.json"))
    assert not list((tmp_path / "triage").rglob("report.json"))


def test_cli_live_triage_constructs_optional_copilot_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    class FakeTurn:
        def __init__(self, token: str, *, model: str | None = None) -> None:
            captured["token"] = token
            captured["model"] = model

    async def fake_triage_live_alert(**kwargs: object) -> Path:
        captured["model_turn"] = kwargs["model_turn"]
        return tmp_path

    def client_factory(token: str) -> FakeGitHubClient:
        del token
        return FakeGitHubClient()

    monkeypatch.setattr(main_module, "GitHubClient", client_factory)
    monkeypatch.setattr(main_module, "CopilotModelTurn", FakeTurn)
    monkeypatch.setattr(main_module, "triage_live_alert", fake_triage_live_alert)
    monkeypatch.setenv("DEPENDABOT_GITHUB_TOKEN", "github-token")
    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "copilot-token")

    result = CliRunner().invoke(
        create_app("test"),
        [
            "triage-alert",
            "--repo",
            f"{OWNER}/{REPO}",
            "--alert",
            str(ALERT),
            "--model",
            "selected-model",
        ],
    )

    assert result.exit_code == 0, result.stderr
    assert captured["token"] == "copilot-token"
    assert captured["model"] == "selected-model"
    assert isinstance(captured["model_turn"], JudgedModelTurn)
    assert isinstance(captured["model_turn"].primary, FakeTurn)


@pytest.mark.parametrize("command", ["review-dismissal", "triage-alert"])
def test_cli_help_omits_real_copilot_flag(command: str) -> None:
    result = CliRunner().invoke(create_app("test"), [command, "--help"])

    assert result.exit_code == 0
    assert "--real-copilot" not in result.stdout


def test_cli_live_triage_defers_model_without_copilot_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    async def fake_triage_live_alert(**kwargs: object) -> Path:
        captured["model_turn"] = kwargs["model_turn"]
        return tmp_path

    def client_factory(token: str) -> FakeGitHubClient:
        del token
        return FakeGitHubClient()

    monkeypatch.setattr(main_module, "GitHubClient", client_factory)
    monkeypatch.setattr(main_module, "triage_live_alert", fake_triage_live_alert)
    monkeypatch.setenv("DEPENDABOT_GITHUB_TOKEN", "github-token")
    monkeypatch.delenv("COPILOT_GITHUB_TOKEN", raising=False)

    result = CliRunner().invoke(
        create_app("test"),
        [
            "triage-alert",
            "--repo",
            f"{OWNER}/{REPO}",
            "--alert",
            str(ALERT),
            "--model",
            "selected-model",
        ],
    )

    assert result.exit_code == 0, result.stderr
    assert captured["model_turn"] is None


def test_cli_live_terminal_triage_accepts_model_without_copilot_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def client_factory(token: str) -> FakeGitHubClient:
        del token
        return FakeGitHubClient(tarball=_tarball(package_version=None))

    monkeypatch.setattr(main_module, "GitHubClient", client_factory)
    monkeypatch.setenv("DEPENDABOT_GITHUB_TOKEN", "github-token")
    monkeypatch.delenv("COPILOT_GITHUB_TOKEN", raising=False)

    result = CliRunner().invoke(
        create_app("test"),
        [
            "triage-alert",
            "--repo",
            f"{OWNER}/{REPO}",
            "--alert",
            str(ALERT),
            "--model",
            "unused-model",
            "--output",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.stderr
    reports = _paths(tmp_path, "report.json")
    assert len(reports) == 1
    assert json.loads(reports[0].read_text(encoding="utf-8"))["model_identity"] == "not_run"


def test_cli_live_terminal_dismissal_accepts_model_without_copilot_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def client_factory(token: str) -> FakeGitHubClient:
        del token
        return FakeGitHubClient()

    monkeypatch.setattr(main_module, "GitHubClient", client_factory)
    monkeypatch.setenv("DEPENDABOT_GITHUB_TOKEN", "github-token")
    monkeypatch.delenv("COPILOT_GITHUB_TOKEN", raising=False)

    result = CliRunner().invoke(
        create_app("test"),
        [
            "review-dismissal",
            "--request",
            f"{OWNER}/{REPO}#{ALERT}",
            "--model",
            "unused-model",
            "--output",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.stderr
    reports = _paths(tmp_path, "report.json")
    assert len(reports) == 1
    assert json.loads(reports[0].read_text(encoding="utf-8"))["model_identity"] == "not_run"


def test_cli_live_operator_fallbacks_reach_request_normalization(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    request = _request()
    request["data"] = None
    request["requester_comment"] = None

    def client_factory(token: str) -> FakeGitHubClient:
        del token
        return FakeGitHubClient(requests=[request, request.copy()])

    justification = tmp_path / "justification.txt"
    justification.write_text("Operator justification.", encoding="utf-8")
    monkeypatch.setattr(main_module, "GitHubClient", client_factory)
    monkeypatch.setenv("DEPENDABOT_GITHUB_TOKEN", "github-token")
    monkeypatch.delenv("COPILOT_GITHUB_TOKEN", raising=False)
    result = CliRunner().invoke(
        create_app("test"),
        [
            "review-dismissal",
            "--request",
            f"{OWNER}/{REPO}#{ALERT}",
            "--reason",
            "no_bandwidth",
            "--justification-file",
            str(justification),
            "--output",
            str(tmp_path / "reports"),
        ],
    )

    assert result.exit_code == 0, result.stderr
    report_path = next((tmp_path / "reports").rglob("report.json"))
    request_report = cast(dict[str, object], _report(report_path.parent)["request"])
    assert request_report["reason"] == "no_bandwidth"
    assert request_report["justification"] == "Operator justification."
    assert request_report["provenance"] == "operator_supplied"
    assert "Provenance: `operator_supplied`" in (report_path.parent / "report.md").read_text(
        encoding="utf-8"
    )
