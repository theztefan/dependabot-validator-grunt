"""Python dependency workflow tests."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

import pytest
from python_dependency_test_support import (
    CASES,
    python_agent_response,
    write_poetry_project,
    write_uv_project,
)

import dependabot_validator_grunt.workflow as workflow_module
from dependabot_validator_grunt.models import (
    PYTHON_REACHABILITY_OPERATIONS,
    ReachabilityEvidence,
    ReachabilityProfile,
)
from dependabot_validator_grunt.workflow import (
    WorkflowError,
    review_offline_fixture,
    triage_offline_fixture,
)


async def test_pip_exact_pin_is_terminal_applies_without_agent(tmp_path: Path) -> None:
    case = tmp_path / "case"
    shutil.copytree(CASES / "triage-absent", case)
    (case / "agent-response.json").unlink(missing_ok=True)
    repository = case / "repository"
    (repository / "requirements.txt").write_text("requests==2.31.0\n", encoding="utf-8")
    alert = json.loads((case / "alert.json").read_text(encoding="utf-8"))
    alert.update(
        {
            "ecosystem": "pip",
            "package_name": "requests",
            "vulnerable_range": "<2.32.0",
            "manifest_path": "requirements.txt",
        }
    )
    alert.pop("package_identity", None)
    (case / "alert.json").write_text(json.dumps(alert), encoding="utf-8")

    output = await triage_offline_fixture(case, tmp_path / "out")
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))

    assert report["model_identity"] == "not_run"
    assert report["alert"]["ecosystem"] == "pip"
    assert report["result"]["assessment"] == "applies"
    assert report["result"]["reason_code"] == "triage_vulnerable_applies"
    assert not list(output.glob("agent-*.json"))


async def test_pip_inconclusive_evidence_uses_python_agent(
    tmp_path: Path,
) -> None:
    case = tmp_path / "case"
    shutil.copytree(CASES / "triage-absent", case)
    (case / "agent-response.json").write_text(
        json.dumps(
            python_agent_response(
                "human_review",
                "insufficient_context",
                insufficient_context=True,
            )
        ),
        encoding="utf-8",
    )
    repository = case / "repository"
    (repository / "requirements.txt").write_text("requests>=2\n", encoding="utf-8")
    alert = json.loads((case / "alert.json").read_text(encoding="utf-8"))
    alert.update(
        {
            "ecosystem": "pip",
            "package_name": "requests",
            "vulnerable_range": "<2.32.0",
            "manifest_path": "requirements.txt",
        }
    )
    alert.pop("package_identity", None)
    (case / "alert.json").write_text(json.dumps(alert), encoding="utf-8")

    output = await triage_offline_fixture(case, tmp_path / "out")
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))

    assert report["model_identity"] == "scripted-fixture"
    assert report["result"]["assessment"] == "human_review"
    assert report["result"]["reason_code"] == "insufficient_context"
    assert (output / "agent-task.json").is_file()
    reachability = json.loads((output / "reachability-evidence.json").read_text(encoding="utf-8"))
    assert reachability["status"] == "no_syntax_match"
    assert not (output / "repository-reference-evidence.json").exists()


async def test_python_agent_task_includes_candidate_paths_relationship_and_targets(
    tmp_path: Path,
) -> None:
    case = tmp_path / "case"
    shutil.copytree(CASES / "triage-absent", case)
    repository = case / "repository"
    (repository / "pyproject.toml").write_text(
        """
[tool.poetry]
name = "example"
version = "0.1.0"

[tool.poetry.dependencies]
python = "^3.12"
parent = ">=1,<2"
""",
        encoding="utf-8",
    )
    (repository / "poetry.lock").write_text(
        """
[[package]]
name = "parent"
version = "1.0.0"
optional = false
groups = ["main"]

[package.dependencies]
requests = { version = ">=2,<3", optional = true }

[[package]]
name = "requests"
version = "2.31.0"
optional = false
groups = ["main"]

