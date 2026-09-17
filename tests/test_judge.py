from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from dependabot_validator_grunt.agentic import RepositoryTools
from dependabot_validator_grunt.copilot_assets import load_judge_assets
from dependabot_validator_grunt.judge import (
    MAX_JUDGE_INPUT_CHARACTERS,
    JudgedModelTurn,
    canonical_json,
    judge_payload,
    render_judge_prompt,
    validate_judge_review,
)
from dependabot_validator_grunt.models import (
    AgentFinding,
    AgentProposalPermission,
    AgentTask,
    CriticAssessment,
    DependencyInstance,
    JudgeFailure,
    JudgeReview,
)


def _task() -> AgentTask:
    return AgentTask(
        correlation_id="correlation",
        repository_id="owner/repository",
        alert_number=7,
        request_id="request",
        dismissal_reason="not_used",
        snapshot_id="snapshot",
        policy_digest="policy",
        ecosystem="pip",
        dependency_package_manager="pip",
        dependency_version_scheme="pep440",
        permitted_proposals=(
            AgentProposalPermission(
                recommendation="deny",
                reason_codes=("advisory_applies",),
            ),
            AgentProposalPermission(
                recommendation="human_review",
                reason_codes=("insufficient_context",),
            ),
        ),
    )


def _finding(task: AgentTask, *, claim: str = "No supported conclusion.") -> AgentFinding:
    return AgentFinding(
        workflow_mode=task.workflow_mode,
        correlation_id=task.correlation_id,
        repository_id=task.repository_id,
        alert_number=task.alert_number,
        request_id=task.request_id,
        snapshot_id=task.snapshot_id,
        policy_digest=task.policy_digest,
        claim=claim,
        citations=(),
        uncertainty="No repository fact was cited.",
        proposed_recommendation="human_review",
        policy_reason_code="insufficient_context",
        confidence=0.5,
        insufficient_context=True,
        injection_detected=False,
    )


def _critic(
    lens: str, verdict: str = "support", issue_codes: tuple[str, ...] = ()
) -> CriticAssessment:
    return CriticAssessment.model_validate(
        {
            "lens": lens,
            "verdict": verdict,
            "issue_codes": issue_codes,
            "rationale": "The conclusion is proportionate to the bounded evidence.",
        }
    )


def _review(
    task: AgentTask,
    *,
    verdict: str = "accept",
    replacement: AgentFinding | None = None,
) -> JudgeReview:
    applicability_verdict = "material_challenge" if verdict == "replace" else "support"
    issue_codes = ("scope_misread",) if verdict == "replace" else ()
    return JudgeReview.model_validate(
        {
            "workflow_mode": task.workflow_mode,
            "correlation_id": task.correlation_id,
            "repository_id": task.repository_id,
            "alert_number": task.alert_number,
            "request_id": task.request_id,
            "snapshot_id": task.snapshot_id,
            "policy_digest": task.policy_digest,
            "evidence_critic": _critic("evidence").model_dump(mode="json"),
            "applicability_critic": _critic(
                "applicability", applicability_verdict, issue_codes
            ).model_dump(mode="json"),
            "verdict": verdict,
            "rationale": "The forum reached a bounded adjudication.",
            "replacement_finding": (
                replacement.model_dump(mode="json") if replacement is not None else None
            ),
        }
    )


def test_critic_issue_codes_match_verdict() -> None:
    with pytest.raises(ValidationError):
        _critic("evidence", "support", ("unsupported_claim",))
    with pytest.raises(ValidationError):
        _critic("evidence", "minor_concern")
    with pytest.raises(ValidationError):
        _critic("evidence", "material_challenge", ("no_material_issue",))


def test_judge_verdict_requires_consistent_challenge_and_replacement() -> None:
    task = _task()
    replacement = _finding(task, claim="Corrected conclusion.")

    with pytest.raises(ValidationError):
        JudgeReview.model_validate(
            {
                **_review(task).model_dump(mode="json"),
                "replacement_finding": replacement.model_dump(mode="json"),
            }
        )
    with pytest.raises(ValidationError):
        JudgeReview.model_validate(
            {
                **_review(task).model_dump(mode="json"),
                "verdict": "replace",
            }
        )


def test_validate_judge_review_rejects_identity_mismatch(tmp_path: Path) -> None:
    task = _task()
    review = _review(task).model_copy(update={"snapshot_id": "other"})

    with pytest.raises(ValueError, match="identity"):
        validate_judge_review(
            review,
            task=task,
            primary_finding=_finding(task),
            tools=RepositoryTools(tmp_path),
        )


