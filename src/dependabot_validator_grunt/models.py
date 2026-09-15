"""Frozen workflow models and canonical serialization."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_core import to_jsonable_python


class FrozenModel(BaseModel):
    """Strict immutable base model."""

    model_config = ConfigDict(frozen=True, extra="forbid")


_SAFE_IDENTIFIER_COMPONENT = re.compile(r"^[A-Za-z0-9._~!()*'-]+$")
_SAFE_IDENTIFIER_MAX_LENGTH = 512


def validate_safe_identifier(value: str) -> str:
    """Validate one bounded URL-safe npm package identifier."""
    if (
        not value
        or len(value) > _SAFE_IDENTIFIER_MAX_LENGTH
        or value != value.strip()
        or any(
            character.isspace() or unicodedata.category(character).startswith("C")
            for character in value
        )
    ):
        raise ValueError("package identifier must be a safe identifier")
    if value.startswith("@"):
        components = value[1:].split("/")
        if len(components) != 2:
            raise ValueError("package identifier must be a safe identifier")
    else:
        components = [value]
    if any(
        component in {"", ".", ".."} or _SAFE_IDENTIFIER_COMPONENT.fullmatch(component) is None
        for component in components
    ):
        raise ValueError("package identifier must be a safe identifier")
    return value


def canonical_json(value: object) -> str:
    """Return stable compact JSON."""
    data = to_jsonable_python(value)
    return json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def stable_digest(value: object) -> str:
    """Return a SHA-256 digest of canonical JSON."""
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


class RequestSnapshot(FrozenModel):
    request_id: str
    reason: str
    justification: str = ""
    status: Literal["pending", "approved", "denied", "expired"]
    expires_at: datetime | None = None
    provenance: Literal["operator_supplied", "ghec_attested"] = "operator_supplied"
    responses: tuple[str, ...] = ()
    raw_response_digest: str

    @field_validator("expires_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("expires_at must include a timezone")
        return value


class AlertSnapshot(FrozenModel):
    alert_number: int = Field(gt=0)
    state: Literal["open", "dismissed", "fixed", "auto_dismissed"] = "open"
    advisory_id: str
    summary: str
    severity: Literal["low", "medium", "high", "critical"]
    cvss: float | None = None
    epss: float | None = None
    cwes: tuple[str, ...] = ()
    package_name: str
    vulnerable_range: str
    patched_versions: str | None = None
    manifest_path: str = "package-lock.json"
    scope: Literal["runtime", "development", "unknown"] = "unknown"
    raw_response_digest: str

    @field_validator("package_name")
    @classmethod
    def validate_package_name(cls, value: str) -> str:
        return validate_safe_identifier(value)


class RepositorySnapshot(FrozenModel):
    owner: str
    name: str
    default_branch: str = "main"
    snapshot_id: str
    provenance: Literal["offline_fixture", "ghec_attested"]
    included_paths: tuple[str, ...]
    excluded_paths: tuple[str, ...] = ()


class NpmInstance(FrozenModel):
    path: str
    version: str | None
    relationship: Literal[
        "root", "workspace", "direct", "development", "optional", "transitive", "unknown"
    ]
    comparable: bool = True
    development_only: bool = False


class NpmDeclaration(FrozenModel):
    manifest_path: str
    name: str
    spec: str
    relationship: Literal["direct", "development", "optional", "peer"]
    alias_target: str | None = None
    exact_version: str | None = None


class NpmEvidence(FrozenModel):
    package_manager: Literal["npm", "yarn-classic", "pnpm"] = "npm"
    lockfile_version: str | None
    lockfile_path: str | None = None
    proof_capabilities: tuple[
        Literal[
            "resolved_instances",
            "complete_inventory",
            "dependency_consumers_complete",
            "development_scope",
        ],
        ...,
    ] = ()
    package_name: str
    instances: tuple[NpmInstance, ...]
    manifest_paths: tuple[str, ...]
    completeness: Literal["complete", "partial", "unsupported"]
    declarations: tuple[NpmDeclaration, ...] = ()
    dependency_consumers: tuple[str, ...] = ()
    issues: tuple[str, ...] = ()


class EvidenceItem(FrozenModel):
    evidence_id: str
    kind: str
    value: str
    provenance: str
    collector_version: str
    source_location: str
    completeness: Literal["complete", "partial", "unsupported"] = "complete"


class PolicyIdentity(FrozenModel):
    policy_id: str
    version: str
    digest: str


class EvidenceBundle(FrozenModel):
    evidence_format_version: Literal["1.2"] = "1.2"
    run_mode: Literal["offline_fixture", "live_ghec"]
    workflow_mode: Literal["dismissal", "triage"]
    correlation_id: str
    request: RequestSnapshot | None = None
    alert: AlertSnapshot
    repository: RepositorySnapshot
    npm: NpmEvidence
    evidence_items: tuple[EvidenceItem, ...]
    policy: PolicyIdentity
    digest: str

    @model_validator(mode="after")
    def validate_workflow_request(self) -> EvidenceBundle:
        if self.workflow_mode == "dismissal" and self.request is None:
            raise ValueError("dismissal evidence requires a request")
        if self.workflow_mode == "triage" and self.request is not None:
            raise ValueError("triage evidence cannot contain a dismissal request")
        return self


class DeterministicProof(FrozenModel):
    rule_id: str
    summary: str
    evidence_ids: tuple[str, ...]


class AgentProposalPermission(FrozenModel):
    recommendation: Literal["approve", "deny", "human_review"]
    reason_codes: tuple[str, ...]

    @model_validator(mode="after")
    def validate_reason_codes(self) -> AgentProposalPermission:
        if not self.reason_codes:
            raise ValueError("agent proposal permission requires reason codes")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("agent proposal reason codes must be unique")
        return self


RepositoryReferenceStatus = Literal[
    "reference_found",
    "sufficient_absence",
    "insufficient",
]
RepositoryReferenceInsufficiencyCode = Literal[
    "lstat_failed",
    "proof_budget_exceeded",
    "read_failed",
    "size_changed",
    "nul_containing_candidate",
    "undecodable_candidate",
    "invalid_package_json",
    "no_scanned_text",
]


class RepositoryReferenceInsufficiencyReason(FrozenModel):
    code: RepositoryReferenceInsufficiencyCode
    count: int = Field(gt=0)


class RepositoryReferenceEvidence(FrozenModel):
    target_identifier: str
    status: RepositoryReferenceStatus
    candidate_count: int = Field(ge=0)
    scanned_count: int = Field(ge=0)
    metadata_excluded_count: int = Field(ge=0)
    binary_excluded_count: int = Field(ge=0)
    scanned_bytes: int = Field(ge=0)
    max_scan_bytes: int = Field(gt=0)
    reference_count: int = Field(ge=0)
    insufficiency_reasons: tuple[RepositoryReferenceInsufficiencyReason, ...] = ()

    @field_validator("target_identifier")
    @classmethod
    def validate_target_identifier(cls, value: str) -> str:
        return validate_safe_identifier(value)

    @model_validator(mode="after")
    def validate_aggregate_consistency(self) -> RepositoryReferenceEvidence:
        if self.scanned_count > self.candidate_count:
            raise ValueError("scanned reference files cannot exceed candidates")
        reason_codes = tuple(reason.code for reason in self.insufficiency_reasons)
        if len(set(reason_codes)) != len(reason_codes):
            raise ValueError("reference insufficiency reasons must be unique")
        budget_exceeded = "proof_budget_exceeded" in reason_codes
        if budget_exceeded != (self.scanned_bytes > self.max_scan_bytes):
            raise ValueError("reference proof-budget status is inconsistent")
        if self.status == "reference_found":
            if self.reference_count == 0 or self.scanned_count == 0 or self.insufficiency_reasons:
                raise ValueError("found reference evidence is inconsistent")
        elif self.status == "sufficient_absence":
            if (
                self.reference_count != 0
                or self.scanned_count == 0
                or self.scanned_count != self.candidate_count
                or self.insufficiency_reasons
            ):
                raise ValueError("sufficient reference absence is inconsistent")
        elif self.reference_count != 0 or not self.insufficiency_reasons:
            raise ValueError("insufficient reference evidence requires structured reasons")
        return self


class AgentTask(FrozenModel):
    task_format_version: Literal["1.3"] = "1.3"
    workflow_mode: Literal["dismissal", "triage"] = "dismissal"
    correlation_id: str
    repository_id: str
    alert_number: int
    request_id: str | None = None
    snapshot_id: str
    policy_digest: str
    dismissal_reason: str | None = None
    justification: str = ""
    advisory_summary: str = ""
    package_name: str = ""
    vulnerable_range: str = ""
    manifest_path: str = ""
    dependency_scope: Literal["runtime", "development", "unknown"] = "unknown"
    installed_instances: tuple[str, ...] = ()
    installed_instance_count: int = 0
    installed_instance_details: tuple[NpmInstance, ...] = ()
    dependency_package_manager: Literal["npm", "yarn-classic", "pnpm"] = "npm"
    dependency_lockfile_version: str | None = None
    npm_completeness: Literal["complete", "partial", "unsupported"] = "unsupported"
    dependency_evidence_capabilities: tuple[
        Literal[
            "resolved_instances",
            "complete_inventory",
            "dependency_consumers_complete",
            "development_scope",
        ],
        ...,
    ] = ()
    dependency_consumers: tuple[str, ...] = ()
    manifest_declarations: tuple[NpmDeclaration, ...] = ()
    repository_file_count: int = 0
    repository_reference_evidence: RepositoryReferenceEvidence | None = None
    permitted_proposals: tuple[AgentProposalPermission, ...]

    def permits(
        self,
        recommendation: Literal["approve", "deny", "human_review"],
        reason_code: str,
    ) -> bool:
        """Return whether one recommendation/code pair is explicitly allowed."""
        return any(
            permission.recommendation == recommendation and reason_code in permission.reason_codes
            for permission in self.permitted_proposals
        )

    @model_validator(mode="after")
    def validate_mode_context(self) -> AgentTask:
        if self.workflow_mode == "dismissal":
            if self.request_id is None or self.dismissal_reason is None:
                raise ValueError("dismissal tasks require request context")
        elif self.request_id is not None or self.dismissal_reason is not None:
            raise ValueError("triage tasks cannot contain dismissal context")
        recommendations = tuple(
            permission.recommendation for permission in self.permitted_proposals
        )
        if not recommendations:
            raise ValueError("agent task requires permitted proposals")
        if len(set(recommendations)) != len(recommendations):
            raise ValueError("agent proposal recommendations must be unique")
        reason_codes = tuple(
            reason_code
            for permission in self.permitted_proposals
            for reason_code in permission.reason_codes
        )
        if len(set(reason_codes)) != len(reason_codes):
            raise ValueError("agent proposal reason codes must belong to one recommendation")
        if self.repository_reference_evidence is not None:
            if not self.permits("approve", "vulnerable_symbol_unused"):
                raise ValueError("reference evidence requires a permitted unused-symbol proposal")
            if self.repository_reference_evidence.target_identifier != self.package_name:
                raise ValueError("reference evidence target must match the assigned package")
        return self


class RepositoryFact(FrozenModel):
    path: str
    line: int = Field(gt=0)
    digest: str
    excerpt: str


class ReachabilityFinding(FrozenModel):
    kind: Literal["import", "require", "dynamic_import", "bound_call"]
    citation: RepositoryFact
    binding: str | None = None


class ReachabilityEvidence(FrozenModel):
    snapshot_id: str
    package_name: str
    engine: Literal["ast-grep"]
    engine_version: str
    status: Literal["syntax_usage_found", "no_syntax_match", "incomplete", "unavailable"]
    scanned_files: int = Field(ge=0)
    scanned_bytes: int = Field(ge=0)
    findings: tuple[ReachabilityFinding, ...] = ()
    limitations: tuple[str, ...]

    @model_validator(mode="after")
    def validate_status(self) -> ReachabilityEvidence:
        if (self.status == "syntax_usage_found") != bool(self.findings):
            raise ValueError("reachability status and findings are inconsistent")
        return self


class AgentFinding(FrozenModel):
    workflow_mode: Literal["dismissal", "triage"] = "dismissal"
    correlation_id: str
    repository_id: str
    alert_number: int
    request_id: str | None = None
    snapshot_id: str
    policy_digest: str
    claim: str
    citations: tuple[RepositoryFact, ...]
    uncertainty: str = ""
    proposed_recommendation: Literal["approve", "deny", "human_review"]
    policy_reason_code: str = "insufficient_context"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    insufficient_context: bool = True
    injection_detected: bool = False

    @model_validator(mode="after")
    def validate_mode_context(self) -> AgentFinding:
        if self.workflow_mode == "dismissal" and self.request_id is None:
            raise ValueError("dismissal findings require a request ID")
        if self.workflow_mode == "triage" and self.request_id is not None:
            raise ValueError("triage findings cannot contain a request ID")
        return self


CriticVerdict = Literal["support", "minor_concern", "material_challenge"]
CriticIssueCode = Literal[
    "unsupported_claim",
    "citation_scope",
    "evidence_scope_overreach",
    "contradiction",
    "consumer_path_ignored",
    "dynamic_usage_ignored",
    "scope_misread",
    "mitigation_overstated",
    "exploitability_overclaim",
    "no_material_issue",
]


class CriticAssessment(FrozenModel):
    lens: Literal["evidence", "applicability"]
    verdict: CriticVerdict
    issue_codes: tuple[CriticIssueCode, ...] = ()
    rationale: str = Field(max_length=600)

    @model_validator(mode="after")
    def validate_issues(self) -> CriticAssessment:
        if len(set(self.issue_codes)) != len(self.issue_codes):
            raise ValueError("critic issue codes must be unique")
        if self.verdict == "support" and self.issue_codes not in {
            (),
            ("no_material_issue",),
        }:
            raise ValueError("supporting critic cannot report challenge issue codes")
        if self.verdict != "support" and not self.issue_codes:
            raise ValueError("critic concern requires at least one issue code")
        if self.verdict != "support" and "no_material_issue" in self.issue_codes:
            raise ValueError("critic concern cannot report no material issue")
        return self


class JudgeReview(FrozenModel):
    judge_review_format_version: Literal["1.0"] = "1.0"
    workflow_mode: Literal["dismissal", "triage"]
    correlation_id: str
    repository_id: str
    alert_number: int
    request_id: str | None = None
    snapshot_id: str
    policy_digest: str
    evidence_critic: CriticAssessment
    applicability_critic: CriticAssessment
    verdict: Literal["accept", "replace"]
    rationale: str = Field(max_length=800)
    replacement_finding: AgentFinding | None = None

    @model_validator(mode="after")
    def validate_forum(self) -> JudgeReview:
        if self.evidence_critic.lens != "evidence":
            raise ValueError("judge evidence critic has the wrong lens")
        if self.applicability_critic.lens != "applicability":
            raise ValueError("judge applicability critic has the wrong lens")
        material = any(
            critic.verdict == "material_challenge"
            for critic in (self.evidence_critic, self.applicability_critic)
        )
        if self.verdict == "accept":
            if material or self.replacement_finding is not None:
                raise ValueError("judge accept verdict is inconsistent")
        elif not material or self.replacement_finding is None:
            raise ValueError("judge replacement requires a material challenge and finding")
        return self


class JudgeFailure(FrozenModel):
    judge_review_format_version: Literal["1.0"] = "1.0"
    status: Literal["unavailable"] = "unavailable"
    reason: Literal[
        "timeout",
        "missing_response",
        "malformed_output",
        "invalid_review",
        "sdk_failure",
    ]
    message: str = Field(max_length=300)


class DismissalDecision(FrozenModel):
    result_kind: Literal["dismissal_decision"] = "dismissal_decision"
    recommendation: Literal["approve", "deny", "human_review"]
    reason_code: str
    proofs: tuple[DeterministicProof, ...] = ()
    agent_findings: tuple[AgentFinding, ...] = ()
    missing_evidence: tuple[str, ...] = ()


class DismissalLifecycleResult(FrozenModel):
    result_kind: Literal["dismissal_lifecycle"] = "dismissal_lifecycle"
    lifecycle: Literal["not_pending", "expired", "stale"]
    reason_code: str
    observed_status: str
    drift_source: Literal["request", "alert"] | None = None
    changed_fields: tuple[str, ...] = ()
    superseded_result_digest: str | None = None


class TriageDecision(FrozenModel):
    result_kind: Literal["triage_decision"] = "triage_decision"
    priority: Literal["critical", "high", "medium", "low", "unknown"]
    assessment: Literal["applies", "does_not_apply", "human_review"]
    recommended_action: Literal["remediate", "investigate", "monitor", "none"]
    reason_code: str
    proofs: tuple[DeterministicProof, ...] = ()
    agent_findings: tuple[AgentFinding, ...] = ()
    missing_evidence: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_action(self) -> TriageDecision:
        allowed = {
            "applies": {"remediate", "investigate"},
            "does_not_apply": {"none"},
            "human_review": {"investigate", "monitor"},
        }
        if self.recommended_action not in allowed[self.assessment]:
            raise ValueError("triage assessment and action are inconsistent")
        return self


class Report(FrozenModel):
    report_schema_version: Literal["1.3"] = "1.3"
    run_mode: Literal["offline_fixture", "live_ghec"]
    workflow_mode: Literal["dismissal", "triage"]
    correlation_id: str
    policy: PolicyIdentity
    request: RequestSnapshot | None = None
    alert: AlertSnapshot
    repository: RepositorySnapshot
    evidence_digest: str
    collector_version: str
    model_identity: str
    result: DismissalDecision | DismissalLifecycleResult | TriageDecision = Field(
        discriminator="result_kind"
    )

    @model_validator(mode="after")
    def validate_result_mode(self) -> Report:
        if self.workflow_mode == "dismissal":
            if self.request is None or isinstance(self.result, TriageDecision):
                raise ValueError("dismissal reports require request and dismissal result")
        elif self.request is not None or not isinstance(self.result, TriageDecision):
            raise ValueError("triage reports require a triage result and no request")
        return self
