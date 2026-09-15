"""Token-bounded two-critic review over one validated agent finding."""

from __future__ import annotations

import asyncio
import time
from typing import Protocol

from pydantic import TypeAdapter

from dependabot_validator_grunt.agentic import RepositoryTools, validate_finding
from dependabot_validator_grunt.models import (
    AgentFinding,
    AgentTask,
    JudgeFailure,
    JudgeReview,
    canonical_json,
)

MAX_JUDGE_INPUT_CHARACTERS = 16_000
MAX_JUDGE_PAYLOAD_CHARACTERS = 12_000
MAX_JUDGE_OUTPUT_CHARACTERS = 8_000
MAX_JUDGE_SECONDS = 60
MAX_JUDGE_CITATIONS = 8
MAX_JUDGE_INSTANCES = 20
MAX_JUDGE_DECLARATIONS = 12
JUDGE_PLACEHOLDER = "{{judge_json}}"


class PrimaryModelTurn(Protocol):
    """Primary finding producer composed with the judge."""

    identity: str

    async def run(
        self,
        task: AgentTask,
        tools: RepositoryTools,
        *,
        max_attempts: int,
        wall_clock_seconds: int,
    ) -> dict[str, object]: ...


class FindingJudge(Protocol):
    """Judge seam replaced by deterministic fakes in offline tests."""

    async def review(
        self,
        *,
        task: AgentTask,
        finding: AgentFinding,
        tools: RepositoryTools,
        timeout_seconds: float,
    ) -> JudgeReview | JudgeFailure: ...


def judge_payload(
    task: AgentTask,
    finding: AgentFinding,
    tools: RepositoryTools,
) -> dict[str, object]:
    """Build compact frozen context for the no-tool judge."""
    citations = tuple(finding.citations[:MAX_JUDGE_CITATIONS])
    reachability = tools.reachability_evidence
    payload: dict[str, object] = {
        "task": {
            "workflow_mode": task.workflow_mode,
            "correlation_id": task.correlation_id,
            "repository_id": task.repository_id,
            "alert_number": task.alert_number,
            "request_id": task.request_id,
            "snapshot_id": task.snapshot_id,
            "policy_digest": task.policy_digest,
            "dismissal_reason": task.dismissal_reason,
            "justification": task.justification[:1200],
            "advisory_summary": task.advisory_summary[:1200],
            "package_name": task.package_name,
            "vulnerable_range": task.vulnerable_range,
            "manifest_path": task.manifest_path,
            "dependency_scope": task.dependency_scope,
            "installed_instance_count": task.installed_instance_count,
            "installed_instances": [
                value[:240] for value in task.installed_instances[:MAX_JUDGE_INSTANCES]
            ],
            "installed_instance_details": [
                instance.model_dump(mode="json")
                for instance in task.installed_instance_details[:MAX_JUDGE_INSTANCES]
            ],
            "installed_instance_details_truncated": (
                len(task.installed_instance_details) > MAX_JUDGE_INSTANCES
            ),
            "dependency_package_manager": task.dependency_package_manager,
            "dependency_lockfile_version": task.dependency_lockfile_version,
            "npm_completeness": task.npm_completeness,
            "dependency_evidence_capabilities": list(task.dependency_evidence_capabilities),
            "dependency_consumer_count": len(task.dependency_consumers),
            "dependency_consumers": [
                value[:240] for value in task.dependency_consumers[:MAX_JUDGE_INSTANCES]
            ],
            "dependency_consumers_truncated": (
                len(task.dependency_consumers) > MAX_JUDGE_INSTANCES
            ),
            "manifest_declarations": [
                declaration.model_dump(mode="json")
                for declaration in task.manifest_declarations[:MAX_JUDGE_DECLARATIONS]
            ],
            "repository_file_count": task.repository_file_count,
            "permitted_proposals": [
                permission.model_dump(mode="json") for permission in task.permitted_proposals
            ],
        },
        "primary_finding": {
            **finding.model_dump(mode="json", exclude={"citations"}),
            "citations": [citation.model_dump(mode="json") for citation in citations],
            "citation_count": len(finding.citations),
            "citations_truncated": len(citations) != len(finding.citations),
        },
        "reachability": (
            {
                "status": reachability.status,
                "engine": reachability.engine,
                "engine_version": reachability.engine_version,
                "scanned_files": reachability.scanned_files,
                "scanned_bytes": reachability.scanned_bytes,
                "finding_count": len(reachability.findings),
                "limitations": list(reachability.limitations[:4]),
            }
            if reachability is not None
            else None
        ),
        "repository_reference_evidence": (
            task.repository_reference_evidence.model_dump(mode="json")
            if task.repository_reference_evidence is not None
            else None
        ),
    }
    if len(canonical_json(payload)) > MAX_JUDGE_PAYLOAD_CHARACTERS:
        task_payload = TypeAdapter(dict[str, object]).validate_python(payload["task"])
        task_payload["justification"] = task.justification[:400]
        task_payload["advisory_summary"] = task.advisory_summary[:400]
        task_payload["installed_instances"] = [
            value[:160] for value in task.installed_instances[:5]
        ]
        task_payload["installed_instance_details"] = [
            instance.model_dump(mode="json") for instance in task.installed_instance_details[:5]
        ]
        task_payload["installed_instance_details_truncated"] = (
            len(task.installed_instance_details) > 5
        )
        task_payload["dependency_consumers"] = [
            value[:160] for value in task.dependency_consumers[:5]
        ]
        task_payload["dependency_consumers_truncated"] = len(task.dependency_consumers) > 5
        task_payload["manifest_declarations"] = [
            declaration.model_dump(mode="json") for declaration in task.manifest_declarations[:5]
        ]
        finding_payload = TypeAdapter(dict[str, object]).validate_python(payload["primary_finding"])
        finding_payload["citations"] = [
            citation.model_dump(mode="json") for citation in finding.citations[:4]
        ]
        finding_payload["citations_truncated"] = len(finding.citations) > 4
        finding_payload["claim"] = finding.claim[:1600]
        finding_payload["claim_truncated"] = len(finding.claim) > 1600
        finding_payload["uncertainty"] = finding.uncertainty[:600]
        payload["task"] = task_payload
        payload["primary_finding"] = finding_payload
    if len(canonical_json(payload)) > MAX_JUDGE_PAYLOAD_CHARACTERS:
        raise ValueError("judge input exceeds the compact context limit")
    return payload


