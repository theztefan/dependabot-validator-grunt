"""Non-authoritative evaluation of the current investigator."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from dependabot_validator_grunt.agent_capabilities import (
    AgentCapabilityAttempt,
    AgentCapabilityProvenance,
)
from dependabot_validator_grunt.copilot import (
    CopilotFindingJudge,
    CopilotModelTurn,
    ModelTurn,
    ScriptedModelTurn,
)
from dependabot_validator_grunt.judge import JudgedModelTurn
from dependabot_validator_grunt.models import (
    AgentTask,
    ReachabilityEvidence,
    ReachabilityOperation,
    Report,
    validate_safe_identifier,
)
from dependabot_validator_grunt.workflow import (
    WorkflowError,
    review_offline_fixture,
    triage_offline_fixture,
)

EvaluationStatus = Literal["passed", "failed"]
ExpectationStatus = Literal["passed", "mismatch", "not_run"]


class EvaluationError(RuntimeError):
    """Raised when an evaluation cannot produce an all-passing result."""

    def __init__(self, message: str, *, summary_path: Path | None = None) -> None:
        super().__init__(message)
        self.summary_path = summary_path


class EvaluationExpectedResult(BaseModel):
    """Expected final report constraints for one evaluation case."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workflow_mode: Literal["dismissal", "triage"]
    result_kind: Literal["dismissal_decision", "dismissal_lifecycle", "triage_decision"]
    recommendation: Literal["approve", "deny", "human_review"] | None = None
    assessment: Literal["applies", "does_not_apply", "human_review"] | None = None
    reason_code: str | None = Field(default=None, min_length=1, max_length=120)

    @model_validator(mode="after")
    def validate_mode_fields(self) -> EvaluationExpectedResult:
        if self.workflow_mode == "dismissal" and self.assessment is not None:
            raise ValueError("dismissal expectations cannot declare assessment")
        if self.workflow_mode == "triage" and self.recommendation is not None:
            raise ValueError("triage expectations cannot declare recommendation")
        if self.workflow_mode == "triage" and self.result_kind != "triage_decision":
            raise ValueError("triage expectations require triage_decision")
        if self.workflow_mode == "dismissal" and self.result_kind == "triage_decision":
            raise ValueError("dismissal expectations cannot require triage_decision")
        return self


class AgentEvaluationCase(BaseModel):
    """One fixture evaluated with the current investigator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    fixture: str
    expected: EvaluationExpectedResult

    @field_validator("case_id")
    @classmethod
    def validate_case_id(cls, value: str) -> str:
        validate_safe_identifier(value)
        if value.startswith("@") or "/" in value:
            raise ValueError("case_id must be a safe identifier")
        return value

    @field_validator("fixture")
    @classmethod
    def validate_fixture(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            not value
            or "\\" in value
            or path.is_absolute()
            or ".." in path.parts
            or value.startswith("~")
        ):
            raise ValueError("fixture must be a safe relative path")
        return value


class AgentEvaluationManifest(BaseModel):
    """Strict versioned evaluation manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_evaluation_manifest_version: Literal["1.0"]
    evaluation_id: str
    cases: tuple[AgentEvaluationCase, ...]

    @field_validator("evaluation_id")
    @classmethod
    def validate_evaluation_id(cls, value: str) -> str:
        validate_safe_identifier(value)
        if value.startswith("@") or "/" in value:
            raise ValueError("evaluation_id must be a safe identifier")
        return value

    @field_validator("cases")
    @classmethod
    def validate_cases(
        cls,
        value: tuple[AgentEvaluationCase, ...],
    ) -> tuple[AgentEvaluationCase, ...]:
        case_ids = [case.case_id for case in value]
        if not case_ids or len(case_ids) != len(set(case_ids)):
            raise ValueError("cases must be non-empty with unique case_id values")
        return value