[metadata]
lock-version = "2.1"
""",
        encoding="utf-8",
    )
    alert = json.loads((case / "alert.json").read_text(encoding="utf-8"))
    alert.update(
        {
            "ecosystem": "pip",
            "package_name": "requests",
            "vulnerable_range": "<2.32.0",
            "manifest_path": "poetry.lock",
            "dependency_relationship": "transitive",
        }
    )
    alert.pop("package_identity", None)
    (case / "alert.json").write_text(json.dumps(alert), encoding="utf-8")
    (case / "agent-response.json").write_text(
        json.dumps(
            python_agent_response(
                "human_review",
                "insufficient_context",
                insufficient_context=True,
            )
        ),
        encoding="utf-8",
    )

    output = await triage_offline_fixture(case, tmp_path / "out")
    task = json.loads((output / "agent-task.json").read_text(encoding="utf-8"))

    assert task["dependency_relationship"] == "transitive"
    assert task["dependency_paths_truncated"] is False
    assert [node["package_name"] for node in task["dependency_paths"][0]["nodes"]] == [
        "<project>",
        "parent",
        "requests",
    ]
    assert task["dependency_paths"][0]["edge_requirements"] == [
        ">=1,<2",
        ">=2,<3",
    ]
    assert task["import_targets"] == [
        {
            "value": "requests",
            "provenance": "canonical_distribution",
            "authoritative": True,
        }
    ]
    assert len(json.dumps(task, separators=(",", ":"))) < 128 * 1024


async def test_poetry_vulnerable_record_is_terminal_applies_without_agent(
    tmp_path: Path,
) -> None:
    case = tmp_path / "case"
    shutil.copytree(CASES / "triage-absent", case)
    (case / "agent-response.json").unlink(missing_ok=True)
    repository = case / "repository"
    write_poetry_project(repository)
    alert = json.loads((case / "alert.json").read_text(encoding="utf-8"))
    alert.update(
        {
            "ecosystem": "pip",
            "package_name": "requests",
            "vulnerable_range": "<2.32.0",
            "manifest_path": "poetry.lock",
        }
    )
    alert.pop("package_identity", None)
    (case / "alert.json").write_text(json.dumps(alert), encoding="utf-8")

    output = await triage_offline_fixture(case, tmp_path / "out")
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))

    assert report["model_identity"] == "not_run"
    assert report["result"]["assessment"] == "applies"
    assert report["result"]["reason_code"] == "triage_vulnerable_applies"
    assert not list(output.glob("agent-*.json"))


async def test_uv_vulnerable_record_is_terminal_applies_without_agent(
    tmp_path: Path,
) -> None:
    case = tmp_path / "case"
    shutil.copytree(CASES / "triage-absent", case)
    (case / "agent-response.json").unlink(missing_ok=True)
    repository = case / "repository"
    write_uv_project(repository)
    alert = json.loads((case / "alert.json").read_text(encoding="utf-8"))
    alert.update(
        {
            "ecosystem": "uv",
            "package_name": "requests",
            "vulnerable_range": "<2.32.0",
            "manifest_path": "uv.lock",
        }
    )
    alert.pop("package_identity", None)
    (case / "alert.json").write_text(json.dumps(alert), encoding="utf-8")

    output = await triage_offline_fixture(case, tmp_path / "out")
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))

    assert report["model_identity"] == "not_run"
    assert report["result"]["assessment"] == "applies"
    assert report["result"]["reason_code"] == "triage_vulnerable_applies"
    assert not list(output.glob("agent-*.json"))


async def test_python_dismissal_inconclusive_uses_python_agent(
    tmp_path: Path,
) -> None:
    case = tmp_path / "case"
    shutil.copytree(CASES / "not-used-absent", case)
    (case / "agent-response.json").write_text(
        json.dumps(
            python_agent_response(
                "human_review",
                "insufficient_context",
                insufficient_context=True,
            )
        ),
        encoding="utf-8",
    )
    repository = case / "repository"
    (repository / "requirements.txt").write_text("requests>=2\n", encoding="utf-8")
    alert = json.loads((case / "alert.json").read_text(encoding="utf-8"))
    alert.update(
        {
            "ecosystem": "pip",
            "package_name": "requests",
            "vulnerable_range": "<2.32.0",
            "manifest_path": "requirements.txt",
        }
    )
    alert.pop("package_identity", None)
    (case / "alert.json").write_text(json.dumps(alert), encoding="utf-8")

    output = await review_offline_fixture(case, tmp_path / "out")
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))

    assert report["model_identity"] == "scripted-fixture"
    assert report["result"]["recommendation"] == "human_review"
    assert report["result"]["reason_code"] == "insufficient_context"
    assert (output / "agent-task.json").is_file()
    assert (output / "reachability-evidence.json").is_file()
    assert not (output / "repository-reference-evidence.json").exists()
    task = json.loads((output / "agent-task.json").read_text(encoding="utf-8"))
    proposals = {
        proposal["recommendation"]: proposal["reason_codes"]
        for proposal in task["permitted_proposals"]
    }
    assert proposals["deny"] == ["advisory_applies"]


@pytest.mark.parametrize(
    ("source", "expected_kind"),
    (
        ("import requests\n", "static_import"),
        ("from requests import Session\n", "static_import"),
        ('import importlib\nmodule = importlib.import_module("requests")\n', "dynamic_import"),
    ),
)
async def test_python_agent_can_confirm_positive_import_usage(
    source: str,
    expected_kind: str,
    tmp_path: Path,
) -> None:
    case = tmp_path / "case"
    shutil.copytree(CASES / "triage-absent", case)
    repository = case / "repository"
    (repository / "requirements.txt").write_text("requests>=2\n", encoding="utf-8")
    (repository / "app.py").write_text(source, encoding="utf-8")
    alert = json.loads((case / "alert.json").read_text(encoding="utf-8"))
    alert.update(
        {
            "ecosystem": "pip",
            "package_name": "requests",
            "vulnerable_range": "<2.32.0",
            "manifest_path": "requirements.txt",
        }
    )
    alert.pop("package_identity", None)
    (case / "alert.json").write_text(json.dumps(alert), encoding="utf-8")
    (case / "agent-response.json").write_text(
        json.dumps(
            python_agent_response(
                "deny",
                "advisory_applies",
            )
        ),
        encoding="utf-8",
    )

    output = await triage_offline_fixture(case, tmp_path / "out")
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))

    assert report["model_identity"] == "scripted-fixture"
    assert report["result"]["assessment"] == "applies"
    assert report["result"]["reason_code"] == "advisory_applies"
    reachability = json.loads((output / "reachability-evidence.json").read_text(encoding="utf-8"))
    assert reachability["status"] == "syntax_usage_found"
    assert any(
        finding["kind"] == expected_kind
        and finding["language"].casefold() == "python"
        and finding["matched_target"] == "requests"
        for finding in reachability["findings"]
    )


async def test_python_dismissal_validation_rejects_unsupported_denial_code(
    tmp_path: Path,
) -> None:
    case = tmp_path / "case"
    shutil.copytree(CASES / "not-used-absent", case)
    repository = case / "repository"
    (repository / "requirements.txt").write_text("requests>=2\n", encoding="utf-8")
    (repository / "app.py").write_text("import requests\n", encoding="utf-8")
    alert = json.loads((case / "alert.json").read_text(encoding="utf-8"))
    alert.update(
        {
            "ecosystem": "pip",
            "package_name": "requests",
            "vulnerable_range": "<2.32.0",
            "manifest_path": "requirements.txt",
        }
    )
    alert.pop("package_identity", None)
    (case / "alert.json").write_text(json.dumps(alert), encoding="utf-8")
    (case / "agent-response.json").write_text(
        json.dumps(
            python_agent_response(
                "deny",
                "reason_justification_mismatch",
            )
        ),
        encoding="utf-8",
    )

    with pytest.raises(WorkflowError) as raised:
        await review_offline_fixture(case, tmp_path / "out")

    assert raised.value.exit_code == 6
    assert raised.value.stage == "agentic"
    assert not list((tmp_path / "out").rglob("report.json"))


async def test_python_manifest_only_citation_cannot_confirm_usage(
    tmp_path: Path,
) -> None:
    case = tmp_path / "case"
    shutil.copytree(CASES / "triage-absent", case)
    repository = case / "repository"
    (repository / "requirements.txt").write_text("requests>=2\n", encoding="utf-8")
    alert = json.loads((case / "alert.json").read_text(encoding="utf-8"))
    alert.update(
        {
            "ecosystem": "pip",
            "package_name": "requests",
            "vulnerable_range": "<2.32.0",
            "manifest_path": "requirements.txt",
        }
    )
    alert.pop("package_identity", None)
    (case / "alert.json").write_text(json.dumps(alert), encoding="utf-8")
    (case / "agent-response.json").write_text(
        json.dumps(
            python_agent_response(
                "deny",
                "advisory_applies",
                query="requests>=2",
            )
        ),
        encoding="utf-8",
    )

    output = await triage_offline_fixture(case, tmp_path / "out")
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))

    assert report["result"]["assessment"] == "human_review"
    assert report["result"]["reason_code"] == "agent_denial_unproven"
    reachability = json.loads((output / "reachability-evidence.json").read_text(encoding="utf-8"))
    assert reachability["status"] == "no_syntax_match"


async def test_python_source_citation_without_dependency_provenance_cannot_confirm_usage(
    tmp_path: Path,
) -> None:
    case = tmp_path / "case"
    shutil.copytree(CASES / "triage-absent", case)
    repository = case / "repository"
    (repository / "requirements.txt").write_text("flask>=2\n", encoding="utf-8")
    (repository / "app.py").write_text("import requests\n", encoding="utf-8")
    alert = json.loads((case / "alert.json").read_text(encoding="utf-8"))
    alert.update(
        {
            "ecosystem": "pip",
            "package_name": "requests",
            "vulnerable_range": "<2.32.0",
            "manifest_path": "requirements.txt",
        }
    )
    alert.pop("package_identity", None)
    (case / "alert.json").write_text(json.dumps(alert), encoding="utf-8")
    (case / "agent-response.json").write_text(
        json.dumps(
            python_agent_response(
                "deny",
                "advisory_applies",
                query="import requests",
            )
        ),
        encoding="utf-8",
    )

    output = await triage_offline_fixture(case, tmp_path / "out")
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))

    assert report["result"]["assessment"] == "human_review"
    assert report["result"]["reason_code"] == "agent_denial_unproven"


async def test_python_irrelevant_non_manifest_citation_cannot_confirm_usage(
    tmp_path: Path,
) -> None:
    case = tmp_path / "case"
    shutil.copytree(CASES / "triage-absent", case)
    repository = case / "repository"
    (repository / "requirements.txt").write_text("requests>=2\n", encoding="utf-8")
    (repository / "README.md").write_text("requests is documented here\n", encoding="utf-8")
    alert = json.loads((case / "alert.json").read_text(encoding="utf-8"))
    alert.update(
        {
            "ecosystem": "pip",
            "package_name": "requests",
            "vulnerable_range": "<2.32.0",
            "manifest_path": "requirements.txt",
        }
    )
    alert.pop("package_identity", None)
    (case / "alert.json").write_text(json.dumps(alert), encoding="utf-8")
    (case / "agent-response.json").write_text(
        json.dumps(
            python_agent_response(
                "deny",
                "advisory_applies",
                query="requests is documented",
            )
        ),
        encoding="utf-8",
    )

    output = await triage_offline_fixture(case, tmp_path / "out")
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))

    assert report["result"]["assessment"] == "human_review"
    assert report["result"]["reason_code"] == "agent_denial_unproven"


async def test_python_plain_search_citation_without_analyzer_finding_cannot_confirm_usage(
    tmp_path: Path,
) -> None:
    case = tmp_path / "case"
    shutil.copytree(CASES / "triage-absent", case)
    repository = case / "repository"
    (repository / "requirements.txt").write_text("requests>=2\n", encoding="utf-8")
    alert = json.loads((case / "alert.json").read_text(encoding="utf-8"))
    alert.update(
        {
            "ecosystem": "pip",
            "package_name": "requests",
            "vulnerable_range": "<2.32.0",
            "manifest_path": "requirements.txt",
        }
    )
    alert.pop("package_identity", None)
    (case / "alert.json").write_text(json.dumps(alert), encoding="utf-8")
    (repository / "app.py").write_text("# import requests\n", encoding="utf-8")
    response = python_agent_response(
        "deny",
        "advisory_applies",
        query="import requests",
    )
    (case / "agent-response.json").write_text(json.dumps(response), encoding="utf-8")

    output = await triage_offline_fixture(case, tmp_path / "out")
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))

    assert report["result"]["assessment"] == "human_review"
    assert report["result"]["reason_code"] == "agent_denial_unproven"
    reachability_paths = list((tmp_path / "out").rglob("reachability-evidence.json"))
    assert len(reachability_paths) == 1
    assert json.loads(reachability_paths[0].read_text(encoding="utf-8"))["findings"] == []


async def test_python_parent_only_import_cannot_confirm_target_usage(tmp_path: Path) -> None:
    case = tmp_path / "case"
    shutil.copytree(CASES / "triage-absent", case)
    repository = case / "repository"
    (repository / "requirements.txt").write_text("requests>=2\n", encoding="utf-8")
    (repository / "app.py").write_text("import urllib3\n", encoding="utf-8")
    alert = json.loads((case / "alert.json").read_text(encoding="utf-8"))
    alert.update(
        {
            "ecosystem": "pip",
            "package_name": "requests",
            "vulnerable_range": "<2.32.0",
            "manifest_path": "requirements.txt",
            "dependency_relationship": "transitive",
        }
    )
    alert.pop("package_identity", None)
    (case / "alert.json").write_text(json.dumps(alert), encoding="utf-8")
    (case / "agent-response.json").write_text(
        json.dumps(
            python_agent_response(
                "deny",
                "advisory_applies",
                query="import urllib3",
            )
        ),
        encoding="utf-8",
    )

    output = await triage_offline_fixture(case, tmp_path / "out")
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    task = json.loads((output / "agent-task.json").read_text(encoding="utf-8"))

    assert task["dependency_relationship"] == "transitive"
    assert report["result"]["assessment"] == "human_review"
    assert report["result"]["reason_code"] == "agent_denial_unproven"


async def test_python_bound_call_citation_alone_cannot_confirm_usage(tmp_path: Path) -> None:
    case = tmp_path / "case"
    shutil.copytree(CASES / "triage-absent", case)
    repository = case / "repository"
    (repository / "requirements.txt").write_text("requests>=2\n", encoding="utf-8")
    bound_call = 'requests.get("https://example.test")'
    (repository / "app.py").write_text(
        f"import requests\n{bound_call}\n",
        encoding="utf-8",
    )
    alert = json.loads((case / "alert.json").read_text(encoding="utf-8"))
    alert.update(
        {
            "ecosystem": "pip",
            "package_name": "requests",
            "vulnerable_range": "<2.32.0",
            "manifest_path": "requirements.txt",
        }
    )
    alert.pop("package_identity", None)
    (case / "alert.json").write_text(json.dumps(alert), encoding="utf-8")
    response = python_agent_response("deny", "advisory_applies")
    finding = response["finding"]
    assert isinstance(finding, dict)
    finding["citations"] = [
        {
            "path": "app.py",
            "line": 2,
            "digest": hashlib.sha256(bound_call.encode()).hexdigest(),
            "excerpt": bound_call,
        }
    ]
    (case / "agent-response.json").write_text(json.dumps(response), encoding="utf-8")

    output = await triage_offline_fixture(case, tmp_path / "out")
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))

    assert report["result"]["assessment"] == "human_review"
    assert report["result"]["reason_code"] == "agent_denial_unproven"


@pytest.mark.parametrize("status", ["incomplete", "unavailable"])
async def test_python_nonpositive_analyzer_state_cannot_confirm_usage(
    status: Literal["incomplete", "unavailable"],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class NonpositiveRunner:
        def analyze(
            self,
            root: Path,
            *,
            snapshot_id: str,
            package_name: str,
            profile: ReachabilityProfile,
            analysis_root: str = "",
            target_identifiers: Sequence[str] | None = None,
            wall_seconds: int,
            max_files: int,
            max_input_bytes: int,
            max_batch_files: int,
            max_batch_bytes: int,
            max_output_bytes: int,
            max_stderr_bytes: int,
            max_findings: int,
        ) -> ReachabilityEvidence:
            del (
                root,
                wall_seconds,
                max_files,
                max_input_bytes,
                max_batch_files,
                max_batch_bytes,
                max_output_bytes,
                max_stderr_bytes,
                max_findings,
            )
            targets = tuple(target_identifiers or ())
            return ReachabilityEvidence(
                snapshot_id=snapshot_id,
                package_name=package_name,
                target_identifiers=targets,
                analysis_root=analysis_root,
                profile=profile,
                engine="ast-grep",
                engine_version="unavailable" if status == "unavailable" else "0.45.3",
                status=status,
                candidate_files=0,
                staged_files=0,
                skipped_files=0,
                staged_bytes=0,
                operations=PYTHON_REACHABILITY_OPERATIONS,
                completed_operations=(),
                limitations=("No positive structural import evidence was produced.",),
            )

    monkeypatch.setattr(workflow_module, "AstGrepRunner", NonpositiveRunner)
    case = tmp_path / "case"
    shutil.copytree(CASES / "triage-absent", case)
    repository = case / "repository"
    (repository / "requirements.txt").write_text("requests>=2\n", encoding="utf-8")
    (repository / "app.py").write_text("import requests\n", encoding="utf-8")
    alert = json.loads((case / "alert.json").read_text(encoding="utf-8"))
    alert.update(
        {
            "ecosystem": "pip",
            "package_name": "requests",
            "vulnerable_range": "<2.32.0",
            "manifest_path": "requirements.txt",
        }
    )
    alert.pop("package_identity", None)
    (case / "alert.json").write_text(json.dumps(alert), encoding="utf-8")
    (case / "agent-response.json").write_text(
        json.dumps(
            python_agent_response(
                "deny",
                "advisory_applies",
                query="import requests",
            )
        ),
        encoding="utf-8",
    )

    output = await triage_offline_fixture(case, tmp_path / "out")
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    reachability = json.loads((output / "reachability-evidence.json").read_text(encoding="utf-8"))

    assert reachability["status"] == status
    assert report["result"]["assessment"] == "human_review"
    assert report["result"]["reason_code"] == "agent_denial_unproven"


async def test_hyphenated_python_distribution_has_no_authoritative_target(
    tmp_path: Path,
) -> None:
    case = tmp_path / "case"
    shutil.copytree(CASES / "triage-absent", case)
    repository = case / "repository"
    (repository / "requirements.txt").write_text("django-filter>=1\n", encoding="utf-8")
    alert = json.loads((case / "alert.json").read_text(encoding="utf-8"))
    alert.update(
        {
            "ecosystem": "pip",
            "package_name": "django-filter",
            "vulnerable_range": "<25",
            "manifest_path": "requirements.txt",
        }
    )
    alert.pop("package_identity", None)
    (case / "alert.json").write_text(json.dumps(alert), encoding="utf-8")
    (case / "agent-response.json").write_text(
        json.dumps(
            python_agent_response(
                "human_review",
                "insufficient_context",
                insufficient_context=True,
            )
        ),
        encoding="utf-8",
    )

    output = await triage_offline_fixture(case, tmp_path / "out")
    task = json.loads((output / "agent-task.json").read_text(encoding="utf-8"))
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))

    assert task["import_targets"] == []
    assert not (output / "reachability-evidence.json").exists()
    assert report["result"]["assessment"] == "human_review"