def render_judge_prompt(
    template: str,
    task: AgentTask,
    finding: AgentFinding,
    tools: RepositoryTools,
) -> str:
    """Render one bounded judge prompt from the validated role template."""
    if template.count(JUDGE_PLACEHOLDER) != 1:
        raise ValueError("judge prompt must contain exactly one context placeholder")
    rendered = template.replace(
        JUDGE_PLACEHOLDER, canonical_json(judge_payload(task, finding, tools))
    )
    if len(rendered) > MAX_JUDGE_INPUT_CHARACTERS:
        raise ValueError("rendered judge prompt exceeds the compact context limit")
    return rendered


def validate_judge_review(
    review: JudgeReview,
    *,
    task: AgentTask,
    primary_finding: AgentFinding,
    tools: RepositoryTools,
) -> AgentFinding:
    """Validate judge identity and return the selected finding."""
    identity = (
        review.workflow_mode,
        review.correlation_id,
        review.repository_id,
        review.alert_number,
        review.request_id,
        review.snapshot_id,
        review.policy_digest,
    )
    expected = (
        task.workflow_mode,
        task.correlation_id,
        task.repository_id,
        task.alert_number,
        task.request_id,
        task.snapshot_id,
        task.policy_digest,
    )
    if identity != expected:
        raise ValueError("judge review identity does not match the assigned task")
    if review.verdict == "accept":
        return primary_finding
    replacement = review.replacement_finding
    if replacement is None:
        raise ValueError("judge replacement finding is missing")
    selected = validate_finding(replacement.model_dump(mode="json"), task, tools)
    payload = judge_payload(task, primary_finding, tools)
    finding_payload = TypeAdapter(dict[str, object]).validate_python(payload["primary_finding"])
    exposed_citations = TypeAdapter(list[dict[str, object]]).validate_python(
        finding_payload["citations"]
    )
    allowed_citations = {canonical_json(citation) for citation in exposed_citations}
    if any(
        canonical_json(citation.model_dump(mode="json")) not in allowed_citations
        for citation in selected.citations
    ):
        raise ValueError("judge replacement cites evidence outside its frozen context")
    return selected


class JudgedModelTurn:
    """Compose a primary model turn with one non-blocking judge forum."""

    def __init__(self, primary: PrimaryModelTurn, judge: FindingJudge) -> None:
        self.primary = primary
        self.judge = judge
        self.identity = getattr(primary, "identity", "copilot:not_run")

    async def run(
        self,
        task: AgentTask,
        tools: RepositoryTools,
        *,
        max_attempts: int,
        wall_clock_seconds: int,
    ) -> dict[str, object]:
        deadline = time.monotonic() + wall_clock_seconds
        raw = await self.primary.run(
            task,
            tools,
            max_attempts=max_attempts,
            wall_clock_seconds=wall_clock_seconds,
        )
        self.identity = self.primary.identity
        raw_finding = TypeAdapter(dict[str, object]).validate_python(raw.get("finding"))
        primary_finding = validate_finding(raw_finding, task, tools)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            failure = JudgeFailure(
                reason="timeout",
                message="Judge forum skipped because the shared deadline was exhausted.",
            )
            return {
                **raw,
                "primary_finding": primary_finding.model_dump(mode="json"),
                "judge_review": failure.model_dump(mode="json"),
            }
        try:
            review = await self.judge.review(
                task=task,
                finding=primary_finding,
                tools=tools,
                timeout_seconds=min(remaining, MAX_JUDGE_SECONDS),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            review = JudgeFailure(
                reason="sdk_failure",
                message="Judge forum was unavailable; primary finding retained.",
            )
        if isinstance(review, JudgeFailure):
            return {
                **raw,
                "primary_finding": primary_finding.model_dump(mode="json"),
                "judge_review": review.model_dump(mode="json"),
            }
        try:
            selected = validate_judge_review(
                review,
                task=task,
                primary_finding=primary_finding,
                tools=tools,
            )
        except ValueError:
            failure = JudgeFailure(
                reason="invalid_review",
                message="Judge replacement failed trusted validation; primary finding retained.",
            )
            return {
                **raw,
                "primary_finding": primary_finding.model_dump(mode="json"),
                "judge_review": failure.model_dump(mode="json"),
            }
        return {
            **raw,
            "primary_finding": primary_finding.model_dump(mode="json"),
            "finding": selected.model_dump(mode="json"),
            "judge_review": review.model_dump(mode="json"),
        }
