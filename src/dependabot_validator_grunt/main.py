"""Command-line entry point and dependency construction."""

from __future__ import annotations

import asyncio
import os
import re
import urllib.parse
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Annotated, Never

import typer
from dotenv import dotenv_values

from dependabot_validator_grunt import __version__
from dependabot_validator_grunt.copilot import (
    CopilotConfigurationError,
    CopilotFindingJudge,
    CopilotModelTurn,
    ModelTurn,
)
from dependabot_validator_grunt.github import GitHubClient
from dependabot_validator_grunt.judge import JudgedModelTurn
from dependabot_validator_grunt.workflow import (
    WorkflowError,
    review_live_dismissal,
    review_offline_fixture,
    triage_live_alert,
    triage_offline_fixture,
)

REPOSITORY_REFERENCE = re.compile(
    r"^(?P<owner>[A-Za-z0-9][A-Za-z0-9_.-]*)/"
    r"(?P<repo>[A-Za-z0-9][A-Za-z0-9_.-]*)#(?P<alert>[1-9][0-9]*)$"
)
REPOSITORY_NAME = re.compile(
    r"^(?P<owner>[A-Za-z0-9][A-Za-z0-9_.-]*)/"
    r"(?P<repo>[A-Za-z0-9][A-Za-z0-9_.-]*)$"
)
DOTENV_CREDENTIAL_NAMES = (
    "DEPENDABOT_GITHUB_TOKEN",
    "COPILOT_GITHUB_TOKEN",
)


def _configuration_error(message: str) -> Never:
    typer.echo(f"configuration: {message}", err=True)
    raise typer.Exit(2)


def _repository(value: str) -> tuple[str, str]:
    match = REPOSITORY_NAME.fullmatch(value)
    if match is None:
        _configuration_error("--repo must be in owner/repository form")
    return match.group("owner"), match.group("repo")


def parse_dismissal_reference(value: str) -> tuple[str, str, int]:
    concise = REPOSITORY_REFERENCE.fullmatch(value)
    if concise is not None:
        return concise.group("owner"), concise.group("repo"), int(concise.group("alert"))
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "https" or parsed.query or parsed.fragment:
        _configuration_error("--request must be a supported HTTPS GitHub reference")
    parts = tuple(part for part in parsed.path.split("/") if part)
    if (
        parsed.hostname == "api.github.com"
        and len(parts) == 6
        and parts[0] == "repos"
        and parts[3:5] == ("dismissal-requests", "dependabot")
    ):
        owner, repo, number = parts[1], parts[2], parts[5]
    elif (
        parsed.hostname == "github.com"
        and len(parts) == 5
        and parts[2:4] == ("security", "dependabot")
    ):
        owner, repo, number = parts[0], parts[1], parts[4]
    else:
        return _configuration_error("--request is not a supported dismissal or alert URL")
    repository_match = REPOSITORY_NAME.fullmatch(f"{owner}/{repo}")
    if repository_match is None or not number.isdigit() or int(number) <= 0:
        _configuration_error("--request contains an invalid repository or alert number")
    return owner, repo, int(number)


def _copilot_turn(
    model: str | None,
    *,
    required: bool = False,
    defer_missing: bool = False,
) -> ModelTurn | None:
    token = os.environ.get("COPILOT_GITHUB_TOKEN", "")
    if not token:
        if required or (model is not None and not defer_missing):
            _configuration_error("COPILOT_GITHUB_TOKEN is required")
        return None
    return JudgedModelTurn(
        CopilotModelTurn(token, model=model),
        CopilotFindingJudge(token, model=model),
    )


def _github_client() -> GitHubClient:
    token = os.environ.get("DEPENDABOT_GITHUB_TOKEN", "")
    if not token:
        _configuration_error("DEPENDABOT_GITHUB_TOKEN is required for live GHEC mode")
    return GitHubClient(token)


