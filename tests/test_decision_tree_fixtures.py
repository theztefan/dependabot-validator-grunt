"""Committed fixture coverage for the dismissal decision tree."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict, TypeAdapter, model_validator

from dependabot_validator_grunt.workflow import review_offline_fixture, triage_offline_fixture

ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "examples" / "offline-cases"
MANIFEST = Path(__file__).with_name("decision_tree_cases.json")


class DecisionTreeCase(BaseModel):
    """One test-only mapping from a criterion to an offline fixture result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fixture: str
    workflow_mode: Literal["dismissal", "triage"]
    criteria: tuple[str, ...]
    scenario_criteria: tuple[str, ...] = ()
    result_kind: Literal["dismissal_decision", "triage_decision"]
    recommendation: Literal["approve", "deny", "human_review"] | None = None
    assessment: Literal["applies", "does_not_apply", "human_review"] | None = None
    recommended_action: Literal["remediate", "investigate", "monitor", "none"] | None = None
    reason_code: str

    @model_validator(mode="after")
    def validate_expected_result(self) -> DecisionTreeCase:
        if self.workflow_mode == "dismissal":
            if self.result_kind != "dismissal_decision" or self.recommendation is None:
                raise ValueError("dismissal fixture requires a dismissal expectation")
            if self.assessment is not None or self.recommended_action is not None:
                raise ValueError("dismissal fixture cannot contain triage expectations")
        elif (
            self.result_kind != "triage_decision"
            or self.assessment is None
            or self.recommended_action is None
        ):
            raise ValueError("triage fixture requires a triage expectation")
        elif self.recommendation is not None:
            raise ValueError("triage fixture cannot contain a dismissal recommendation")
        return self


def _cases() -> tuple[DecisionTreeCase, ...]:
    raw = TypeAdapter(dict[str, object]).validate_python(
        json.loads(MANIFEST.read_text(encoding="utf-8"))
    )
    assert raw.get("version") == 1
    return TypeAdapter(tuple[DecisionTreeCase, ...]).validate_python(raw.get("cases"))


CASES = _cases()
COMMON_FIXTURE_ENTRIES = {
    "agent-response.json",
    "alert.json",
    "case.json",
    "policy.json",
    "post-analysis-alert.json",
    "repository",
}


def test_manifest_covers_every_committed_offline_fixture() -> None:
    """Keep every standalone offline fixture and expectation synchronized."""
    expected = {case.fixture for case in CASES}
    actual = {path.name for path in FIXTURES.iterdir() if path.is_dir()}

    assert actual == expected
    assert all(case.criteria or case.scenario_criteria for case in CASES)
    assert len(expected) == len(CASES)
    known_criteria = {
        *(f"R{index}" for index in range(1, 7)),
        *(f"J{index}" for index in range(1, 6)),
        *(f"A{index}" for index in range(1, 7)),
        "A8",
        *(f"D{index}" for index in range(1, 6)),
        *(f"E{index}" for index in range(1, 3)),
        *(f"P{index}" for index in range(1, 5)),
        *(f"F{index}" for index in range(1, 5)),
        *(f"T{index}" for index in range(1, 4)),
    }
    covered_criteria = {
        criterion for case in CASES for criterion in case.criteria + case.scenario_criteria
    }
    assert covered_criteria <= known_criteria
    required_fixture_criteria = {
        *(f"R{index}" for index in range(1, 7)),
        *(f"A{index}" for index in range(1, 7)),
        "A8",
        "D1",
        "D5",
        *(f"E{index}" for index in range(1, 3)),
        *(f"P{index}" for index in range(1, 4)),
        "F3",
        *(f"T{index}" for index in range(1, 4)),
    }
    behavior_criteria = {criterion for case in CASES for criterion in case.criteria}
    assert required_fixture_criteria <= behavior_criteria
    for case in CASES:
        root = FIXTURES / case.fixture
        assert (root / "case.json").is_file()
        assert (root / "alert.json").is_file()
        assert (root / "repository").is_dir()
        assert (root / "request.json").is_file() == (case.workflow_mode == "dismissal")


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.fixture)
def test_fixture_contains_only_workflow_supported_entries(case: DecisionTreeCase) -> None:
    """Keep committed fixtures free of ignored or orphaned top-level files."""
    root = FIXTURES / case.fixture
    allowed = set(COMMON_FIXTURE_ENTRIES)
    if case.workflow_mode == "dismissal":
        allowed.update({"request.json", "post-analysis-request.json"})

    actual = {path.name for path in root.iterdir()}
    assert actual <= allowed
    assert all(path.is_file() for path in root.iterdir() if path.name != "repository")


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.fixture)
async def test_decision_tree_fixture_result(
    case: DecisionTreeCase,
    tmp_path: Path,
) -> None:
    """Run every committed dismissal fixture through the complete workflow."""
    if case.workflow_mode == "dismissal":
        output = await review_offline_fixture(FIXTURES / case.fixture, tmp_path)
    else:
        output = await triage_offline_fixture(FIXTURES / case.fixture, tmp_path)
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    result = TypeAdapter(dict[str, object]).validate_python(report["result"])

    assert result["result_kind"] == case.result_kind
    assert result["reason_code"] == case.reason_code
    if case.workflow_mode == "dismissal":
        assert result["recommendation"] == case.recommendation
    else:
        assert result["assessment"] == case.assessment
        assert result["recommended_action"] == case.recommended_action
