"""Versioned policy loading and validation."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dependabot_validator_grunt.models import PolicyIdentity, stable_digest

KNOWN_RULES = {
    "deny_fix_started",
    "deny_no_bandwidth",
    "approve_package_absent",
    "approve_unaffected_versions",
    "triage_absent_does_not_apply",
    "triage_unaffected_does_not_apply",
    "triage_vulnerable_applies",
    "triage_inconclusive_human_review",
}
KNOWN_DISMISSAL_REASONS = {
    "fix_started",
    "no_bandwidth",
    "tolerable_risk",
    "not_used",
    "inaccurate",
}
AGENT_APPROVAL_CODES_BY_REASON: dict[str, frozenset[str]] = {
    "fix_started": frozenset(),
    "no_bandwidth": frozenset(),
    "tolerable_risk": frozenset(),
    "not_used": frozenset({"vulnerable_symbol_unused"}),
    "inaccurate": frozenset(),
}
TRIAGE_AGENT_APPROVAL_CODES = frozenset({"vulnerable_symbol_unused", "dev_only_scope"})


def _require_unique_entries(values: tuple[str, ...], field_name: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} entries must be unique")


class Route(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    mode: Literal["deterministic", "deterministic_then_agentic", "human_review"]
    permitted_final: tuple[Literal["approve", "deny", "human_review"], ...]
    agent_permitted: tuple[Literal["approve", "deny", "human_review"], ...] = ()
    agent_approval_codes: tuple[str, ...] = ()


class Limits(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    max_attempts: int = Field(ge=1, le=10)
    wall_clock_seconds: int = Field(ge=1, le=3600)
    archive_bytes: int = Field(default=100 * 1024 * 1024, ge=1)
    expanded_bytes: int = Field(default=512 * 1024 * 1024, ge=1)
    max_archive_members: int = Field(default=50_000, ge=1)
    max_archive_file_bytes: int = Field(default=10 * 1024 * 1024, ge=1)
    max_dependency_file_bytes: int = Field(default=32 * 1024 * 1024, ge=1)
    max_read_bytes: int = Field(default=2 * 1024 * 1024, ge=1)
    max_results: int = Field(default=200, ge=1)
    max_session_bytes: int = Field(default=32 * 1024 * 1024, ge=1)
    max_proof_scan_bytes: int = Field(default=64 * 1024 * 1024, ge=1)
    analyzer_wall_seconds: int = Field(default=60, ge=1, le=600)
    max_analyzer_files: int = Field(default=10_000, ge=1)
    max_analyzer_input_bytes: int = Field(default=64 * 1024 * 1024, ge=1)
    max_analyzer_output_bytes: int = Field(default=4 * 1024 * 1024, ge=1)
    max_analyzer_stderr_bytes: int = Field(default=256 * 1024, ge=1)
    max_analyzer_findings: int = Field(default=500, ge=1)

    @model_validator(mode="after")
    def validate_snapshot_limits(self) -> Limits:
        if self.max_archive_file_bytes > self.expanded_bytes:
            raise ValueError("single-file archive limit cannot exceed expanded archive limit")
        if self.max_dependency_file_bytes > self.expanded_bytes:
            raise ValueError("dependency-file limit cannot exceed expanded archive limit")
        if self.max_read_bytes > self.max_session_bytes:
            raise ValueError("single agent read cannot exceed the session byte limit")
        return self


class Policy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    policy_id: str
    version: str
    routes: dict[str, Route]
    enabled_rules: tuple[str, ...]
    triage_agent_permitted: tuple[Literal["approve", "deny", "human_review"], ...]
    triage_agent_approval_codes: tuple[str, ...]
    minimum_agent_approval_confidence: float = Field(ge=0.0, le=1.0)
    limits: Limits

    @model_validator(mode="after")
    def validate_policy(self) -> Policy:
        _require_unique_entries(self.enabled_rules, "enabled_rules")
        unknown = set(self.enabled_rules) - KNOWN_RULES
        if unknown:
            raise ValueError(f"unknown rule IDs: {sorted(unknown)}")
        unknown_reasons = set(self.routes) - KNOWN_DISMISSAL_REASONS
        if unknown_reasons:
            raise ValueError(f"unknown dismissal reasons: {sorted(unknown_reasons)}")
        for reason, route in self.routes.items():
            _require_unique_entries(
                route.permitted_final,
                f"route {reason!r} permitted_final",
            )
            _require_unique_entries(
                route.agent_permitted,
                f"route {reason!r} agent_permitted",
            )
            _require_unique_entries(
                route.agent_approval_codes,
                f"route {reason!r} agent_approval_codes",
            )
            if "human_review" not in route.permitted_final:
                raise ValueError(f"route {reason!r} must permit fail-closed human review")
            if reason == "tolerable_risk" and "approve" in route.permitted_final:
                raise ValueError("tolerable_risk cannot permit approval without structured proof")
            if not set(route.agent_permitted) <= set(route.permitted_final):
                raise ValueError(
                    f"agentic route {reason!r} permits outcomes forbidden as final results"
                )
            if route.agent_approval_codes and "approve" not in route.agent_permitted:
                raise ValueError(
                    f"agentic route {reason!r} has approval codes but forbids approval"
                )
            if "approve" in route.agent_permitted and not route.agent_approval_codes:
                raise ValueError(
                    f"agentic route {reason!r} permits approval without approval codes"
                )
            unsupported_codes = (
                set(route.agent_approval_codes) - AGENT_APPROVAL_CODES_BY_REASON[reason]
            )
            if unsupported_codes:
                raise ValueError(
                    f"agentic route {reason!r} has unsupported approval codes: "
                    f"{sorted(unsupported_codes)}"
                )
        for reason, rule in (
            ("fix_started", "deny_fix_started"),
            ("no_bandwidth", "deny_no_bandwidth"),
        ):
            route = self.routes.get(reason)
            if (
                rule in self.enabled_rules
                and route is not None
                and "deny" not in route.permitted_final
            ):
                raise ValueError(f"route {reason!r} must permit its deterministic denial")
        _require_unique_entries(
            self.triage_agent_permitted,
            "triage_agent_permitted",
        )
        _require_unique_entries(
            self.triage_agent_approval_codes,
            "triage_agent_approval_codes",
        )
        if self.triage_agent_approval_codes and "approve" not in self.triage_agent_permitted:
            raise ValueError("triage has approval codes but forbids approval")
        if "approve" in self.triage_agent_permitted and not self.triage_agent_approval_codes:
            raise ValueError("triage permits approval without approval codes")
        if "human_review" not in self.triage_agent_permitted:
            raise ValueError("triage must permit fail-closed human review")
        unsupported_triage_codes = (
            set(self.triage_agent_approval_codes) - TRIAGE_AGENT_APPROVAL_CODES
        )
        if unsupported_triage_codes:
            raise ValueError(
                f"triage has unsupported approval codes: {sorted(unsupported_triage_codes)}"
            )
        return self

    def identity(self) -> PolicyIdentity:
        return PolicyIdentity(
            policy_id=self.policy_id,
            version=self.version,
            digest=stable_digest(self),
        )


def default_policy_path() -> Path:
    """Return the packaged default policy path."""
    return Path(str(files("dependabot_validator_grunt").joinpath("policies/default.json")))


def load_policy(path: Path | None = None) -> Policy:
    """Load and strictly validate policy JSON."""
    selected = path or default_policy_path()
    return Policy.model_validate(json.loads(selected.read_text(encoding="utf-8")))