def _justification(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        _configuration_error("justification file could not be read")


def _run_workflow(workflow: Callable[[], Coroutine[object, object, Path]]) -> None:
    try:
        artifact_directory = asyncio.run(workflow())
    except asyncio.CancelledError as error:
        typer.echo("agentic: Copilot operation cancelled", err=True)
        raise typer.Exit(6) from error
    except CopilotConfigurationError as error:
        _configuration_error(str(error))
    except WorkflowError as error:
        typer.echo(f"{error.stage}: {error}", err=True)
        raise typer.Exit(error.exit_code) from error
    typer.echo(artifact_directory)


def create_app(version: str) -> typer.Typer:
    """Create the CLI with explicit values for offline tests."""
    app = typer.Typer(
        add_completion=False,
        help="Agentic Dependabot validation workflow.",
        no_args_is_help=True,
    )

    def version_callback(value: bool) -> None:
        if value:
            typer.echo(version)
            raise typer.Exit

    def _main(
        show_version: bool = typer.Option(
            False,
            "--version",
            callback=version_callback,
            is_eager=True,
            help="Show the package version.",
        ),
    ) -> None:
        """Run Dependabot Validator Grunt."""

    app.callback()(_main)

    def review_dismissal(
        offline_fixture: Annotated[
            Path | None,
            typer.Option(
                "--offline-fixture",
                exists=True,
                file_okay=False,
                readable=True,
            ),
        ] = None,
        request: Annotated[str | None, typer.Option("--request")] = None,
        repository: Annotated[str | None, typer.Option("--repo")] = None,
        alert: Annotated[int | None, typer.Option("--alert", min=1)] = None,
        reason: Annotated[str | None, typer.Option("--reason")] = None,
        justification_file: Annotated[
            Path | None,
            typer.Option("--justification-file", exists=True, dir_okay=False, readable=True),
        ] = None,
        output: Annotated[Path, typer.Option("--output")] = Path("reports"),
        policy: Annotated[
            Path | None, typer.Option("--policy", exists=True, dir_okay=False)
        ] = None,
        model: Annotated[str | None, typer.Option("--model")] = None,
    ) -> None:
        """Review one offline fixture or live GHEC dismissal request."""
        if offline_fixture is not None:
            if any(
                value is not None
                for value in (request, repository, alert, reason, justification_file)
            ):
                _configuration_error("--offline-fixture is mutually exclusive with live inputs")
            _run_workflow(
                lambda: review_offline_fixture(
                    offline_fixture,
                    output,
                    policy,
                    _copilot_turn(model, required=True) if model is not None else None,
                )
            )
            return
        if request is not None:
            if repository is not None or alert is not None:
                _configuration_error("--request is mutually exclusive with --repo and --alert")
            owner, repo, alert_number = parse_dismissal_reference(request)
        else:
            if repository is None or alert is None:
                _configuration_error("live dismissal requires --request or both --repo and --alert")
            owner, repo = _repository(repository)
            alert_number = alert
        github = _github_client()
        _run_workflow(
            lambda: review_live_dismissal(
                github=github,
                owner=owner,
                repo=repo,
                alert_number=alert_number,
                output_root=output,
                policy_path=policy,
                model_turn=_copilot_turn(model, defer_missing=True),
                operator_reason=reason,
                operator_justification=_justification(justification_file),
            )
        )

    app.command("review-dismissal")(review_dismissal)

    def triage_alert(
        offline_fixture: Annotated[
            Path | None,
            typer.Option(
                "--offline-fixture",
                exists=True,
                file_okay=False,
                readable=True,
            ),
        ] = None,
        repository: Annotated[str | None, typer.Option("--repo")] = None,
        alert: Annotated[int | None, typer.Option("--alert", min=1)] = None,
        output: Annotated[Path, typer.Option("--output")] = Path("reports"),
        policy: Annotated[
            Path | None, typer.Option("--policy", exists=True, dir_okay=False)
        ] = None,
        model: Annotated[str | None, typer.Option("--model")] = None,
    ) -> None:
        """Triage one offline fixture or live GHEC Dependabot alert."""
        if offline_fixture is not None:
            if repository is not None or alert is not None:
                _configuration_error(
                    "--offline-fixture is mutually exclusive with --repo and --alert"
                )
            _run_workflow(
                lambda: triage_offline_fixture(
                    offline_fixture,
                    output,
                    policy,
                    _copilot_turn(model, required=True) if model is not None else None,
                )
            )
            return
        if repository is None or alert is None:
            _configuration_error("live triage requires both --repo and --alert")
        owner, repo = _repository(repository)
        github = _github_client()
        _run_workflow(
            lambda: triage_live_alert(
                github=github,
                owner=owner,
                repo=repo,
                alert_number=alert,
                output_root=output,
                policy_path=policy,
                model_turn=_copilot_turn(model, defer_missing=True),
            )
        )

    app.command("triage-alert")(triage_alert)
    return app


def entrypoint() -> None:
    """Run the command-line interface."""
    load_environment()
    create_app(__version__)()


def load_environment() -> None:
    """Load invocation-directory dotenv values without overriding exports."""
    values = dotenv_values(Path.cwd() / ".env")
    for name in DOTENV_CREDENTIAL_NAMES:
        value = values.get(name)
        if name not in os.environ and value is not None:
            os.environ[name] = value


if __name__ == "__main__":
    entrypoint()
