"""Versioned investigator capability and provenance tests."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from dependabot_validator_grunt.agent_capabilities import (
    AgentCapabilityProvenance,
    InvestigatorCapability,
    load_investigator_capability_catalog,
    select_investigator_capability,
)
from dependabot_validator_grunt.copilot import CopilotConfigurationError
from dependabot_validator_grunt.workflow import WorkflowError, triage_offline_fixture

ROOT = Path(__file__).parents[1]
CASES = ROOT / "examples" / "offline-cases"


def _read_run_provenance(output_root: Path) -> AgentCapabilityProvenance:
    run_directory = next(path for path in output_root.glob("*/*/*") if "_failed" not in path.parts)
    return AgentCapabilityProvenance.model_validate_json(
        (run_directory / "agent-capability.json").read_text(encoding="utf-8")
    )


def test_capability_catalog_has_one_route_per_supported_ecosystem() -> None:
    catalog = load_investigator_capability_catalog()

    assert catalog.agent_capability_catalog_version == "1.0"
    assert {capability.capability_id for capability in catalog.capabilities} == {
        "javascript-typescript-v1",
        "python-v1",
    }


def test_capabilities_select_only_ecosystem_methodology() -> None:
    npm = select_investigator_capability("npm")
    python = select_investigator_capability("pip")
    uv = select_investigator_capability("uv")

    assert npm.capability_version == "1.3.0"
    assert python.capability_version == "1.2.0"
    assert npm.skill_name == "javascript-typescript-dependency-risk-analysis"
    assert python.skill_name == uv.skill_name == "python-dependency-risk-analysis"
    assert npm.analyzer_profile == "npm"
    assert python.analyzer_profile == uv.analyzer_profile == "python"


def test_capability_cannot_select_an_investigator_identity() -> None:
    capability = select_investigator_capability("npm")

    with pytest.raises(ValidationError):
        InvestigatorCapability.model_validate(
            {
                **capability.model_dump(mode="json"),
                "agent_name": "alternate-investigator",
            }
        )


async def test_agentic_workflow_writes_scripted_capability_provenance(
    tmp_path: Path,
) -> None:
    output = await triage_offline_fixture(
        CASES / "triage-vulnerable",
        tmp_path,
    )

    raw = json.loads((output / "agent-capability.json").read_text(encoding="utf-8"))
    provenance = AgentCapabilityProvenance.model_validate(raw)
    assert provenance.execution_mode == "scripted"
    assert provenance.capability_id == "javascript-typescript-v1"
    assert provenance.agent_name == "dependency-risk-investigator"
    assert provenance.evidence_digest
    assert provenance.task_digest
    assert provenance.requested_model is None
    assert provenance.observed_model is None


class _FatalCapabilityTurn:
    identity = "copilot:fake-model"
    execution_mode = "copilot"
    requested_model = None
    observed_model = "fake-model"
    diagnostics = ("unexpected_enabled_skill",)
    attempts = ()

    async def run(
        self,
        task: object,
        tools: object,
        *,
        max_attempts: int,
        wall_clock_seconds: int,
    ) -> dict[str, object]:
        del task, tools, max_attempts, wall_clock_seconds
        raise CopilotConfigurationError("Copilot loaded an untrusted enabled skill")


async def test_fatal_runtime_observation_still_writes_capability_provenance(
    tmp_path: Path,
) -> None:
    with pytest.raises(WorkflowError):
        await triage_offline_fixture(
            CASES / "triage-vulnerable",
            tmp_path,
            model_turn=_FatalCapabilityTurn(),
        )

    provenance = await asyncio.to_thread(_read_run_provenance, tmp_path)
    assert provenance.observed_model == "fake-model"
    assert provenance.diagnostics == ("unexpected_enabled_skill",)


class _InvalidFindingTurn(_FatalCapabilityTurn):
    async def run(
        self,
        task: object,
        tools: object,
        *,
        max_attempts: int,
        wall_clock_seconds: int,
    ) -> dict[str, object]:
        del task, tools, max_attempts, wall_clock_seconds
        raise ValueError("invalid finding")


class _CancelledTurn(_FatalCapabilityTurn):
    async def run(
        self,
        task: object,
        tools: object,
        *,
        max_attempts: int,
        wall_clock_seconds: int,
    ) -> dict[str, object]:
        del task, tools, max_attempts, wall_clock_seconds
        raise asyncio.CancelledError


@pytest.mark.parametrize(
    ("turn", "error_type"),
    (
        (_InvalidFindingTurn(), WorkflowError),
        (_CancelledTurn(), asyncio.CancelledError),
    ),
)
async def test_failed_agentic_runs_write_capability_provenance(
    tmp_path: Path,
    turn: _FatalCapabilityTurn,
    error_type: type[BaseException],
) -> None:
    with pytest.raises(error_type):
        await triage_offline_fixture(
            CASES / "triage-vulnerable",
            tmp_path,
            model_turn=turn,
        )

    provenance = await asyncio.to_thread(_read_run_provenance, tmp_path)
    assert provenance.observed_model == "fake-model"
