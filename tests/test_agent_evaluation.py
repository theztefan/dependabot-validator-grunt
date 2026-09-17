"""Agent capability evaluation manifest, runner, and publication tests."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dependabot_validator_grunt.agent_evaluation import (
    AgentEvaluationSummary,
    EvaluationError,
    evaluate_agent_capabilities,
    load_evaluation_manifest,
)
from dependabot_validator_grunt.main import create_app

ROOT = Path(__file__).parents[1]
CASES = ROOT / "examples" / "offline-cases"


def _write_manifest(
    path: Path,
    *,
    evaluation_id: str = "current-investigator",
    assessment: str = "applies",
    fixture: str = "triage-vulnerable",
) -> None:
    path.write_text(
        json.dumps(
            {
                "agent_evaluation_manifest_version": "1.0",
                "evaluation_id": evaluation_id,
                "cases": [
                    {
                        "case_id": fixture,
                        "fixture": fixture,
                        "expected": {
                            "workflow_mode": "triage",
                            "result_kind": "triage_decision",
                            "assessment": assessment,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


async def _prepare_manifest(tmp_path: Path, *, assessment: str = "applies") -> Path:
    def prepare() -> Path:
        shutil.copytree(CASES / "triage-vulnerable", tmp_path / "triage-vulnerable")
        manifest = tmp_path / "evaluation.json"
        _write_manifest(manifest, assessment=assessment)
        return manifest

    return await asyncio.to_thread(prepare)


async def test_evaluation_runs_current_investigator_in_isolated_directory(
    tmp_path: Path,
) -> None:
    manifest = await _prepare_manifest(tmp_path / "inputs")
    summary_path = await evaluate_agent_capabilities(
        manifest,
        tmp_path / "output",
    )

    summary = AgentEvaluationSummary.model_validate_json(
        await asyncio.to_thread(summary_path.read_text, encoding="utf-8")
    )
    assert summary.authoritative is False
    assert summary.status == "passed"
    assert len(summary.results) == 1
    assert summary.results[0].capability_provenance is not None
    assert summary.results[0].capability_provenance.capability_id == "javascript-typescript-v1"
    assert summary.results[0].metrics.analyzer_status is not None
    assert summary.results[0].metrics.analyzer_candidate_files is not None
    assert all(result.expectation_status == "passed" for result in summary.results)
    assert all(
        result.artifact_directory.startswith(f"cases/{result.case_id}/")
        for result in summary.results
    )


async def test_evaluation_publishes_failed_summary_after_expectation_mismatch(
    tmp_path: Path,
) -> None:
    manifest = await _prepare_manifest(tmp_path / "inputs", assessment="does_not_apply")

    with pytest.raises(EvaluationError) as raised:
        await evaluate_agent_capabilities(
            manifest,
            tmp_path / "output",
        )

    assert raised.value.summary_path is not None
    summary = AgentEvaluationSummary.model_validate_json(
        await asyncio.to_thread(
            raised.value.summary_path.read_text,
            encoding="utf-8",
        )
    )
    assert summary.status == "failed"
    assert all(result.expectation_status == "mismatch" for result in summary.results)


def test_evaluation_manifest_rejects_fixture_escape(tmp_path: Path) -> None:
    manifest = tmp_path / "evaluation.json"
    _write_manifest(manifest)
    raw = json.loads(manifest.read_text(encoding="utf-8"))
    raw["cases"][0]["fixture"] = "../outside"
    manifest.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(EvaluationError, match="manifest is invalid"):
        load_evaluation_manifest(manifest)


async def test_evaluation_output_directory_is_exclusive(tmp_path: Path) -> None:
    manifest = await _prepare_manifest(tmp_path / "inputs")
    reserved = tmp_path / "output" / "current-investigator"
    await asyncio.to_thread(reserved.mkdir, parents=True)

    with pytest.raises(EvaluationError, match="already reserved"):
        await evaluate_agent_capabilities(manifest, tmp_path / "output")


async def test_evaluation_fails_when_fixture_does_not_execute_investigator(
    tmp_path: Path,
) -> None:
    def prepare() -> Path:
        inputs = tmp_path / "inputs"
        fixture = inputs / "triage-unaffected"
        shutil.copytree(CASES / "triage-unaffected", fixture)
        shutil.copy(
            CASES / "triage-vulnerable" / "agent-response.json",
            fixture / "agent-response.json",
        )
        manifest = inputs / "evaluation.json"
        _write_manifest(
            manifest,
            fixture="triage-unaffected",
            assessment="does_not_apply",
        )
        return manifest

    manifest = await asyncio.to_thread(prepare)
    with pytest.raises(EvaluationError) as raised:
        await evaluate_agent_capabilities(manifest, tmp_path / "output")

    assert raised.value.summary_path is not None
    summary = AgentEvaluationSummary.model_validate_json(
        await asyncio.to_thread(
            raised.value.summary_path.read_text,
            encoding="utf-8",
        )
    )
    assert all(result.validation_status == "failed" for result in summary.results)
    assert all(
        result.error_message == "the investigator did not execute" for result in summary.results
    )


def test_evaluation_cli_returns_exit_nine_and_prints_failed_summary(
    tmp_path: Path,
) -> None:
    inputs = tmp_path / "inputs"
    shutil.copytree(CASES / "triage-vulnerable", inputs / "triage-vulnerable")
    manifest = inputs / "evaluation.json"
    _write_manifest(manifest, assessment="does_not_apply")

    result = CliRunner().invoke(
        create_app("test"),
        [
            "evaluate-agent-capabilities",
            "--manifest",
            str(manifest),
            "--output",
            str(tmp_path / "output"),
        ],
    )

    assert result.exit_code == 9
    summary_path = tmp_path / "output" / "current-investigator" / "evaluation.json"
    assert str(summary_path) in result.stdout
    assert summary_path.is_file()