def test_validate_judge_review_rejects_unobserved_replacement_citation(
    tmp_path: Path,
) -> None:
    task = _task()
    replacement = AgentFinding.model_validate(
        {
            **_finding(task, claim="Corrected conclusion.").model_dump(mode="json"),
            "citations": [
                {
                    "path": "package.json",
                    "line": 1,
                    "excerpt": "{}",
                    "digest": "0" * 64,
                }
            ],
        }
    )
    review = _review(task, verdict="replace", replacement=replacement)

    with pytest.raises(ValueError):
        validate_judge_review(
            review,
            task=task,
            primary_finding=_finding(task),
            tools=RepositoryTools(tmp_path),
        )


@pytest.mark.parametrize("blocker", ("insufficient_context", "injection_detected"))
def test_validate_judge_review_cannot_clear_primary_blocker(
    blocker: str,
    tmp_path: Path,
) -> None:
    task = _task()
    primary = _finding(task).model_copy(update={blocker: True})
    replacement = _finding(task, claim="Corrected conclusion.").model_copy(update={blocker: False})
    review = _review(task, verdict="replace", replacement=replacement)

    with pytest.raises(ValueError, match="cannot clear"):
        validate_judge_review(
            review,
            task=task,
            primary_finding=primary,
            tools=RepositoryTools(tmp_path),
        )


def test_validate_judge_review_rejects_observed_but_unexposed_citation(
    tmp_path: Path,
) -> None:
    task = _task()
    tools = RepositoryTools(tmp_path)
    (tmp_path / "package.json").write_text("needle\n" * 9, encoding="utf-8")
    observed = tools.search("needle")
    primary = _finding(task).model_copy(update={"citations": tuple(observed)})
    replacement = _finding(task, claim="Corrected conclusion.").model_copy(
        update={"citations": (observed[-1],)}
    )
    review = _review(task, verdict="replace", replacement=replacement)

    with pytest.raises(ValueError, match="outside its frozen context"):
        validate_judge_review(
            review,
            task=task,
            primary_finding=primary,
            tools=tools,
        )


def test_judge_prompt_is_bounded_for_large_context(tmp_path: Path) -> None:
    task = _task()
    tools = RepositoryTools(tmp_path, max_read_bytes=2_000_000)
    for index in range(20):
        path = tmp_path / f"source-{index}.js"
        path.write_text(("const value = 'large';\n" * 1000), encoding="utf-8")
        tools.read_file(path.name)
    finding = _finding(task, claim="x" * 20_000)

    payload = judge_payload(task, finding, tools)
    prompt = render_judge_prompt(load_judge_assets().prompt_template, task, finding, tools)

    assert len(canonical_json(payload)) <= 12_000
    assert len(prompt) <= MAX_JUDGE_INPUT_CHARACTERS
    assert json.loads(canonical_json(payload))["primary_finding"]["claim_truncated"] is True


def test_judge_payload_includes_bounded_applicability_context(tmp_path: Path) -> None:
    task = _task().model_copy(
        update={
            "dependency_completeness": "complete",
            "installed_instance_count": 1,
            "installed_instance_details": (
                DependencyInstance(
                    path="node_modules/package",
                    version="1.0.0",
                    relationship="development",
                    comparable=True,
                    development_only=True,
                    source_kind="registry",
                ),
            ),
            "dependency_consumer_count": 1,
            "dependency_consumers": ("node_modules/consumer",),
        }
    )

    payload = judge_payload(task, _finding(task), RepositoryTools(tmp_path))
    task_payload = payload["task"]

    assert isinstance(task_payload, dict)
    assert task_payload["dependency_completeness"] == "complete"
    assert "installed_instances" not in task_payload
    assert task_payload["installed_instance_count"] == 1
    assert task_payload["dependency_consumers"] == ["node_modules/consumer"]
    assert task_payload["installed_instance_details"] == [
        {
            "path": "node_modules/package",
            "version": "1.0.0",
            "relationship": "development",
            "comparable": True,
            "development_only": True,
            "source_kind": "registry",
            "source_locator": None,
        }
    ]


class _Primary:
    identity = "primary-model"

    def __init__(self, finding: AgentFinding) -> None:
        self.finding = finding

    async def run(
        self,
        task: AgentTask,
        tools: RepositoryTools,
        *,
        max_attempts: int,
        wall_clock_seconds: float,
    ) -> dict[str, object]:
        del task, tools, max_attempts, wall_clock_seconds
        return {"finding": self.finding.model_dump(mode="json")}


class _Judge:
    def __init__(self, result: JudgeReview | JudgeFailure | Exception) -> None:
        self.result = result

    async def review(
        self,
        *,
        task: AgentTask,
        finding: AgentFinding,
        tools: RepositoryTools,
        timeout_seconds: float,
    ) -> JudgeReview | JudgeFailure:
        del task, finding, tools, timeout_seconds
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.mark.asyncio
async def test_judged_turn_accepts_primary_finding_unchanged(tmp_path: Path) -> None:
    task = _task()
    primary = _finding(task)
    turn = JudgedModelTurn(_Primary(primary), lambda: _Judge(_review(task)))

    output = await turn.run(
        task,
        RepositoryTools(tmp_path),
        max_attempts=2,
        wall_clock_seconds=360,
    )

    assert AgentFinding.model_validate(output["finding"]) == primary
    assert JudgeReview.model_validate(output["judge_review"]).verdict == "accept"