class EvaluationMetrics(BaseModel):
    """Non-authoritative runtime and analyzer metrics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    cost: float | None = None
    tool_calls: int | None = None
    authoritative_import_targets: int | None = Field(default=None, ge=0)
    analyzer_status: (
        Literal[
            "syntax_usage_found",
            "no_syntax_match",
            "incomplete",
            "unavailable",
        ]
        | None
    ) = None
    analyzer_analysis_root: str | None = None
    analyzer_candidate_files: int | None = Field(default=None, ge=0)
    analyzer_staged_files: int | None = Field(default=None, ge=0)
    analyzer_skipped_files: int | None = Field(default=None, ge=0)
    analyzer_staged_bytes: int | None = Field(default=None, ge=0)
    analyzer_completed_operations: tuple[ReachabilityOperation, ...] = ()
    analyzer_findings: int | None = Field(default=None, ge=0)


class AgentEvaluationResult(BaseModel):
    """One isolated evaluation case result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    fixture: str
    artifact_directory: str
    execution_status: EvaluationStatus
    validation_status: EvaluationStatus
    expectation_status: ExpectationStatus
    error_stage: str | None = None
    error_message: str | None = None
    capability_provenance: AgentCapabilityProvenance | None = None
    primary_result: dict[str, object] | None = None
    judge_result: dict[str, object] | None = None
    final_result: dict[str, object] | None = None
    attempts: tuple[AgentCapabilityAttempt, ...] = ()
    elapsed_milliseconds: int = Field(ge=0)
    metrics: EvaluationMetrics = EvaluationMetrics()


