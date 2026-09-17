"""Live workflow acceptance tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
import typer
from github_workflow_support import (
    ALERT,
    COMMIT_SHA,
    OWNER,
    REPO,
    FakeGitHubClient,
    make_python_tarball,
)
from github_workflow_support import (
    alert as _alert,
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

import dependabot_validator_grunt.workflow as workflow_module
from dependabot_validator_grunt.copilot import ScriptedModelTurn
from dependabot_validator_grunt.github import (
    GitHubAuthError,
    GitHubCollectionError,
)
from dependabot_validator_grunt.main import parse_dismissal_reference
from dependabot_validator_grunt.models import RepositorySnapshot
from dependabot_validator_grunt.policy import Limits
from dependabot_validator_grunt.workflow import (
    WorkflowError,
    review_live_dismissal,
    review_offline_fixture,
    triage_live_alert,
    triage_offline_fixture,
)


def _triage_turn(tmp_path: Path) -> ScriptedModelTurn:
    response = tmp_path / "triage-agent-response.json"
    response.write_text(
        json.dumps(
            {
                "tool_calls": [
                    {"name": "analyze_reachability", "arguments": {}},
                    {"name": "search", "arguments": {"query": "lodash", "path": "src"}},
                ],
                "finding": {
                    "workflow_mode": "$task.workflow_mode",
                    "correlation_id": "$task.correlation_id",
                    "repository_id": "$task.repository_id",
                    "alert_number": "$task.alert_number",
                    "request_id": "$task.request_id",
                    "snapshot_id": "$task.snapshot_id",
                    "policy_digest": "$task.policy_digest",
                    "claim": "The vulnerable dependency is used by repository code.",
                    "citations": "$observations",
                    "uncertainty": "",
                    "proposed_recommendation": "deny",
                    "policy_reason_code": "advisory_applies",
                    "confidence": 0.95,
                    "insufficient_context": False,
                    "injection_detected": False,
                },
            }
        ),
        encoding="utf-8",
    )
    return ScriptedModelTurn(response)


async def test_live_dismissal_uses_shared_pipeline_and_attested_snapshot(
    tmp_path: Path,
) -> None:
    github = FakeGitHubClient()

    output = await review_live_dismissal(
        github=github,
        owner=OWNER,
        repo=REPO,
        alert_number=ALERT,
        output_root=tmp_path,
    )

    report = _report(output)
    result = cast(dict[str, object], report["result"])
    assert report["report_schema_version"] == "3.0"
    assert report["run_mode"] == "live_ghec"
    assert report["workflow_mode"] == "dismissal"
    repository = cast(dict[str, object], report["repository"])
    assert repository["provenance"] == "ghec_attested"
    assert repository["snapshot_id"] == COMMIT_SHA
    assert result["recommendation"] == "deny"
    assert result["reason_code"] == "deny_no_bandwidth"
    assert github.calls == [
        "dismissal",
        "alert",
        "repository",
        "branch",
        "tarball",
        "dismissal",
        "alert",
    ]
    assert all(
        owner == OWNER and repo == REPO and (number is None or number == ALERT)
        for _, owner, repo, number in github.arguments
    )
    assert {
        "input.json",
        "evidence.json",
        "deterministic-decision.json",
        "report.json",
        "report.md",
    }.issubset(path.name for path in output.iterdir())


@pytest.mark.parametrize(
    ("request_payload", "expected_lifecycle"),
    [
        (_request(status="approved"), "not_pending"),
        (
            {
                **_request(),
                "expires_at": "2020-01-01T00:00:00Z",
            },
            "expired",
        ),
    ],
)
async def test_live_lifecycle_result_skips_repository_archive(
    request_payload: dict[str, object],
    expected_lifecycle: str,
    tmp_path: Path,
) -> None:
    github = FakeGitHubClient(requests=[request_payload])

    output = await review_live_dismissal(
        github=github,
        owner=OWNER,
        repo=REPO,
        alert_number=ALERT,
        output_root=tmp_path,
    )

    result = cast(dict[str, object], _report(output)["result"])
    assert result["lifecycle"] == expected_lifecycle
    assert github.calls == ["dismissal", "alert", "repository", "branch"]


async def test_live_triage_uses_shared_pipeline(tmp_path: Path) -> None:
    github = FakeGitHubClient()

    output = await triage_live_alert(
        github=github,
        owner=OWNER,
        repo=REPO,
        alert_number=ALERT,
        output_root=tmp_path,
        model_turn=_triage_turn(tmp_path),
    )

    report = _report(output)
    result = cast(dict[str, object], report["result"])
    assert report["run_mode"] == "live_ghec"
    assert report["workflow_mode"] == "triage"
    assert result["assessment"] == "applies"
    assert result["recommended_action"] == "remediate"
    assert report["model_identity"] == "scripted-fixture"
    assert github.calls == ["alert", "repository", "branch", "tarball", "alert"]


@pytest.mark.parametrize(
    ("ecosystem", "manifest_path", "files", "expected_manager"),
    (
        (
            "pip",
            "requirements.txt",
            {"requirements.txt": b"requests==2.31.0\n"},
            "pip",
        ),
        (
            "pip",
            "pyproject.toml",
            {
                "pyproject.toml": b"""
