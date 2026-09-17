"""Closed investigator capabilities and execution provenance."""

from __future__ import annotations

import hashlib
from functools import cache
from importlib.resources import files
from typing import Literal

from pydantic import Field, model_validator

from dependabot_validator_grunt.models import (
    AgentTask,
    Ecosystem,
    FrozenModel,
    PackageManager,
    ReachabilityProfile,
    analysis_family,
    canonical_json,
)

CAPABILITY_CATALOG_ASSET = "agents/investigator-capabilities.json"
CAPABILITY_FORMAT_VERSION = "1.0"
INVESTIGATOR_AGENT_MANIFEST_ASSET = "agents/dependency-risk-investigator/agent.json"
INVESTIGATOR_AGENT_NAME = "dependency-risk-investigator"
INVESTIGATOR_ROLE_PROMPT_ASSET = "agents/dependency-risk-investigator/prompt.md"

ExecutionMode = Literal["scripted", "copilot"]
AttemptOutcomeName = Literal[
    "success",
    "timeout",
    "missing_response",
    "malformed_output",
    "sdk_failure",
]


class AgentCapabilityError(ValueError):
    """Invalid packaged capability configuration or selection."""


class InvestigatorCapability(FrozenModel):
    """One immutable investigator configuration selected by trusted Python."""

    capability_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    capability_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    ecosystems: tuple[Ecosystem, ...]
    analyzer_profile: ReachabilityProfile
    skill_asset: str
    skill_name: str

    @model_validator(mode="after")
    def validate_semantics(self) -> InvestigatorCapability:
        if not self.ecosystems or len(set(self.ecosystems)) != len(self.ecosystems):
            raise ValueError("investigator capability ecosystems must be non-empty and unique")
        families = {analysis_family(ecosystem) for ecosystem in self.ecosystems}
        if len(families) != 1:
            raise ValueError("investigator capability analyzer profile is inconsistent")
        match next(iter(families)):
            case "javascript_typescript":
                expected_profile: ReachabilityProfile = "npm"
            case "python":
                expected_profile = "python"
            case _:
                raise ValueError("investigator capability analysis family is unsupported")
        if self.analyzer_profile != expected_profile:
            raise ValueError("investigator capability analyzer profile is inconsistent")
        return self

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_json(self).encode()).hexdigest()


class InvestigatorCapabilityCatalog(FrozenModel):
    """Versioned closed package-data catalog."""

    agent_capability_catalog_version: Literal["1.0"]
    capabilities: tuple[InvestigatorCapability, ...]

    @model_validator(mode="after")
    def validate_catalog(self) -> InvestigatorCapabilityCatalog:
        keys = tuple(
            ecosystem for capability in self.capabilities for ecosystem in capability.ecosystems
        )
        if len(set(keys)) != len(keys):
            raise ValueError("investigator capability selections must be unique")
        expected = {"npm", "pip", "uv"}
        if set(keys) != expected:
            raise ValueError("investigator capability catalog is incomplete")
        return self


class AgentCapabilityAttempt(FrozenModel):
    """One classified investigator attempt in provenance."""

    number: int = Field(ge=1)
    outcome: AttemptOutcomeName


class AgentCapabilityProvenance(FrozenModel):
    """Auditable non-authoritative configuration provenance."""

    agent_capability_format_version: Literal["1.0"] = CAPABILITY_FORMAT_VERSION
    correlation_id: str
    task_digest: str
    snapshot_id: str
    policy_digest: str
    evidence_digest: str
    ecosystem: Ecosystem
    package_manager: PackageManager
    execution_mode: ExecutionMode
    capability_id: str
    capability_version: str
    capability_digest: str
    agent_name: str
    role_prompt_asset: str
    role_prompt_digest: str
    skill_name: str
    skill_asset: str
    skill_digest: str
    analyzer_profile: ReachabilityProfile
    tool_names: tuple[str, ...]
    requested_model: str | None = None
    observed_model: str | None = None
    diagnostics: tuple[str, ...] = ()
    attempts: tuple[AgentCapabilityAttempt, ...] = ()


def _read_asset(relative_path: str) -> str:
    content = (
        files("dependabot_validator_grunt")
        .joinpath(*relative_path.split("/"))
        .read_text(encoding="utf-8")
    )
    if not content.strip():
        raise ValueError(f"agent capability asset is empty: {relative_path}")
    return content.replace("\r\n", "\n")


@cache
def load_investigator_capability_catalog() -> InvestigatorCapabilityCatalog:
    """Load and validate the exact packaged investigator catalog."""
    try:
        return InvestigatorCapabilityCatalog.model_validate_json(
            _read_asset(CAPABILITY_CATALOG_ASSET)
        )
    except (OSError, UnicodeError, ValueError) as error:
        raise AgentCapabilityError("investigator capability catalog is invalid") from error


def select_investigator_capability(
    ecosystem: Ecosystem,
) -> InvestigatorCapability:
    """Select exactly one packaged capability for the assigned task."""
    matches = tuple(
        capability
        for capability in load_investigator_capability_catalog().capabilities
        if ecosystem in capability.ecosystems
    )
    if len(matches) != 1:
        raise AgentCapabilityError("investigator capability selection is invalid")
    return matches[0]


def build_capability_provenance(
    *,
    task: AgentTask,
    evidence_digest: str,
    capability: InvestigatorCapability,
    execution_mode: ExecutionMode,
    tool_names: tuple[str, ...],
    requested_model: str | None,
    observed_model: str | None,
    diagnostics: tuple[str, ...],
    attempts: tuple[AgentCapabilityAttempt, ...],
) -> AgentCapabilityProvenance:
    """Build provenance from the task, capability, fixed assets, and runtime."""
    return AgentCapabilityProvenance(
        correlation_id=task.correlation_id,
        task_digest=hashlib.sha256(canonical_json(task).encode()).hexdigest(),
        snapshot_id=task.snapshot_id,
        policy_digest=task.policy_digest,
        evidence_digest=evidence_digest,
        ecosystem=task.ecosystem,
        package_manager=task.dependency_package_manager,
        execution_mode=execution_mode,
        capability_id=capability.capability_id,
        capability_version=capability.capability_version,
        capability_digest=capability.digest,
        agent_name=INVESTIGATOR_AGENT_NAME,
        role_prompt_asset=INVESTIGATOR_ROLE_PROMPT_ASSET,
        role_prompt_digest=hashlib.sha256(
            _read_asset(INVESTIGATOR_ROLE_PROMPT_ASSET).encode()
        ).hexdigest(),
        skill_name=capability.skill_name,
        skill_asset=capability.skill_asset,
        skill_digest=hashlib.sha256(_read_asset(capability.skill_asset).encode()).hexdigest(),
        analyzer_profile=capability.analyzer_profile,
        tool_names=tool_names,
        requested_model=requested_model,
        observed_model=observed_model,
        diagnostics=diagnostics,
        attempts=attempts,
    )