class AgentEvaluationSummary(BaseModel):
    """Canonical non-authoritative evaluation summary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_evaluation_format_version: Literal["1.0"] = "1.0"
    authoritative: Literal[False] = False
    evaluation_id: str
    manifest_digest: str
    requested_model: str | None = None
    observed_models: tuple[str, ...] = ()
    started_at: datetime
    completed_at: datetime
    status: EvaluationStatus
    results: tuple[AgentEvaluationResult, ...]


def load_evaluation_manifest(path: Path) -> tuple[AgentEvaluationManifest, str]:
    """Load one manifest and return it with its exact-byte digest."""
    try:
        raw = path.read_bytes()
        manifest = AgentEvaluationManifest.model_validate_json(raw)
    except (OSError, UnicodeError, ValueError) as error:
        raise EvaluationError("agent evaluation manifest is invalid") from error
    return manifest, hashlib.sha256(raw).hexdigest()


def _resolve_fixture(manifest_path: Path, fixture: str) -> Path:
    root = manifest_path.parent.resolve()
    candidate = (root / fixture).resolve()
    if candidate == root or root not in candidate.parents:
        raise EvaluationError("evaluation fixture escapes the manifest directory")
    if not candidate.is_dir():
        raise EvaluationError(f"evaluation fixture does not exist: {fixture}")
    return candidate


def _model_turn(
    fixture: Path,
    *,
    model: str | None,
    copilot_token: str | None,
) -> ModelTurn:
    if model is None:
        response_path = fixture / "agent-response.json"
        if not response_path.is_file():
            raise EvaluationError("scripted evaluation fixture requires agent-response.json")
        return ScriptedModelTurn(response_path)
    if not copilot_token:
        raise EvaluationError("COPILOT_GITHUB_TOKEN is required for model evaluation")
    return JudgedModelTurn(
        CopilotModelTurn(copilot_token, model=model),
        lambda: CopilotFindingJudge(copilot_token, model=model),
    )


def _read_optional_json(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    return TypeAdapter(dict[str, object]).validate_json(path.read_text(encoding="utf-8"))


def _artifact_payload(
    artifact_directory: Path,
) -> tuple[
    AgentCapabilityProvenance | None,
    dict[str, object] | None,
    dict[str, object] | None,
]:
    capability_raw = _read_optional_json(artifact_directory / "agent-capability.json")
    capability = (
        AgentCapabilityProvenance.model_validate(capability_raw)
        if capability_raw is not None
        else None
    )
    return (
        capability,
        _read_optional_json(artifact_directory / "agent-primary-finding.json")
        or _read_optional_json(artifact_directory / "agent-findings.json"),
        _read_optional_json(artifact_directory / "judge-review.json"),
    )


def _evaluation_metrics(artifact_directory: Path) -> EvaluationMetrics:
    task_raw = _read_optional_json(artifact_directory / "agent-task.json")
    reachability_raw = _read_optional_json(artifact_directory / "reachability-evidence.json")
    task = AgentTask.model_validate(task_raw) if task_raw is not None else None
    reachability = (
        ReachabilityEvidence.model_validate(reachability_raw)
        if reachability_raw is not None
        else None
    )
    return EvaluationMetrics(
        authoritative_import_targets=(
            sum(target.authoritative for target in task.import_targets)
            if task is not None
            else None
        ),
        analyzer_status=reachability.status if reachability is not None else None,
        analyzer_analysis_root=reachability.analysis_root if reachability is not None else None,
        analyzer_candidate_files=(
            reachability.candidate_files if reachability is not None else None
        ),
        analyzer_staged_files=reachability.staged_files if reachability is not None else None,
        analyzer_skipped_files=reachability.skipped_files if reachability is not None else None,
        analyzer_staged_bytes=reachability.staged_bytes if reachability is not None else None,
        analyzer_completed_operations=(
            reachability.completed_operations if reachability is not None else ()
        ),
        analyzer_findings=len(reachability.findings) if reachability is not None else None,
    )


def _discover_artifact_directory(case_root: Path) -> Path:
    for artifact_name in ("report.json", "agent-capability.json", "failure.json"):
        matches = sorted(case_root.rglob(artifact_name))
        if matches:
            return matches[0].parent
    return case_root


def _matches_expectation(report: Report, expected: EvaluationExpectedResult) -> bool:
    result = report.result.model_dump(mode="json")
    constraints: dict[str, object] = {
        "result_kind": expected.result_kind,
    }
    if expected.recommendation is not None:
        constraints["recommendation"] = expected.recommendation
    if expected.assessment is not None:
        constraints["assessment"] = expected.assessment
    if expected.reason_code is not None:
        constraints["reason_code"] = expected.reason_code
    return report.workflow_mode == expected.workflow_mode and all(
        result.get(name) == value for name, value in constraints.items()
    )


async def _evaluate_one(
    *,
    case: AgentEvaluationCase,
    fixture: Path,
    evaluation_root: Path,
    model: str | None,
    copilot_token: str | None,
    policy_path: Path | None,
) -> AgentEvaluationResult:
    started = time.monotonic()
    case_root = evaluation_root / "cases" / case.case_id
    artifact_directory = case_root
    try:
        turn = _model_turn(
            fixture,
            model=model,
            copilot_token=copilot_token,
        )
        if case.expected.workflow_mode == "dismissal":
            artifact_directory = await review_offline_fixture(
                fixture,
                case_root,
                policy_path,
                turn,
            )
        else:
            artifact_directory = await triage_offline_fixture(
                fixture,
                case_root,
                policy_path,
                turn,
            )
        report = Report.model_validate_json(
            await asyncio.to_thread(
                (artifact_directory / "report.json").read_text,
                encoding="utf-8",
            )
        )
        capability, primary, judge = await asyncio.to_thread(
            _artifact_payload,
            artifact_directory,
        )
        if capability is None:
            return AgentEvaluationResult(
                case_id=case.case_id,
                fixture=case.fixture,
                artifact_directory=artifact_directory.relative_to(evaluation_root).as_posix(),
                execution_status="passed",
                validation_status="failed",
                expectation_status="not_run",
                error_stage="validation",
                error_message="the investigator did not execute",
                capability_provenance=capability,
                primary_result=primary,
                judge_result=judge,
                final_result=report.result.model_dump(mode="json"),
                attempts=capability.attempts if capability is not None else (),
                elapsed_milliseconds=int((time.monotonic() - started) * 1000),
                metrics=await asyncio.to_thread(_evaluation_metrics, artifact_directory),
            )
        matched = _matches_expectation(report, case.expected)
        return AgentEvaluationResult(
            case_id=case.case_id,
            fixture=case.fixture,
            artifact_directory=artifact_directory.relative_to(evaluation_root).as_posix(),
            execution_status="passed",
            validation_status="passed",
            expectation_status="passed" if matched else "mismatch",
            capability_provenance=capability,
            primary_result=primary,
            judge_result=judge,
            final_result=report.result.model_dump(mode="json"),
            attempts=capability.attempts,
            elapsed_milliseconds=int((time.monotonic() - started) * 1000),
            metrics=await asyncio.to_thread(_evaluation_metrics, artifact_directory),
        )
    except asyncio.CancelledError:
        raise
    except (EvaluationError, WorkflowError, OSError, ValueError) as error:
        artifact_directory = await asyncio.to_thread(
            _discover_artifact_directory,
            case_root,
        )
        capability, primary, judge = await asyncio.to_thread(
            _artifact_payload,
            artifact_directory,
        )
        return AgentEvaluationResult(
            case_id=case.case_id,
            fixture=case.fixture,
            artifact_directory=artifact_directory.relative_to(evaluation_root).as_posix(),
            execution_status="failed",
            validation_status="failed",
            expectation_status="not_run",
            error_stage=error.stage if isinstance(error, WorkflowError) else "evaluation",
            error_message=str(error)[:500],
            capability_provenance=capability,
            primary_result=primary,
            judge_result=judge,
            attempts=capability.attempts if capability is not None else (),
            elapsed_milliseconds=int((time.monotonic() - started) * 1000),
            metrics=await asyncio.to_thread(_evaluation_metrics, artifact_directory),
        )


def _publish_summary(path: Path, summary: AgentEvaluationSummary) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    payload = json.dumps(
        summary.model_dump(mode="json"),
        indent=2,
        sort_keys=True,
    )
    try:
        temporary.write_text(f"{payload}\n", encoding="utf-8")
        os.replace(temporary, path)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise EvaluationError("agent evaluation summary could not be published") from error


async def evaluate_agent_capabilities(
    manifest_path: Path,
    output_root: Path,
    *,
    model: str | None = None,
    copilot_token: str | None = None,
    policy_path: Path | None = None,
) -> Path:
    """Run every case once, publishing the canonical summary last."""
    manifest, manifest_digest = await asyncio.to_thread(
        load_evaluation_manifest,
        manifest_path,
    )
    evaluation_root = output_root / manifest.evaluation_id
    try:
        evaluation_root.mkdir(parents=True, exist_ok=False)
    except OSError as error:
        raise EvaluationError("evaluation output directory is already reserved") from error
    started_at = datetime.now(UTC)
    results: list[AgentEvaluationResult] = []
    for case in manifest.cases:
        try:
            fixture = await asyncio.to_thread(_resolve_fixture, manifest_path, case.fixture)
        except EvaluationError as error:
            results.append(
                AgentEvaluationResult(
                    case_id=case.case_id,
                    fixture=case.fixture,
                    artifact_directory=f"cases/{case.case_id}",
                    execution_status="failed",
                    validation_status="failed",
                    expectation_status="not_run",
                    error_stage="manifest",
                    error_message=str(error),
                    elapsed_milliseconds=0,
                )
            )
            continue
        results.append(
            await _evaluate_one(
                case=case,
                fixture=fixture,
                evaluation_root=evaluation_root,
                model=model,
                copilot_token=copilot_token,
                policy_path=policy_path,
            )
        )
    status: EvaluationStatus = (
        "passed"
        if all(
            result.execution_status == "passed"
            and result.validation_status == "passed"
            and result.expectation_status == "passed"
            for result in results
        )
        else "failed"
    )
    observed_models = tuple(
        sorted(
            {
                result.capability_provenance.observed_model
                for result in results
                if result.capability_provenance is not None
                and result.capability_provenance.observed_model is not None
            }
        )
    )
    summary = AgentEvaluationSummary(
        evaluation_id=manifest.evaluation_id,
        manifest_digest=manifest_digest,
        requested_model=model,
        observed_models=observed_models,
        started_at=started_at,
        completed_at=datetime.now(UTC),
        status=status,
        results=tuple(results),
    )
    summary_path = evaluation_root / "evaluation.json"
    await asyncio.to_thread(_publish_summary, summary_path, summary)
    if status == "failed":
        raise EvaluationError(
            "one or more agent capability evaluation cases failed",
            summary_path=summary_path,
        )
    return summary_path