[tool.poetry]
name = "example"
version = "0.1.0"

[tool.poetry.dependencies]
python = "^3.12"
requests = ">=2.31,<3"
""",
                "poetry.lock": b"""
[[package]]
name = "requests"
version = "2.31.0"
optional = false
groups = ["main"]

[metadata]
lock-version = "2.1"
python-versions = "^3.12"
content-hash = "unverified"
""",
            },
            "poetry",
        ),
        (
            "pip",
            "uv.lock",
            {
                "pyproject.toml": b"""
[project]
name = "example"
version = "0.1.0"
dependencies = ["requests>=2"]
""",
                "uv.lock": b"""
version = 1
revision = 3
requires-python = ">=3.12"

[[package]]
name = "requests"
version = "2.31.0"
source = { registry = "https://pypi.org/simple" }
""",
            },
            "uv",
        ),
    ),
)
async def test_live_python_triage_is_terminal_without_agent(
    ecosystem: str,
    manifest_path: str,
    files: dict[str, bytes],
    expected_manager: str,
    tmp_path: Path,
) -> None:
    python_alert = _alert(
        ecosystem=ecosystem,
        package_name="Requests",
        manifest_path=manifest_path,
        vulnerable_range="<2.32.0",
        patched_version="2.32.0",
    )
    github = FakeGitHubClient(
        alerts=[python_alert, python_alert],
        tarball=make_python_tarball(files=files),
    )

    output = await triage_live_alert(
        github=github,
        owner=OWNER,
        repo=REPO,
        alert_number=ALERT,
        output_root=tmp_path,
    )

    report = _report(output)
    alert = cast(dict[str, object], report["alert"])
    result = cast(dict[str, object], report["result"])
    evidence = json.loads((output / "evidence.json").read_text(encoding="utf-8"))
    assert report["model_identity"] == "not_run"
    assert alert["ecosystem"] == ecosystem
    assert alert["package_identity"] == "requests"
    assert result["assessment"] == "applies"
    assert result["reason_code"] == "triage_vulnerable_applies"
    assert evidence["dependency"]["package_manager"] == expected_manager
    assert github.calls == ["alert", "repository", "branch", "tarball", "alert"]


async def test_live_triage_requires_agent_for_non_terminal_baseline(tmp_path: Path) -> None:
    github = FakeGitHubClient()

    with pytest.raises(WorkflowError) as raised:
        await triage_live_alert(
            github=github,
            owner=OWNER,
            repo=REPO,
            alert_number=ALERT,
            output_root=tmp_path,
        )

    assert raised.value.exit_code == 2
    assert raised.value.stage == "configuration"
    assert _paths(tmp_path, "deterministic-decision.json")
    assert not _paths(tmp_path, "report.json")


async def test_live_triage_requires_agent_for_inconclusive_baseline(tmp_path: Path) -> None:
    github = FakeGitHubClient(tarball=_tarball(package_version="git+https://example.invalid/x"))

    with pytest.raises(WorkflowError) as raised:
        await triage_live_alert(
            github=github,
            owner=OWNER,
            repo=REPO,
            alert_number=ALERT,
            output_root=tmp_path,
        )

    assert raised.value.exit_code == 2
    decisions = _paths(tmp_path, "deterministic-decision.json")
    assert len(decisions) == 1
    decision = json.loads(decisions[0].read_text(encoding="utf-8"))
    assert decision["assessment"] == "human_review"
    assert not _paths(tmp_path, "report.json")


async def test_live_triage_terminal_non_applicability_needs_no_agent(tmp_path: Path) -> None:
    github = FakeGitHubClient(tarball=_tarball(package_version=None))

    output = await triage_live_alert(
        github=github,
        owner=OWNER,
        repo=REPO,
        alert_number=ALERT,
        output_root=tmp_path,
    )

    report = _report(output)
    result = cast(dict[str, object], report["result"])
    assert result["assessment"] == "does_not_apply"
    assert result["recommended_action"] == "none"
    assert report["model_identity"] == "not_run"


async def test_live_triage_terminal_route_does_not_invoke_supplied_model(tmp_path: Path) -> None:
    github = FakeGitHubClient(tarball=_tarball(package_version=None))

    output = await triage_live_alert(
        github=github,
        owner=OWNER,
        repo=REPO,
        alert_number=ALERT,
        output_root=tmp_path,
        model_turn=ScriptedModelTurn(tmp_path / "must-not-be-read.json"),
    )

    assert _report(output)["model_identity"] == "not_run"


async def test_offline_terminal_routes_do_not_invoke_supplied_model(tmp_path: Path) -> None:
    missing_response = ScriptedModelTurn(tmp_path / "must-not-be-read.json")

    dismissal_output = await review_offline_fixture(
        Path(__file__).parents[1] / "examples" / "offline-cases" / "fix-started",
        tmp_path / "dismissal",
        model_turn=missing_response,
    )
    triage_output = await triage_offline_fixture(
        Path(__file__).parents[1] / "examples" / "offline-cases" / "triage-absent",
        tmp_path / "triage",
        model_turn=missing_response,
    )

    assert _report(dismissal_output)["model_identity"] == "not_run"
    assert _report(triage_output)["model_identity"] == "not_run"


@pytest.mark.parametrize(
    "request_payload",
    [
        _request(reason="no_bandwidth"),
        _request(status="approved"),
    ],
    ids=["terminal-decision", "lifecycle-result"],
)
async def test_live_terminal_dismissal_does_not_invoke_supplied_model(
    request_payload: dict[str, object],
    tmp_path: Path,
) -> None:
    output = await review_live_dismissal(
        github=FakeGitHubClient(requests=[request_payload, request_payload.copy()]),
        owner=OWNER,
        repo=REPO,
        alert_number=ALERT,
        output_root=tmp_path,
        model_turn=ScriptedModelTurn(tmp_path / "must-not-be-read.json"),
    )

    assert _report(output)["model_identity"] == "not_run"


async def test_live_snapshot_is_deleted_after_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    destinations: list[Path] = []
    original = workflow_module.extract_repository_tarball

    def recording_extract(
        data: bytes,
        destination: Path,
        *,
        owner: str,
        repo: str,
        default_branch: str,
        commit_sha: str,
        limits: Limits,
        selected_dependency_path: str | None = None,
    ) -> RepositorySnapshot:
        destinations.append(destination)
        return original(
            data,
            destination,
            owner=owner,
            repo=repo,
            default_branch=default_branch,
            commit_sha=commit_sha,
            limits=limits,
            selected_dependency_path=selected_dependency_path,
        )

    monkeypatch.setattr(workflow_module, "extract_repository_tarball", recording_extract)
    await review_live_dismissal(
        github=FakeGitHubClient(),
        owner=OWNER,
        repo=REPO,
        alert_number=ALERT,
        output_root=tmp_path,
    )

    assert len(destinations) == 1
    assert not destinations[0].exists()


async def test_live_snapshot_is_deleted_after_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    destinations: list[Path] = []

    def recording_extract(
        data: bytes,
        destination: Path,
        *,
        owner: str,
        repo: str,
        default_branch: str,
        commit_sha: str,
        limits: Limits,
        selected_dependency_path: str | None = None,
    ) -> RepositorySnapshot:
        del data, owner, repo, default_branch, commit_sha, limits, selected_dependency_path
        destinations.append(destination)
        raise GitHubCollectionError("archive could not be parsed")

    monkeypatch.setattr(workflow_module, "extract_repository_tarball", recording_extract)
    with pytest.raises(WorkflowError):
        await review_live_dismissal(
            github=FakeGitHubClient(),
            owner=OWNER,
            repo=REPO,
            alert_number=ALERT,
            output_root=tmp_path,
        )

    assert len(destinations) == 1
    assert not destinations[0].exists()


async def test_live_request_drift_discards_recommendation(tmp_path: Path) -> None:
    github = FakeGitHubClient(requests=[_request(), _request(status="approved")])

    output = await review_live_dismissal(
        github=github,
        owner=OWNER,
        repo=REPO,
        alert_number=ALERT,
        output_root=tmp_path,
    )

    result = cast(dict[str, object], _report(output)["result"])
    assert result["result_kind"] == "dismissal_lifecycle"
    assert result["lifecycle"] == "stale"
    assert result["drift_source"] == "request"


async def test_live_alert_drift_discards_dismissal_recommendation(
    tmp_path: Path,
) -> None:
    github = FakeGitHubClient(alerts=[_alert(), _alert(severity="critical")])

    output = await review_live_dismissal(
        github=github,
        owner=OWNER,
        repo=REPO,
        alert_number=ALERT,
        output_root=tmp_path,
    )

    result = cast(dict[str, object], _report(output)["result"])
    assert result["result_kind"] == "dismissal_lifecycle"
    assert result["drift_source"] == "alert"


async def test_live_refetch_failure_is_validation_error(tmp_path: Path) -> None:
    github = FakeGitHubClient(
        request_error=GitHubCollectionError("GitHub request failed"),
        request_error_at=2,
    )
    with pytest.raises(WorkflowError) as raised:
        await review_live_dismissal(
            github=github,
            owner=OWNER,
            repo=REPO,
            alert_number=ALERT,
            output_root=tmp_path,
        )

    assert raised.value.exit_code == 7
    assert raised.value.stage == "validation"


@pytest.mark.parametrize(
    ("error", "exit_code"),
    [
        (GitHubAuthError("GitHub authentication or authorization failed"), 3),
        (GitHubCollectionError("GitHub request failed"), 4),
    ],
)
async def test_live_initial_github_failures_are_classified(
    error: Exception,
    exit_code: int,
    tmp_path: Path,
) -> None:
    with pytest.raises(WorkflowError) as raised:
        await review_live_dismissal(
            github=FakeGitHubClient(request_error=error),
            owner=OWNER,
            repo=REPO,
            alert_number=ALERT,
            output_root=tmp_path,
        )

    assert raised.value.exit_code == exit_code


async def test_invalid_default_branch_is_classified_as_collection_failure(
    tmp_path: Path,
) -> None:
    github = FakeGitHubClient(
        repository={
            "full_name": f"{OWNER}/{REPO}",
            "default_branch": "bad\nbranch",
        }
    )

    with pytest.raises(WorkflowError) as raised:
        await triage_live_alert(
            github=github,
            owner=OWNER,
            repo=REPO,
            alert_number=ALERT,
            output_root=tmp_path,
        )

    assert raised.value.exit_code == 4
    assert raised.value.stage == "collection"


@pytest.mark.parametrize(("owner", "repo"), [("..", REPO), (OWNER, "../escape")])
async def test_live_entry_points_reject_unsafe_repository_components(
    owner: str,
    repo: str,
    tmp_path: Path,
) -> None:
    github = FakeGitHubClient()
    with pytest.raises(WorkflowError) as raised:
        await triage_live_alert(
            github=github,
            owner=owner,
            repo=repo,
            alert_number=ALERT,
            output_root=tmp_path,
        )
    assert raised.value.exit_code == 2
    assert github.calls == []


async def test_live_agentic_route_requires_copilot_credentials(tmp_path: Path) -> None:
    github = FakeGitHubClient(
        requests=[_request(reason="tolerable_risk")],
    )
    with pytest.raises(WorkflowError) as raised:
        await review_live_dismissal(
            github=github,
            owner=OWNER,
            repo=REPO,
            alert_number=ALERT,
            output_root=tmp_path,
        )
    assert raised.value.exit_code == 2
    assert raised.value.stage == "configuration"


async def test_live_agentic_route_uses_snapshot_tools_and_escalates(
    tmp_path: Path,
) -> None:
    response = tmp_path / "agent-response.json"
    response.write_text(
        json.dumps(
            {
                "tool_calls": [
                    {"name": "analyze_reachability", "arguments": {}},
                    {"name": "search", "arguments": {"query": "lodash", "path": "src"}},
                ],
                "finding": {
                    "workflow_mode": "$task.workflow_mode",
                    "correlation_id": "$task.correlation_id",
                    "repository_id": "$task.repository_id",
                    "alert_number": "$task.alert_number",
                    "request_id": "$task.request_id",
                    "snapshot_id": "$task.snapshot_id",
                    "policy_digest": "$task.policy_digest",
                    "claim": "The available evidence does not support a permitted conclusion.",
                    "citations": "$observations",
                    "uncertainty": "The tolerable-risk request needs human review.",
                    "proposed_recommendation": "human_review",
                    "policy_reason_code": "insufficient_context",
                    "confidence": 0.5,
                    "insufficient_context": True,
                    "injection_detected": False,
                },
            }
        ),
        encoding="utf-8",
    )
    github = FakeGitHubClient(
        requests=[_request(reason="tolerable_risk"), _request(reason="tolerable_risk")]
    )

    output = await review_live_dismissal(
        github=github,
        owner=OWNER,
        repo=REPO,
        alert_number=ALERT,
        output_root=tmp_path / "reports",
        model_turn=ScriptedModelTurn(response),
    )

    result = cast(dict[str, object], _report(output)["result"])
    assert result["recommendation"] == "human_review"
    assert result["reason_code"] == "insufficient_context"


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        (f"{OWNER}/{REPO}#{ALERT}", (OWNER, REPO, ALERT)),
        (
            f"https://api.github.com/repos/{OWNER}/{REPO}/dismissal-requests/dependabot/{ALERT}",
            (OWNER, REPO, ALERT),
        ),
        (
            f"https://github.com/{OWNER}/{REPO}/security/dependabot/{ALERT}",
            (OWNER, REPO, ALERT),
        ),
    ],
)
def test_dismissal_reference_grammar(
    reference: str,
    expected: tuple[str, str, int],
) -> None:
    assert parse_dismissal_reference(reference) == expected


@pytest.mark.parametrize(
    "reference",
    [
        "http://github.com/org/repo/security/dependabot/1",
        "https://evil.example/org/repo/security/dependabot/1",
        "owner/repo#0",
        "owner/repo",
    ],
)
def test_dismissal_reference_rejects_untrusted_forms(reference: str) -> None:
    with pytest.raises(typer.Exit):
        parse_dismissal_reference(reference)


async def test_live_alert_state_drift_is_detected(tmp_path: Path) -> None:
    changed = _alert()
    changed["state"] = "fixed"
    github = FakeGitHubClient(alerts=[_alert(), changed])

    with pytest.raises(WorkflowError) as raised:
        await triage_live_alert(
            github=github,
            owner=OWNER,
            repo=REPO,
            alert_number=ALERT,
            output_root=tmp_path,
            model_turn=_triage_turn(tmp_path),
        )

    assert raised.value.exit_code == 7
    assert "state" in str(raised.value)
