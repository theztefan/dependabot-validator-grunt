"""Offline and live workflow orchestration."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import stat
import tempfile
import uuid
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal, Never, cast

from pydantic import BaseModel, TypeAdapter, ValidationError

from dependabot_validator_grunt.agent_capabilities import (
    AgentCapabilityAttempt,
    AgentCapabilityError,
    AgentCapabilityProvenance,
    ExecutionMode,
    build_capability_provenance,
    select_investigator_capability,
)
from dependabot_validator_grunt.agentic import RepositoryTools, path_is_denied, validate_finding
from dependabot_validator_grunt.copilot import (
    CopilotConfigurationError,
    CopilotTurnError,
    ModelTurn,
    ScriptedModelTurn,
    validate_task_reachability,
)
from dependabot_validator_grunt.deterministic import (
    create_triage_agent_task,
    decide,
    decide_triage,
    reconcile,
    reconcile_triage,
)
from dependabot_validator_grunt.github import (
    GitHubAuthError,
    GitHubClient,
    GitHubCollectionError,
    dependency_file_uses_extended_limit,
    extract_repository_tarball,
    normalize_branch_sha,
    normalize_dependabot_alert,
    normalize_dismissal_request,
    normalize_repository,
)
from dependabot_validator_grunt.models import (
    AgentFinding,
    AgentTask,
    AgentTaskSizeError,
    AlertSnapshot,
    DependencyEvidence,
    DismissalDecision,
    DismissalLifecycleResult,
    EvidenceBundle,
    EvidenceItem,
    PackageManager,
    ReachabilityEvidence,
    Report,
    RepositoryReferenceEvidence,
    RepositorySnapshot,
    RequestSnapshot,
    analysis_family,
    stable_digest,
    version_scheme_for_ecosystem,
)
from dependabot_validator_grunt.npm import collect_npm_evidence
from dependabot_validator_grunt.policy import Policy, load_policy
from dependabot_validator_grunt.python_dependencies import collect_python_evidence
from dependabot_validator_grunt.reachability import AstGrepRunner
from dependabot_validator_grunt.reporting import write_failure, write_json, write_report


class WorkflowError(Exception):
    """Stage-classified workflow failure."""

    def __init__(self, exit_code: int, stage: str, message: str) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.stage = stage


@dataclass(frozen=True)
class WorkflowCollection:
    """Validated inputs shared by offline and live workflow modes."""

    run_mode: Literal["offline_fixture", "live_ghec"]
    alert: AlertSnapshot
    repository_root: Path
    repository: RepositorySnapshot
    policy: Policy
    dependency: DependencyEvidence
    collector_version: str
    evidence_provenance: str


@dataclass(frozen=True)
class AgentRun:
    finding: AgentFinding
    task: AgentTask
    repository_reference_evidence: RepositoryReferenceEvidence | None
    reachability_evidence: ReachabilityEvidence | None
    model_identity: str


REPOSITORY_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
OFFLINE_COLLECTION_VALIDATION_MESSAGE = "offline fixture data failed validation"
REFERENCE_EVIDENCE_VALIDATION_MESSAGE = "repository reference evidence validation failed"


def _validate_live_target(owner: str, repo: str) -> None:
    if (
        REPOSITORY_COMPONENT.fullmatch(owner) is None
        or REPOSITORY_COMPONENT.fullmatch(repo) is None
    ):
        raise WorkflowError(2, "configuration", "repository must contain safe owner and name")


def _artifact_json(
    path: Path,
    value: BaseModel | Mapping[str, object],
    failure_root: Path,
) -> None:
    try:
        write_json(path, value)
    except OSError as error:
        with suppress(OSError):
            write_failure(failure_root, "publication", str(error))
        raise WorkflowError(8, "publication", str(error)) from error


def _raise_reference_evidence_validation_failure(
    run_directory: Path,
    failure_root: Path,
    error: OSError | ValueError | ValidationError,
) -> Never:
    _artifact_json(
        run_directory / "failure.json",
        {
            "stage": "validation",
            "message": REFERENCE_EVIDENCE_VALIDATION_MESSAGE,
        },
        failure_root,
    )
    raise WorkflowError(
        7,
        "validation",
        REFERENCE_EVIDENCE_VALIDATION_MESSAGE,
    ) from error


def _json_object(path: Path) -> dict[str, object]:
    return TypeAdapter(dict[str, object]).validate_python(
        json.loads(path.read_text(encoding="utf-8"))
    )


def _load_snapshot[SnapshotT: BaseModel](path: Path, model: type[SnapshotT]) -> SnapshotT:
    raw = _json_object(path)
    raw["raw_response_digest"] = stable_digest(raw)
    return model.model_validate(raw)


def _file_digest(path: Path, max_bytes: int) -> tuple[str, int]:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > max_bytes:
        raise ValueError("offline snapshot file exceeds its configured limit")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(descriptor)
        if (
            (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
            or opened.st_size != before.st_size
            or opened.st_mtime_ns != before.st_mtime_ns
        ):
            raise ValueError("offline snapshot file changed during open")
        digest = hashlib.sha256()
        total = 0
        with os.fdopen(descriptor, "rb", closefd=False) as file:
            for chunk in iter(lambda: file.read(64 * 1024), b""):
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("offline snapshot file exceeds its configured limit")
                digest.update(chunk)
        closed = os.fstat(descriptor)
        if (
            (closed.st_dev, closed.st_ino) != (before.st_dev, before.st_ino)
            or closed.st_size != before.st_size
            or closed.st_mtime_ns != before.st_mtime_ns
        ):
            raise ValueError("offline snapshot file changed during read")
        return digest.hexdigest(), total
    finally:
        os.close(descriptor)


def _repository_snapshot(
    root: Path,
    owner: str,
    name: str,
    *,
    max_members: int,
    max_file_bytes: int,
    max_dependency_file_bytes: int,
    max_total_bytes: int,
    selected_dependency_path: str | None = None,
) -> RepositorySnapshot:
    included: list[str] = []
    excluded: list[str] = []
    manifest: list[dict[str, str]] = []
    total_bytes = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        if path_is_denied(relative):
            excluded.append(relative)
            continue
        if len(included) >= max_members:
            raise ValueError("offline snapshot member limit exceeded")
        relative_path = path.relative_to(root).as_posix()
        file_limit = (
            max_dependency_file_bytes
            if dependency_file_uses_extended_limit(
                relative_path,
                selected_dependency_path=selected_dependency_path,
            )
            else max_file_bytes
        )
        content_digest, file_bytes = _file_digest(path, file_limit)
        total_bytes += file_bytes
        if total_bytes > max_total_bytes:
            raise ValueError("offline snapshot expanded byte limit exceeded")
        included.append(relative)
        manifest.append(
            {
                "path": relative,
                "content_digest": content_digest,
            }
        )
    return RepositorySnapshot(
        owner=owner,
        name=name,
        snapshot_id=stable_digest(manifest),
        provenance="offline_fixture",
        included_paths=tuple(included),
        excluded_paths=tuple(excluded),
    )


def _lifecycle(request: RequestSnapshot) -> DismissalLifecycleResult | None:
    if request.status != "pending":
        return DismissalLifecycleResult(
            lifecycle="not_pending",
            reason_code="request_not_pending",
            observed_status=request.status,
        )
    if request.expires_at is not None and request.expires_at <= datetime.now(UTC):
        return DismissalLifecycleResult(
            lifecycle="expired",
            reason_code="request_expired",
            observed_status=request.status,
        )
    return None


def _semantic_changes(left: BaseModel, right: BaseModel) -> tuple[str, ...]:
    left_data = left.model_dump(mode="json", exclude={"raw_response_digest"})
    right_data = right.model_dump(mode="json", exclude={"raw_response_digest"})
    return tuple(
        key
        for key in sorted(left_data.keys() | right_data.keys())
        if left_data.get(key) != right_data.get(key)
    )


def _collect_offline(
    case_directory: Path,
    policy_path: Path | None,
    failure_root: Path,
) -> WorkflowCollection:
    selected_policy = policy_path
    if selected_policy is None and (case_directory / "policy.json").exists():
        selected_policy = case_directory / "policy.json"
    policy = _load_policy(selected_policy, failure_root)
    try:
        alert = _load_snapshot(case_directory / "alert.json", AlertSnapshot)
        repository_root = case_directory / "repository"
        case_meta = _json_object(case_directory / "case.json")
        owner, name = str(case_meta["repository"]).split("/", 1)
        if (
            REPOSITORY_COMPONENT.fullmatch(owner) is None
            or REPOSITORY_COMPONENT.fullmatch(name) is None
        ):
            raise ValueError("case repository must contain safe owner and name components")
        repository = _repository_snapshot(
            repository_root,
            owner,
            name,
            max_members=policy.limits.max_archive_members,
            max_file_bytes=policy.limits.max_archive_file_bytes,
            max_dependency_file_bytes=policy.limits.max_dependency_file_bytes,
            max_total_bytes=policy.limits.expanded_bytes,
            selected_dependency_path=alert.manifest_path,
        )
    except ValidationError as error:
        write_failure(failure_root, "collection", OFFLINE_COLLECTION_VALIDATION_MESSAGE)
        raise WorkflowError(
            4,
            "collection",
            OFFLINE_COLLECTION_VALIDATION_MESSAGE,
        ) from error
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        write_failure(failure_root, "collection", str(error))
        raise WorkflowError(4, "collection", str(error)) from error
    dependency = _collect_dependency(
        repository_root,
        alert,
        failure_root,
        max_dependency_file_bytes=policy.limits.max_dependency_file_bytes,
        excluded_paths=repository.excluded_paths,
    )
    return WorkflowCollection(
        run_mode="offline_fixture",
        alert=alert,
        repository_root=repository_root,
        repository=repository,
        policy=policy,
        dependency=dependency,
        collector_version="offline-dependency-v2",
        evidence_provenance="offline_fixture",
    )


def _load_policy(policy_path: Path | None, failure_root: Path) -> Policy:
    try:
        return load_policy(policy_path)
    except (OSError, ValueError, json.JSONDecodeError, ValidationError) as error:
        write_failure(failure_root, "configuration", str(error))
        raise WorkflowError(2, "configuration", str(error)) from error


def _collect_dependency(
    repository_root: Path,
    alert: AlertSnapshot,
    failure_root: Path,
    *,
    max_dependency_file_bytes: int,
    excluded_paths: tuple[str, ...],
) -> DependencyEvidence:
    try:
        match analysis_family(alert.ecosystem):
            case "javascript_typescript":
                return collect_npm_evidence(
                    repository_root,
                    alert.package_name,
                    alert.manifest_path,
                    max_dependency_file_bytes=max_dependency_file_bytes,
                    excluded_paths=excluded_paths,
                )
            case "python":
                return collect_python_evidence(
                    repository_root,
                    alert.ecosystem,
                    alert.package_name,
                    alert.manifest_path,
                    max_dependency_file_bytes=max_dependency_file_bytes,
                    excluded_paths=excluded_paths,
                )
    except (OSError, ValueError, KeyError, json.JSONDecodeError, ValidationError) as error:
        write_failure(failure_root, "dependency_evidence", str(error))
        raise WorkflowError(5, "dependency_evidence", str(error)) from error


def _lifecycle_package_manager(alert: AlertSnapshot) -> PackageManager:
    """Infer the selected manager from attested ecosystem and manifest path."""
    name = PurePosixPath(alert.manifest_path).name
    match analysis_family(alert.ecosystem):
        case "javascript_typescript":
            managers: dict[str, PackageManager] = {
                "package-lock.json": "npm",
                "yarn.lock": "yarn-classic",
                "pnpm-lock.yaml": "pnpm",
            }
            return managers.get(name, "npm")
        case "python":
            if name == "uv.lock":
                return "uv"
            if name == "poetry.lock":
                return "poetry"
            return "uv" if alert.ecosystem == "uv" else "pip"


def _build_bundle(
    collection: WorkflowCollection,
    correlation_id: str,
    workflow_mode: Literal["dismissal", "triage"],
    request: RequestSnapshot | None,
) -> EvidenceBundle:
    package_manifest = next(
        (declaration.manifest_path for declaration in collection.dependency.declarations),
        next(
            (
                path
                for path in collection.dependency.manifest_paths
                if path.endswith(("package.json", "pyproject.toml"))
            ),
            collection.alert.manifest_path,
        ),
    )
    lock_manifest = collection.dependency.lockfile_path or package_manifest
    declaration_provenance = (
        ",".join(
            sorted({declaration.source_kind for declaration in collection.dependency.declarations})
        )
        or collection.dependency.ecosystem
    )
    evidence_items = (
        EvidenceItem(
            evidence_id="dependency.instances",
            kind="dependency_instances",
            value=str(len(collection.dependency.instances)),
            provenance=collection.dependency.package_manager,
            collector_version="dependency-evidence-v1",
            source_location=lock_manifest,
            completeness=collection.dependency.completeness,
        ),
        EvidenceItem(
            evidence_id="dependency.declarations",
            kind="dependency_declarations",
            value=str(len(collection.dependency.declarations)),
            provenance=declaration_provenance,
            collector_version="dependency-evidence-v1",
            source_location=package_manifest,
            completeness=collection.dependency.completeness,
        ),
        EvidenceItem(
            evidence_id="alert.vulnerable_range",
            kind="vulnerable_range",
            value=collection.alert.vulnerable_range,
            provenance=collection.evidence_provenance,
            collector_version=collection.collector_version,
            source_location=(
                "alert.json"
                if collection.run_mode == "offline_fixture"
                else f"dependabot-alert:{collection.alert.alert_number}"
            ),
        ),
    )
    partial = EvidenceBundle(
        run_mode=collection.run_mode,
        workflow_mode=workflow_mode,
        correlation_id=correlation_id,
        request=request,
        alert=collection.alert,
        repository=collection.repository,
        dependency=collection.dependency,
        evidence_items=evidence_items,
        policy=collection.policy.identity(),
        digest="",
    )
    digest_input = partial.model_dump(mode="json", exclude={"digest"})
    return partial.model_copy(update={"digest": stable_digest(digest_input)})


async def _run_agent(
    *,
    task: AgentTask,
    collection: WorkflowCollection,
    model_turn: ModelTurn,
    evidence_digest: str,
    run_directory: Path,
    failure_root: Path,
) -> AgentRun:
    tools = RepositoryTools(
        collection.repository_root,
        max_read_bytes=collection.policy.limits.max_read_bytes,
        max_results=collection.policy.limits.max_results,
        max_session_bytes=collection.policy.limits.max_session_bytes,
        max_proof_scan_bytes=collection.policy.limits.max_proof_scan_bytes,
        reachability_runner=AstGrepRunner(),
        analyzer_wall_seconds=collection.policy.limits.analyzer_wall_seconds,
        max_analyzer_files=collection.policy.limits.max_analyzer_files,
        max_analyzer_input_bytes=collection.policy.limits.max_analyzer_input_bytes,
        max_analyzer_batch_files=collection.policy.limits.max_analyzer_batch_files,
        max_analyzer_batch_bytes=collection.policy.limits.max_analyzer_batch_bytes,
        max_analyzer_output_bytes=collection.policy.limits.max_analyzer_output_bytes,
        max_analyzer_stderr_bytes=collection.policy.limits.max_analyzer_stderr_bytes,
        max_analyzer_findings=collection.policy.limits.max_analyzer_findings,
        coverage_excluded_path_count=len(collection.repository.coverage_excluded_paths),
    )
    reference_evidence = None
    assigned_task = task
    if task.permits("approve", "vulnerable_symbol_unused"):
        try:
            reference_evidence = tools.collect_reference_evidence(task.package_name)
        except (OSError, ValueError, ValidationError) as error:
            _raise_reference_evidence_validation_failure(run_directory, failure_root, error)
        _artifact_json(
            run_directory / "repository-reference-evidence.json",
            reference_evidence,
            failure_root,
        )
        try:
            assigned_task = AgentTask.model_validate(
                {
                    **task.model_dump(mode="json"),
                    "repository_reference_evidence": reference_evidence.model_dump(mode="json"),
                }
            )
        except AgentTaskSizeError as error:
            write_failure(run_directory, "configuration", str(error))
            raise WorkflowError(2, "configuration", str(error)) from error
        except (OSError, ValueError, ValidationError) as error:
            _raise_reference_evidence_validation_failure(run_directory, failure_root, error)
    _artifact_json(run_directory / "agent-task.json", assigned_task, failure_root)
    try:
        selected_capability = select_investigator_capability(assigned_task.ecosystem)
    except AgentCapabilityError as error:
        write_failure(run_directory, "configuration", str(error))
        raise WorkflowError(2, "configuration", str(error)) from error

    def capability_provenance() -> AgentCapabilityProvenance:
        execution_mode_value = getattr(model_turn, "execution_mode", "scripted")
        if execution_mode_value not in {"scripted", "copilot"}:
            raise WorkflowError(2, "configuration", "investigator execution mode is invalid")
        execution_mode = cast(ExecutionMode, execution_mode_value)
        requested_model = getattr(model_turn, "requested_model", None)
        observed_model_value = getattr(model_turn, "observed_model", None)
        observed_model = (
            observed_model_value
            if execution_mode == "copilot" and isinstance(observed_model_value, str)
            else None
        )
        attempts = tuple(
            AgentCapabilityAttempt(number=attempt.number, outcome=attempt.outcome)
            for attempt in getattr(model_turn, "attempts", ())
        )
        return build_capability_provenance(
            task=assigned_task,
            evidence_digest=evidence_digest,
            capability=selected_capability,
            execution_mode=execution_mode,
            tool_names=("list_files", "read_file", "search", "analyze_reachability"),
            requested_model=requested_model,
            observed_model=observed_model,
            diagnostics=tuple(getattr(model_turn, "diagnostics", ())),
            attempts=attempts,
        )

    try:
        raw_output = await model_turn.run(
            assigned_task,
            tools,
            max_attempts=collection.policy.limits.max_attempts,
            wall_clock_seconds=collection.policy.limits.wall_clock_seconds,
        )
        validate_task_reachability(assigned_task, tools)
        try:
            tools.validate_reference_snapshot()
        except (OSError, ValueError) as error:
            _raise_reference_evidence_validation_failure(run_directory, failure_root, error)
        if tools.reachability_evidence is not None:
            _artifact_json(
                run_directory / "reachability-evidence.json",
                tools.reachability_evidence,
                failure_root,
            )
        _artifact_json(run_directory / "agent-output.raw.json", raw_output, failure_root)
        if "primary_finding" in raw_output:
            _artifact_json(
                run_directory / "agent-primary-finding.json",
                TypeAdapter(dict[str, object]).validate_python(raw_output["primary_finding"]),
                failure_root,
            )
        if "judge_review" in raw_output:
            _artifact_json(
                run_directory / "judge-review.json",
                TypeAdapter(dict[str, object]).validate_python(raw_output["judge_review"]),
                failure_root,
            )
        raw_finding = TypeAdapter(dict[str, object]).validate_python(raw_output.get("finding"))
        finding = validate_finding(raw_finding, assigned_task, tools)
        _artifact_json(
            run_directory / "agent-capability.json",
            capability_provenance(),
            failure_root,
        )
    except CopilotConfigurationError as error:
        _artifact_json(
            run_directory / "agent-capability.json",
            capability_provenance(),
            failure_root,
        )
        write_failure(run_directory, "configuration", str(error))
        raise WorkflowError(2, "configuration", str(error)) from error
    except CopilotTurnError as error:
        _artifact_json(
            run_directory / "agent-capability.json",
            capability_provenance(),
            failure_root,
        )
        _artifact_json(
            run_directory / "agent-output.raw.json",
            error.artifact(),
            failure_root,
        )
        write_failure(run_directory, "agentic", str(error))
        raise WorkflowError(6, "agentic", str(error)) from error
    except asyncio.CancelledError:
        _artifact_json(
            run_directory / "agent-capability.json",
            capability_provenance(),
            failure_root,
        )
        write_failure(run_directory, "agentic", "Copilot operation cancelled")
        raise
    except (OSError, ValueError, KeyError, json.JSONDecodeError, ValidationError) as error:
        message = "Copilot returned an invalid or unsupported finding"
        _artifact_json(
            run_directory / "agent-capability.json",
            capability_provenance(),
            failure_root,
        )
        write_failure(run_directory, "agentic", message)
        raise WorkflowError(6, "agentic", message) from error
    _artifact_json(run_directory / "agent-findings.json", finding, failure_root)
    return AgentRun(
        finding=finding,
        task=assigned_task,
        repository_reference_evidence=reference_evidence,
        reachability_evidence=tools.reachability_evidence,
        model_identity=model_turn.identity,
    )


def _missing_agent_boundary_message(run_mode: Literal["offline_fixture", "live_ghec"]) -> str:
    if run_mode == "live_ghec":
        return "Copilot credentials are required for the agent route selected by routing"
    return "offline agent route requires agent-response.json or an explicit model turn"


async def _execute_dismissal(
    *,
    correlation_id: str,
    failure_root: Path,
    collection: WorkflowCollection,
    request: RequestSnapshot,
    output_root: Path,
    input_data: Mapping[str, object],
    model_turn: ModelTurn | None,
    reread_request: Callable[[], Awaitable[RequestSnapshot]],
    reread_alert: Callable[[], Awaitable[AlertSnapshot]],
) -> Path:
    run_directory = (
        output_root
        / f"{collection.repository.owner}_{collection.repository.name}"
        / str(collection.alert.alert_number)
        / correlation_id
    )
    bundle = _build_bundle(collection, correlation_id, "dismissal", request)
    _artifact_json(run_directory / "input.json", input_data, failure_root)
    _artifact_json(run_directory / "evidence.json", bundle, failure_root)
    lifecycle = _lifecycle(request)
    model_identity = "not_run"
    result: DismissalDecision | DismissalLifecycleResult
    if lifecycle is not None:
        result = lifecycle
    else:
        try:
            initial = decide(bundle, collection.policy)
        except (AgentTaskSizeError, ValidationError) as error:
            write_failure(run_directory, "configuration", str(error))
            raise WorkflowError(2, "configuration", str(error)) from error
        _artifact_json(run_directory / "deterministic-decision.json", initial, failure_root)
        if isinstance(initial, DismissalDecision):
            result = initial
        else:
            if model_turn is None:
                message = _missing_agent_boundary_message(collection.run_mode)
                write_failure(run_directory, "configuration", message)
                raise WorkflowError(2, "configuration", message)
            agent_run = await _run_agent(
                task=initial,
                collection=collection,
                model_turn=model_turn,
                evidence_digest=bundle.digest,
                run_directory=run_directory,
                failure_root=failure_root,
            )
            model_identity = agent_run.model_identity
            result = reconcile(
                agent_run.finding,
                agent_run.task,
                bundle,
                collection.policy,
                repository_reference_evidence=agent_run.repository_reference_evidence,
                reachability_evidence=agent_run.reachability_evidence,
            )
        try:
            current = await reread_request()
            current_alert = await reread_alert()
        except (OSError, ValueError, KeyError, json.JSONDecodeError, ValidationError) as error:
            write_failure(run_directory, "validation", str(error))
            raise WorkflowError(7, "validation", str(error)) from error
        request_changes = _semantic_changes(request, current)
        alert_changes = _semantic_changes(collection.alert, current_alert)
        if request_changes:
            result = DismissalLifecycleResult(
                lifecycle="stale",
                reason_code="request_state_changed",
                observed_status=current.status,
                drift_source="request",
                changed_fields=request_changes,
                superseded_result_digest=stable_digest(result),
            )
        elif alert_changes:
            result = DismissalLifecycleResult(
                lifecycle="stale",
                reason_code="alert_state_changed",
                observed_status=current.status,
                drift_source="alert",
                changed_fields=alert_changes,
                superseded_result_digest=stable_digest(result),
            )
    report = Report(
        run_mode=collection.run_mode,
        workflow_mode="dismissal",
        correlation_id=correlation_id,
        policy=collection.policy.identity(),
        request=request,
        alert=collection.alert,
        repository=collection.repository,
        evidence_digest=bundle.digest,
        collector_version=collection.collector_version,
        model_identity=model_identity,
        result=result,
    )
    if isinstance(result, DismissalDecision):
        route = collection.policy.routes.get(request.reason)
        if route is not None and result.recommendation not in route.permitted_final:
            write_failure(
                run_directory,
                "validation",
                "final recommendation is not permitted by policy",
            )
            raise WorkflowError(
                7,
                "validation",
                "final recommendation is not permitted by policy",
            )
    _publish_report(run_directory, report, failure_root)
    return run_directory


async def _execute_triage(
    *,
    correlation_id: str,
    failure_root: Path,
    collection: WorkflowCollection,
    output_root: Path,
    input_data: Mapping[str, object],
    reread_alert: Callable[[], Awaitable[AlertSnapshot]],
    model_turn: ModelTurn | None = None,
) -> Path:
    run_directory = (
        output_root
        / f"{collection.repository.owner}_{collection.repository.name}"
        / str(collection.alert.alert_number)
        / correlation_id
    )
    bundle = _build_bundle(collection, correlation_id, "triage", None)
    _artifact_json(run_directory / "input.json", input_data, failure_root)
    _artifact_json(run_directory / "evidence.json", bundle, failure_root)
    baseline = decide_triage(bundle, collection.policy)
    _artifact_json(run_directory / "deterministic-decision.json", baseline, failure_root)
    result = baseline
    model_identity = "not_run"
    requires_agent = baseline.assessment == "human_review" or (
        analysis_family(collection.alert.ecosystem) == "javascript_typescript"
        and baseline.assessment == "applies"
        and collection.dependency.package_manager == "npm"
    )
    if requires_agent and model_turn is None:
        message = _missing_agent_boundary_message(collection.run_mode)
        write_failure(run_directory, "configuration", message)
        raise WorkflowError(2, "configuration", message)
    if model_turn is not None and requires_agent:
        try:
            task = create_triage_agent_task(bundle, collection.policy)
        except (AgentTaskSizeError, ValidationError) as error:
            write_failure(run_directory, "configuration", str(error))
            raise WorkflowError(2, "configuration", str(error)) from error
        agent_run = await _run_agent(
            task=task,
            collection=collection,
            model_turn=model_turn,
            evidence_digest=bundle.digest,
            run_directory=run_directory,
            failure_root=failure_root,
        )
        result = reconcile_triage(
            agent_run.finding,
            agent_run.task,
            baseline,
            bundle,
            collection.policy,
            repository_reference_evidence=agent_run.repository_reference_evidence,
            reachability_evidence=agent_run.reachability_evidence,
        )
        model_identity = agent_run.model_identity
    try:
        current_alert = await reread_alert()
    except (OSError, ValueError, KeyError, json.JSONDecodeError, ValidationError) as error:
        write_failure(run_directory, "validation", str(error))
        raise WorkflowError(7, "validation", str(error)) from error
    alert_changes = _semantic_changes(collection.alert, current_alert)
    if alert_changes:
        message = f"alert state changed: {', '.join(alert_changes)}"
        write_failure(run_directory, "validation", message)
        raise WorkflowError(7, "validation", message)
    report = Report(
        run_mode=collection.run_mode,
        workflow_mode="triage",
        correlation_id=correlation_id,
        policy=collection.policy.identity(),
        request=None,
        alert=collection.alert,
        repository=collection.repository,
        evidence_digest=bundle.digest,
        collector_version=collection.collector_version,
        model_identity=model_identity,
        result=result,
    )
    _publish_report(run_directory, report, failure_root)
    return run_directory


def _publish_report(run_directory: Path, report: Report, failure_root: Path) -> None:
    try:
        write_report(run_directory, report)
    except OSError as error:
        with suppress(OSError):
            write_failure(failure_root, "publication", str(error))
        raise WorkflowError(8, "publication", str(error)) from error


async def review_offline_fixture(
    case_directory: Path,
    output_root: Path,
    policy_path: Path | None = None,
    model_turn: ModelTurn | None = None,
) -> Path:
    """Run one complete offline dismissal review and return its artifact directory."""
    correlation_id = uuid.uuid4().hex
    failure_root = output_root / "_failed" / correlation_id
    try:
        request = _load_snapshot(case_directory / "request.json", RequestSnapshot)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, ValidationError) as error:
        write_failure(failure_root, "collection", str(error))
        raise WorkflowError(4, "collection", str(error)) from error
    collection = _collect_offline(case_directory, policy_path, failure_root)

    async def reread_request() -> RequestSnapshot:
        path = case_directory / "post-analysis-request.json"
        if not path.exists():
            path = case_directory / "request.json"
        return await asyncio.to_thread(_load_snapshot, path, RequestSnapshot)

    async def reread_alert() -> AlertSnapshot:
        path = case_directory / "post-analysis-alert.json"
        if not path.exists():
            path = case_directory / "alert.json"
        return await asyncio.to_thread(_load_snapshot, path, AlertSnapshot)

    turn = model_turn
    response_path = case_directory / "agent-response.json"
    if turn is None and response_path.is_file():
        turn = ScriptedModelTurn(response_path)
    return await _execute_dismissal(
        correlation_id=correlation_id,
        failure_root=failure_root,
        collection=collection,
        request=request,
        output_root=output_root,
        input_data={
            "run_mode": "offline_fixture",
            "workflow_mode": "dismissal",
            "case_directory": str(case_directory),
            "correlation_id": correlation_id,
        },
        model_turn=turn,
        reread_request=reread_request,
        reread_alert=reread_alert,
    )


async def triage_offline_fixture(
    case_directory: Path,
    output_root: Path,
    policy_path: Path | None = None,
    model_turn: ModelTurn | None = None,
) -> Path:
    """Run one complete offline alert triage and return its artifact directory."""
    correlation_id = uuid.uuid4().hex
    failure_root = output_root / "_failed" / correlation_id
    collection = _collect_offline(case_directory, policy_path, failure_root)
    turn = model_turn
    response_path = case_directory / "agent-response.json"
    if turn is None and response_path.is_file():
        turn = ScriptedModelTurn(response_path)

    async def reread_alert() -> AlertSnapshot:
        path = case_directory / "post-analysis-alert.json"
        if not path.exists():
            path = case_directory / "alert.json"
        return await asyncio.to_thread(_load_snapshot, path, AlertSnapshot)

    return await _execute_triage(
        correlation_id=correlation_id,
        failure_root=failure_root,
        collection=collection,
        output_root=output_root,
        input_data={
            "run_mode": "offline_fixture",
            "workflow_mode": "triage",
            "case_directory": str(case_directory),
            "correlation_id": correlation_id,
        },
        reread_alert=reread_alert,
        model_turn=turn,
    )


async def _collect_live(
    *,
    github: GitHubClient,
    owner: str,
    repo: str,
    alert_number: int,
    policy: Policy,
    snapshot_root: Path,
    failure_root: Path,
) -> WorkflowCollection:
    try:
        alert_raw, repository_raw = await asyncio.gather(
            github.get_dependabot_alert(owner, repo, alert_number),
            github.get_repository(owner, repo),
        )
        alert = normalize_dependabot_alert(alert_raw, alert_number=alert_number)
        default_branch = normalize_repository(repository_raw, owner=owner, repo=repo)
        branch_raw = await github.get_branch(owner, repo, default_branch)
        commit_sha = normalize_branch_sha(branch_raw, expected_branch=default_branch)
        archive = await github.download_tarball(
            owner,
            repo,
            commit_sha,
            policy.limits.archive_bytes,
        )
        repository = await asyncio.to_thread(
            extract_repository_tarball,
            archive,
            snapshot_root,
            owner=owner,
            repo=repo,
            default_branch=default_branch,
            commit_sha=commit_sha,
            limits=policy.limits,
            selected_dependency_path=alert.manifest_path,
        )
    except GitHubAuthError as error:
        write_failure(failure_root, "authentication", str(error))
        raise WorkflowError(3, "authentication", str(error)) from error
    except GitHubCollectionError as error:
        write_failure(failure_root, "collection", str(error))
        raise WorkflowError(4, "collection", str(error)) from error
    dependency = _collect_dependency(
        snapshot_root,
        alert,
        failure_root,
        max_dependency_file_bytes=policy.limits.max_dependency_file_bytes,
        excluded_paths=repository.excluded_paths,
    )
    return WorkflowCollection(
        run_mode="live_ghec",
        alert=alert,
        repository_root=snapshot_root,
        repository=repository,
        policy=policy,
        dependency=dependency,
        collector_version="ghec-dependency-v2",
        evidence_provenance="ghec_api",
    )


async def review_live_dismissal(
    *,
    github: GitHubClient,
    owner: str,
    repo: str,
    alert_number: int,
    output_root: Path,
    policy_path: Path | None = None,
    model_turn: ModelTurn | None = None,
    operator_reason: str | None = None,
    operator_justification: str | None = None,
) -> Path:
    """Review one live GHEC dismissal request without performing GitHub writes."""
    correlation_id = uuid.uuid4().hex
    failure_root = output_root / "_failed" / correlation_id
    _validate_live_target(owner, repo)
    policy = _load_policy(policy_path, failure_root)
    try:
        request_raw = await github.get_dismissal_request(owner, repo, alert_number)
        request = normalize_dismissal_request(
            request_raw,
            owner=owner,
            repo=repo,
            alert_number=alert_number,
            operator_reason=operator_reason,
            operator_justification=operator_justification,
        )
    except GitHubAuthError as error:
        write_failure(failure_root, "authentication", str(error))
        raise WorkflowError(3, "authentication", str(error)) from error
    except GitHubCollectionError as error:
        write_failure(failure_root, "collection", str(error))
        raise WorkflowError(4, "collection", str(error)) from error
    lifecycle = _lifecycle(request)
    if lifecycle is not None:
        try:
            alert_raw, repository_raw = await asyncio.gather(
                github.get_dependabot_alert(owner, repo, alert_number),
                github.get_repository(owner, repo),
            )
            alert = normalize_dependabot_alert(alert_raw, alert_number=alert_number)
            default_branch = normalize_repository(repository_raw, owner=owner, repo=repo)
            branch_raw = await github.get_branch(owner, repo, default_branch)
            commit_sha = normalize_branch_sha(branch_raw, expected_branch=default_branch)
        except GitHubAuthError as error:
            write_failure(failure_root, "authentication", str(error))
            raise WorkflowError(3, "authentication", str(error)) from error
        except GitHubCollectionError as error:
            write_failure(failure_root, "collection", str(error))
            raise WorkflowError(4, "collection", str(error)) from error
        collection = WorkflowCollection(
            run_mode="live_ghec",
            alert=alert,
            repository_root=Path(),
            repository=RepositorySnapshot(
                owner=owner,
                name=repo,
                default_branch=default_branch,
                snapshot_id=commit_sha,
                provenance="ghec_attested",
                included_paths=(),
            ),
            policy=policy,
            dependency=DependencyEvidence(
                ecosystem=alert.ecosystem,
                package_manager=_lifecycle_package_manager(alert),
                version_scheme=version_scheme_for_ecosystem(alert.ecosystem),
                lockfile_version=None,
                lockfile_path=None,
                proof_capabilities=(),
                package_name=alert.package_name,
                instances=(),
                manifest_paths=(),
                completeness="unsupported",
                issues=("repository snapshot not collected for lifecycle result",),
            ),
            collector_version="ghec-dependency-v2",
            evidence_provenance="ghec_api",
        )

        async def unreachable_request_reread() -> RequestSnapshot:
            raise AssertionError("lifecycle results do not re-fetch request state")

        async def unreachable_alert_reread() -> AlertSnapshot:
            raise AssertionError("lifecycle results do not re-fetch alert state")

        return await _execute_dismissal(
            correlation_id=correlation_id,
            failure_root=failure_root,
            collection=collection,
            request=request,
            output_root=output_root,
            input_data={
                "run_mode": "live_ghec",
                "workflow_mode": "dismissal",
                "repository": f"{owner}/{repo}",
                "alert_number": alert_number,
                "correlation_id": correlation_id,
            },
            model_turn=None,
            reread_request=unreachable_request_reread,
            reread_alert=unreachable_alert_reread,
        )
    with tempfile.TemporaryDirectory(prefix="dependabot-validator-snapshot-") as temporary:
        snapshot_root = Path(temporary) / "repository"
        collection = await _collect_live(
            github=github,
            owner=owner,
            repo=repo,
            alert_number=alert_number,
            policy=policy,
            snapshot_root=snapshot_root,
            failure_root=failure_root,
        )

        async def reread_request() -> RequestSnapshot:
            try:
                raw = await github.get_dismissal_request(owner, repo, alert_number)
                return normalize_dismissal_request(
                    raw,
                    owner=owner,
                    repo=repo,
                    alert_number=alert_number,
                    operator_reason=operator_reason,
                    operator_justification=operator_justification,
                )
            except (GitHubAuthError, GitHubCollectionError) as error:
                raise ValueError("GitHub dismissal request re-fetch failed") from error

        async def reread_alert() -> AlertSnapshot:
            try:
                raw = await github.get_dependabot_alert(owner, repo, alert_number)
                return normalize_dependabot_alert(raw, alert_number=alert_number)
            except (GitHubAuthError, GitHubCollectionError) as error:
                raise ValueError("GitHub Dependabot alert re-fetch failed") from error

        return await _execute_dismissal(
            correlation_id=correlation_id,
            failure_root=failure_root,
            collection=collection,
            request=request,
            output_root=output_root,
            input_data={
                "run_mode": "live_ghec",
                "workflow_mode": "dismissal",
                "repository": f"{owner}/{repo}",
                "alert_number": alert_number,
                "correlation_id": correlation_id,
            },
            model_turn=model_turn,
            reread_request=reread_request,
            reread_alert=reread_alert,
        )


async def triage_live_alert(
    *,
    github: GitHubClient,
    owner: str,
    repo: str,
    alert_number: int,
    output_root: Path,
    policy_path: Path | None = None,
    model_turn: ModelTurn | None = None,
) -> Path:
    """Triage one live GHEC Dependabot alert without performing GitHub writes."""
    correlation_id = uuid.uuid4().hex
    failure_root = output_root / "_failed" / correlation_id
    _validate_live_target(owner, repo)
    policy = _load_policy(policy_path, failure_root)
    with tempfile.TemporaryDirectory(prefix="dependabot-validator-snapshot-") as temporary:
        snapshot_root = Path(temporary) / "repository"
        collection = await _collect_live(
            github=github,
            owner=owner,
            repo=repo,
            alert_number=alert_number,
            policy=policy,
            snapshot_root=snapshot_root,
            failure_root=failure_root,
        )

        async def reread_alert() -> AlertSnapshot:
            try:
                raw = await github.get_dependabot_alert(owner, repo, alert_number)
                return normalize_dependabot_alert(raw, alert_number=alert_number)
            except (GitHubAuthError, GitHubCollectionError) as error:
                raise ValueError("GitHub Dependabot alert re-fetch failed") from error

        return await _execute_triage(
            correlation_id=correlation_id,
            failure_root=failure_root,
            collection=collection,
            output_root=output_root,
            input_data={
                "run_mode": "live_ghec",
                "workflow_mode": "triage",
                "repository": f"{owner}/{repo}",
                "alert_number": alert_number,
                "correlation_id": correlation_id,
            },
            reread_alert=reread_alert,
            model_turn=model_turn,
        )
