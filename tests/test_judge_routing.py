"""Judge routing tests for terminal deterministic workflow paths."""

from __future__ import annotations

import json
from pathlib import Path

from dependabot_validator_grunt.agentic import RepositoryTools
from dependabot_validator_grunt.judge import JudgedModelTurn
from dependabot_validator_grunt.models import (
    AgentFinding,
    AgentTask,
    JudgeFailure,
    JudgeReview,
)
from dependabot_validator_grunt.workflow import (
    review_offline_fixture,
    triage_offline_fixture,
)

ROOT = Path(__file__).parents[1]
CASES = ROOT / "examples" / "offline-cases"


class _ForbiddenPrimary:
    identity = "forbidden-primary"

    async def run(
        self,
        task: AgentTask,
        tools: RepositoryTools,
        *,
        max_attempts: int,
        wall_clock_seconds: int,
    ) -> dict[str, object]:
        del task, tools, max_attempts, wall_clock_seconds
        raise AssertionError("terminal deterministic route invoked the primary model")


class _ForbiddenJudge:
    async def review(
        self,
        *,
        task: AgentTask,
        finding: AgentFinding,
        tools: RepositoryTools,
        timeout_seconds: float,
    ) -> JudgeReview | JudgeFailure:
        del task, finding, tools, timeout_seconds
        raise AssertionError("terminal deterministic route invoked the judge")


def _forbidden_agentic_boundary() -> JudgedModelTurn:
    return JudgedModelTurn(_ForbiddenPrimary(), _ForbiddenJudge())


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


async def test_terminal_deterministic_dismissal_makes_zero_llm_calls(
    tmp_path: Path,
) -> None:
    output = await review_offline_fixture(
        CASES / "not-used-absent",
        tmp_path,
        model_turn=_forbidden_agentic_boundary(),
    )

    report = _read_json(output / "report.json")
    result = report["result"]
    assert isinstance(result, dict)
    assert result["result_kind"] == "dismissal_decision"
    assert report["model_identity"] == "not_run"
    assert not list(output.glob("agent-*.json"))
    assert not (output / "judge-review.json").exists()


async def test_terminal_deterministic_triage_makes_zero_llm_calls(
    tmp_path: Path,
) -> None:
    output = await triage_offline_fixture(
        CASES / "triage-absent",
        tmp_path,
        model_turn=_forbidden_agentic_boundary(),
    )

    report = _read_json(output / "report.json")
    result = report["result"]
    assert isinstance(result, dict)
    assert result["assessment"] == "does_not_apply"
    assert report["model_identity"] == "not_run"
    assert not list(output.glob("agent-*.json"))
    assert not (output / "judge-review.json").exists()