@pytest.mark.asyncio
async def test_judged_turn_uses_valid_replacement(tmp_path: Path) -> None:
    task = _task()
    primary = _finding(task)
    replacement = _finding(task, claim="Corrected conclusion.")
    turn = JudgedModelTurn(
        _Primary(primary),
        lambda: _Judge(_review(task, verdict="replace", replacement=replacement)),
    )

    output = await turn.run(
        task,
        RepositoryTools(tmp_path),
        max_attempts=2,
        wall_clock_seconds=360,
    )

    assert AgentFinding.model_validate(output["finding"]) == replacement
    assert AgentFinding.model_validate(output["primary_finding"]) == primary


@pytest.mark.asyncio
async def test_judged_turn_retains_primary_when_judge_fails(tmp_path: Path) -> None:
    task = _task()
    primary = _finding(task)
    turn = JudgedModelTurn(_Primary(primary), lambda: _Judge(RuntimeError("unavailable")))

    output = await turn.run(
        task,
        RepositoryTools(tmp_path),
        max_attempts=2,
        wall_clock_seconds=360,
    )

    assert AgentFinding.model_validate(output["finding"]) == primary
    assert JudgeFailure.model_validate(output["judge_review"]).reason == "sdk_failure"


@pytest.mark.asyncio
async def test_judged_turn_constructs_judge_only_after_primary_validation(
    tmp_path: Path,
) -> None:
    task = _task()
    primary = _finding(task)
    constructions = 0

    def judge_provider() -> _Judge:
        nonlocal constructions
        constructions += 1
        return _Judge(_review(task))

    turn = JudgedModelTurn(_Primary(primary), judge_provider)

    assert constructions == 0
    await turn.run(
        task,
        RepositoryTools(tmp_path),
        max_attempts=2,
        wall_clock_seconds=360,
    )
    assert constructions == 1


@pytest.mark.asyncio
async def test_judged_turn_retains_primary_when_judge_construction_fails(
    tmp_path: Path,
) -> None:
    task = _task()
    primary = _finding(task)

    def judge_provider() -> _Judge:
        raise RuntimeError("broken judge assets")

    output = await JudgedModelTurn(_Primary(primary), judge_provider).run(
        task,
        RepositoryTools(tmp_path),
        max_attempts=2,
        wall_clock_seconds=360,
    )

    assert AgentFinding.model_validate(output["finding"]) == primary
    assert JudgeFailure.model_validate(output["judge_review"]).reason == "sdk_failure"


@pytest.mark.asyncio
async def test_judged_turn_does_not_construct_judge_when_primary_fails(
    tmp_path: Path,
) -> None:
    task = _task()
    constructions = 0

    class FailingPrimary:
        identity = "failing-primary"

        async def run(
            self,
            task: AgentTask,
            tools: RepositoryTools,
            *,
            max_attempts: int,
            wall_clock_seconds: float,
        ) -> dict[str, object]:
            del task, tools, max_attempts, wall_clock_seconds
            raise ValueError("primary failed")

    def judge_provider() -> _Judge:
        nonlocal constructions
        constructions += 1
        return _Judge(_review(task))

    with pytest.raises(ValueError, match="primary failed"):
        await JudgedModelTurn(FailingPrimary(), judge_provider).run(
            task,
            RepositoryTools(tmp_path),
            max_attempts=2,
            wall_clock_seconds=360,
        )

    assert constructions == 0


@pytest.mark.asyncio
async def test_judged_turn_validates_reachability_before_constructing_judge(
    tmp_path: Path,
) -> None:
    task = _task().model_copy(
        update={
            "ecosystem": "npm",
            "package_name": "lodash",
            "package_identity": "lodash",
            "dependency_package_manager": "npm",
            "dependency_version_scheme": "npm",
        }
    )
    primary = _finding(task)
    constructions = 0

    def judge_provider() -> _Judge:
        nonlocal constructions
        constructions += 1
        return _Judge(_review(task))

    class NoReachabilityPrimary(_Primary):
        async def run(
            self,
            task: AgentTask,
            tools: RepositoryTools,
            *,
            max_attempts: int,
            wall_clock_seconds: float,
        ) -> dict[str, object]:
            del task, tools, max_attempts, wall_clock_seconds
            return {"finding": self.finding.model_dump(mode="json")}

    with pytest.raises(ValueError, match="reachability analysis was not invoked"):
        await JudgedModelTurn(NoReachabilityPrimary(primary), judge_provider).run(
            task,
            RepositoryTools(tmp_path),
            max_attempts=2,
            wall_clock_seconds=360,
        )

    assert constructions == 0
