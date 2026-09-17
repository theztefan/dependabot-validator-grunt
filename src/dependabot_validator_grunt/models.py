"""Frozen workflow models and canonical serialization."""

from __future__ import annotations

import hashlib
import json
import keyword
import re
import unicodedata
from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal, assert_never

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_core import to_jsonable_python

Ecosystem = Literal["npm", "pip", "uv"]
PackageManager = Literal["npm", "yarn-classic", "pnpm", "pip", "poetry", "uv"]
VersionScheme = Literal["npm", "pep440"]
AnalysisFamily = Literal["javascript_typescript", "python"]
SourceKind = Literal["registry", "url", "vcs", "path", "workspace", "unknown"]


class FrozenModel(BaseModel):
    """Strict immutable base model."""

    model_config = ConfigDict(frozen=True, extra="forbid")


_SAFE_IDENTIFIER_COMPONENT = re.compile(r"^[A-Za-z0-9._~!()*'-]+$")
_SAFE_IDENTIFIER_MAX_LENGTH = 512
_DEPENDENCY_EDGE_REQUIREMENT_MAX_LENGTH = 512
_PYTHON_DISTRIBUTION_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
AGENT_TASK_INSTALLED_INSTANCE_SAMPLE_LIMIT = 20
AGENT_TASK_DEPENDENCY_CONSUMER_SAMPLE_LIMIT = 20
AGENT_TASK_DEPENDENCY_PATH_SAMPLE_LIMIT = 8
AGENT_TASK_DECLARATION_SAMPLE_LIMIT = 20
AGENT_TASK_PROVENANCE_SAMPLE_LIMIT = 20
MAX_AGENT_TASK_CHARACTERS = 24_000


class AgentTaskSizeError(RuntimeError):
    """A trusted model-facing task exceeds its aggregate serialized limit."""


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


def normalize_package_identifier(ecosystem: Ecosystem, value: str) -> str:
    """Validate one package name and return its ecosystem identity."""
    match ecosystem:
        case "npm":
            return validate_safe_identifier(value)
        case "pip" | "uv":
            if (
                not value
                or len(value) > _SAFE_IDENTIFIER_MAX_LENGTH
                or value != value.strip()
                or _PYTHON_DISTRIBUTION_NAME.fullmatch(value) is None
            ):
                raise ValueError("package identifier must be a safe identifier")
            return re.sub(r"[-_.]+", "-", value).lower()
        case _ as unreachable:
            assert_never(unreachable)


def analysis_family(ecosystem: Ecosystem) -> AnalysisFamily:
    """Return the explicit source-language analysis family."""
    match ecosystem:
        case "npm":
            return "javascript_typescript"
        case "pip" | "uv":
            return "python"
        case _ as unreachable:
            assert_never(unreachable)


def version_scheme_for_ecosystem(ecosystem: Ecosystem) -> VersionScheme:
    """Return the explicit version-comparison scheme."""
    match ecosystem:
        case "npm":
            return "npm"
        case "pip" | "uv":
            return "pep440"
        case _ as unreachable:
            assert_never(unreachable)


def canonical_json(value: object) -> str:
    """Return stable compact JSON."""
    data = to_jsonable_python(value)
    return json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def stable_digest(value: object) -> str:
    """Return a SHA-256 digest of canonical JSON."""
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def validate_dependency_edge_requirement(value: str) -> str:
    """Validate one bounded dependency-edge requirement."""
    if (
        not value
        or len(value) > _DEPENDENCY_EDGE_REQUIREMENT_MAX_LENGTH
        or any(unicodedata.category(character).startswith("C") for character in value)
    ):
        raise ValueError("dependency path edge requirements must be bounded text")
    return value


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
    ecosystem: Ecosystem = "npm"
    package_name: str
    package_identity: str = ""
    vulnerable_range: str
    patched_versions: str | None = None
    manifest_path: str = "package-lock.json"
    scope: Literal["runtime", "development", "unknown"] = "unknown"
    dependency_relationship: Literal["direct", "transitive", "inconclusive", "unknown"] = "unknown"
    raw_response_digest: str

    @model_validator(mode="after")
    def validate_package_identity(self) -> AlertSnapshot:
        identity = normalize_package_identifier(self.ecosystem, self.package_name)
        if self.package_identity and self.package_identity != identity:
            raise ValueError("package identity does not match the package name")
        object.__setattr__(self, "package_identity", identity)
        return self


class RepositorySnapshot(FrozenModel):
    owner: str
    name: str
    default_branch: str = "main"
    snapshot_id: str
    provenance: Literal["offline_fixture", "ghec_attested"]
    included_paths: tuple[str, ...]
    excluded_paths: tuple[str, ...] = ()
    coverage_excluded_paths: tuple[str, ...] = ()


class DependencyInstance(FrozenModel):
    path: str
    version: str | None
    relationship: Literal["workspace", "direct", "development", "optional", "transitive", "unknown"]
    comparable: bool = True
    development_only: bool = False
    source_kind: SourceKind
    source_locator: str | None = None


class DependencyDeclaration(FrozenModel):
    manifest_path: str
    name: str
    spec: str
    relationship: Literal["direct", "development", "optional", "peer"]
    alias_target: str | None = None
    exact_version: str | None = None
    marker: str | None = None
    source_kind: SourceKind = "registry"
    source_locator: str | None = None


class DependencyPathNode(FrozenModel):
    instance_id: str
    package_name: str
    version: str | None = None


class DependencyPath(FrozenModel):
    nodes: tuple[DependencyPathNode, ...]
    edge_kinds: tuple[Literal["runtime", "development", "optional", "peer", "transitive"], ...]
    edge_requirements: tuple[str | None, ...]
    conditions: tuple[str | None, ...]
    conditional: bool = False
    development_only: bool = False
    cycle_detected: bool = False

    @model_validator(mode="after")
    def validate_shape(self) -> DependencyPath:
        edge_count = max(len(self.nodes) - 1, 0)
        if (
            len(self.edge_kinds) != edge_count
            or len(self.edge_requirements) != edge_count
            or len(self.conditions) != edge_count
        ):
            raise ValueError("dependency path edges must connect every adjacent node")
        if not self.nodes:
            raise ValueError("dependency path requires at least one node")
        for requirement in self.edge_requirements:
            if requirement is not None:
                validate_dependency_edge_requirement(requirement)
        if self.conditional != any(condition is not None for condition in self.conditions):
            raise ValueError("dependency path conditional state is inconsistent")
        return self


class DependencyProvenance(FrozenModel):
    kind: Literal["requirement_include", "constraint_include", "pip_compile_via"]
    source_path: str
    line: int = Field(gt=0)
    target: str
    authoritative: Literal[False] = False


class DependencyEvidence(FrozenModel):
    ecosystem: Ecosystem = "npm"
    package_manager: PackageManager = "npm"
    version_scheme: VersionScheme = "npm"
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
    package_identity: str = ""
    instances: tuple[DependencyInstance, ...]
    manifest_paths: tuple[str, ...]
    completeness: Literal["complete", "partial", "unsupported"]
    declarations: tuple[DependencyDeclaration, ...] = ()
    dependency_consumers: tuple[str, ...] = ()
    dependency_paths: tuple[DependencyPath, ...] = ()
    dependency_provenance: tuple[DependencyProvenance, ...] = ()
    dependency_paths_truncated: bool = False
    issues: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_package_identity(self) -> DependencyEvidence:
        identity = normalize_package_identifier(self.ecosystem, self.package_name)
        if self.package_identity and self.package_identity != identity:
            raise ValueError("dependency evidence identity does not match the package name")
        object.__setattr__(self, "package_identity", identity)
        return self


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
    evidence_format_version: Literal["3.0"] = "3.0"
    run_mode: Literal["offline_fixture", "live_ghec"]
    workflow_mode: Literal["dismissal", "triage"]
    correlation_id: str
    request: RequestSnapshot | None = None
    alert: AlertSnapshot
    repository: RepositorySnapshot
    dependency: DependencyEvidence
    evidence_items: tuple[EvidenceItem, ...]
    policy: PolicyIdentity
    digest: str

    @model_validator(mode="after")
    def validate_workflow_request(self) -> EvidenceBundle:
        if self.workflow_mode == "dismissal" and self.request is None:
            raise ValueError("dismissal evidence requires a request")
        if self.workflow_mode == "triage" and self.request is not None:
            raise ValueError("triage evidence cannot contain a dismissal request")
        if self.alert.ecosystem != self.dependency.ecosystem:
            raise ValueError("alert and dependency ecosystems must match")
        if self.alert.package_identity != self.dependency.package_identity:
            raise ValueError("alert and dependency package identities must match")
        expected_scheme = version_scheme_for_ecosystem(self.alert.ecosystem)
        if self.dependency.version_scheme != expected_scheme:
            raise ValueError("dependency version scheme does not match the ecosystem")
        allowed_managers: dict[Ecosystem, set[PackageManager]] = {
            "npm": {"npm", "yarn-classic", "pnpm"},
            "pip": {"pip", "poetry", "uv"},
            "uv": {"uv"},
        }
        if self.dependency.package_manager not in allowed_managers[self.alert.ecosystem]:
            raise ValueError("dependency package manager does not match the ecosystem")
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
    "snapshot_excluded_path",
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


class ImportTarget(FrozenModel):
    value: str
    provenance: Literal["canonical_distribution", "curated_mapping"]
    authoritative: bool = False

    @field_validator("value")
    @classmethod
    def validate_import_target(cls, value: str) -> str:
        validate_safe_identifier(value)
        if not value.isidentifier() or keyword.iskeyword(value):
            raise ValueError("import target must be one top-level Python identifier")
        return value

    @model_validator(mode="after")
    def validate_authority(self) -> ImportTarget:
        if self.authoritative and self.provenance not in {
            "canonical_distribution",
            "curated_mapping",
        }:
            raise ValueError("authoritative import target provenance is unsupported")
        return self


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
    task_format_version: Literal["3.0"] = "3.0"
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
    ecosystem: Ecosystem = "npm"
    package_name: str = ""
    package_identity: str = ""
    vulnerable_range: str = ""
    manifest_path: str = ""
    analysis_root: str = ""
    dependency_scope: Literal["runtime", "development", "unknown"] = "unknown"
    dependency_relationship: Literal["direct", "transitive", "inconclusive", "unknown"] = "unknown"
    installed_instance_count: int = Field(default=0, ge=0)
    installed_instance_details: tuple[DependencyInstance, ...] = Field(
        default=(),
        max_length=AGENT_TASK_INSTALLED_INSTANCE_SAMPLE_LIMIT,
    )
    installed_instance_details_truncated: bool = False
    dependency_package_manager: PackageManager = "npm"
    dependency_version_scheme: VersionScheme = "npm"
    dependency_lockfile_version: str | None = None
    dependency_completeness: Literal["complete", "partial", "unsupported"] = "unsupported"
    dependency_evidence_capabilities: tuple[
        Literal[
            "resolved_instances",
            "complete_inventory",
            "dependency_consumers_complete",
            "development_scope",
        ],
        ...,
    ] = ()
    dependency_consumer_count: int = Field(default=0, ge=0)
    dependency_consumers: tuple[str, ...] = Field(
        default=(),
        max_length=AGENT_TASK_DEPENDENCY_CONSUMER_SAMPLE_LIMIT,
    )
    dependency_consumers_truncated: bool = False
    dependency_path_count: int = Field(default=0, ge=0)
    dependency_paths: tuple[DependencyPath, ...] = Field(
        default=(),
        max_length=AGENT_TASK_DEPENDENCY_PATH_SAMPLE_LIMIT,
    )
    dependency_paths_truncated: bool = False
    import_targets: tuple[ImportTarget, ...] = ()
    manifest_declaration_count: int = Field(default=0, ge=0)
    manifest_declarations: tuple[DependencyDeclaration, ...] = Field(
        default=(),
        max_length=AGENT_TASK_DECLARATION_SAMPLE_LIMIT,
    )
    manifest_declarations_truncated: bool = False
    dependency_provenance_count: int = Field(default=0, ge=0)
    dependency_provenance: tuple[DependencyProvenance, ...] = Field(
        default=(),
        max_length=AGENT_TASK_PROVENANCE_SAMPLE_LIMIT,
    )
    dependency_provenance_truncated: bool = False
    repository_file_count: int = Field(default=0, ge=0)
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
        if self.package_name or self.package_identity:
            identity = normalize_package_identifier(self.ecosystem, self.package_name)
            if self.package_identity and self.package_identity != identity:
                raise ValueError("agent task package identity does not match the package name")
            object.__setattr__(self, "package_identity", identity)
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
        family = analysis_family(self.ecosystem)
        if family == "python" and "approve" in recommendations:
            raise ValueError("Python agent tasks cannot permit approval")
        reason_codes = tuple(
            reason_code
            for permission in self.permitted_proposals
            for reason_code in permission.reason_codes
        )
        if len(set(reason_codes)) != len(reason_codes):
            raise ValueError("agent proposal reason codes must belong to one recommendation")
        target_values = tuple(target.value for target in self.import_targets)
        if len(set(target_values)) != len(target_values):
            raise ValueError("agent task import targets must be unique")
        if family == "javascript_typescript" and any(
            target.authoritative for target in self.import_targets
        ):
            raise ValueError("JavaScript tasks cannot declare authoritative Python targets")
        if any(
            target.authoritative
            and target.provenance == "canonical_distribution"
            and target.value != self.package_identity
            for target in self.import_targets
        ):
            raise ValueError("canonical import target must match the Python package identity")
        manifest = PurePosixPath(self.manifest_path)
        expected_analysis_root = (
            "" if manifest.parent == PurePosixPath(".") else manifest.parent.as_posix()
        )
        if self.analysis_root != expected_analysis_root:
            raise ValueError("agent task analysis root must match the manifest directory")
        samples = (
            (
                "installed instance",
                self.installed_instance_count,
                len(self.installed_instance_details),
                self.installed_instance_details_truncated,
                False,
            ),
            (
                "dependency consumer",
                self.dependency_consumer_count,
                len(self.dependency_consumers),
                self.dependency_consumers_truncated,
                False,
            ),
            (
                "dependency path",
                self.dependency_path_count,
                len(self.dependency_paths),
                self.dependency_paths_truncated,
                True,
            ),
            (
                "manifest declaration",
                self.manifest_declaration_count,
                len(self.manifest_declarations),
                self.manifest_declarations_truncated,
                False,
            ),
            (
                "dependency provenance",
                self.dependency_provenance_count,
                len(self.dependency_provenance),
                self.dependency_provenance_truncated,
                False,
            ),
        )
        for name, total_count, sample_count, truncated, allows_upstream_truncation in samples:
            if sample_count > total_count:
                raise ValueError(f"{name} sample cannot exceed its total count")
            if total_count > sample_count and not truncated:
                raise ValueError(f"{name} sample truncation must be explicit")
            if not allows_upstream_truncation and truncated and total_count == sample_count:
                raise ValueError(f"{name} truncation is inconsistent with its total count")
        if self.repository_reference_evidence is not None:
            if not self.permits("approve", "vulnerable_symbol_unused"):
                raise ValueError("reference evidence requires a permitted unused-symbol proposal")
            if self.repository_reference_evidence.target_identifier != self.package_name:
                raise ValueError("reference evidence target must match the assigned package")
        serialized_characters = len(canonical_json(self))
        if serialized_characters > MAX_AGENT_TASK_CHARACTERS:
            raise AgentTaskSizeError(
                f"serialized agent task exceeds {MAX_AGENT_TASK_CHARACTERS} characters"
            )
        return self


class RepositoryFact(FrozenModel):
    path: str
    line: int = Field(gt=0)
    digest: str
    excerpt: str


ReachabilityOperation = Literal[
    "import_statement",
    "import_from_statement",
    "call_expression",
    "call",
]
ReachabilityProfile = Literal["npm", "python"]
NPM_REACHABILITY_OPERATIONS: tuple[ReachabilityOperation, ...] = (
    "import_statement",
    "call_expression",
)
PYTHON_REACHABILITY_OPERATIONS: tuple[ReachabilityOperation, ...] = (
    "import_statement",
    "import_from_statement",
    "call",
)


class ReachabilityFinding(FrozenModel):
    kind: Literal["static_import", "dynamic_import", "runtime_require", "bound_call"]
    language: str = Field(min_length=1)
    matched_target: str = Field(min_length=1)
    citation: RepositoryFact
    binding: str | None = None


class ReachabilityEvidence(FrozenModel):
    snapshot_id: str
    package_name: str
    target_identifiers: tuple[str, ...]
    analysis_root: str = ""
    profile: ReachabilityProfile
    engine: Literal["ast-grep"]
    engine_version: str
    status: Literal["syntax_usage_found", "no_syntax_match", "incomplete", "unavailable"]
    candidate_files: int = Field(ge=0)
    staged_files: int = Field(ge=0)
    skipped_files: int = Field(ge=0)
    staged_bytes: int = Field(ge=0)
    operations: tuple[ReachabilityOperation, ...]
    completed_operations: tuple[ReachabilityOperation, ...]
    findings: tuple[ReachabilityFinding, ...] = ()
    limitations: tuple[str, ...]

    @model_validator(mode="after")
    def validate_status(self) -> ReachabilityEvidence:
        if (self.status == "syntax_usage_found") != bool(self.findings):
            raise ValueError("reachability status and findings are inconsistent")
        if not self.target_identifiers or len(set(self.target_identifiers)) != len(
            self.target_identifiers
        ):
            raise ValueError("reachability targets must be non-empty and unique")
        for target in self.target_identifiers:
            validate_safe_identifier(target)
        analysis_root = PurePosixPath(self.analysis_root)
        if analysis_root.is_absolute() or ".." in analysis_root.parts or self.analysis_root == ".":
            raise ValueError("reachability analysis root is unsafe")
        if self.candidate_files != self.staged_files + self.skipped_files:
            raise ValueError("reachability file coverage is inconsistent")
        expected_operations = (
            NPM_REACHABILITY_OPERATIONS if self.profile == "npm" else PYTHON_REACHABILITY_OPERATIONS
        )
        if self.operations != expected_operations:
            raise ValueError("reachability operations do not match the application profile")
        expected_completed = tuple(
            operation for operation in self.operations if operation in self.completed_operations
        )
        if expected_completed != self.completed_operations:
            raise ValueError("completed reachability operations are inconsistent")
        if self.status == "no_syntax_match" and (
            self.skipped_files or self.completed_operations != self.operations
        ):
            raise ValueError("no-match reachability evidence requires complete bounded coverage")
        if any(finding.matched_target not in self.target_identifiers for finding in self.findings):
            raise ValueError("reachability finding target is not bound to the evidence")
        if any(
            (
                self.profile == "npm"
                and finding.language.casefold() not in {"javascript", "jsx", "typescript", "tsx"}
            )
            or (
                self.profile == "python"
                and (finding.language.casefold() != "python" or finding.kind == "runtime_require")
            )
            for finding in self.findings
        ):
            raise ValueError("reachability finding does not match the application profile")
        return self


class AgentFinding(FrozenModel):
    workflow_mode: Literal["dismissal", "triage"]
    correlation_id: str
    repository_id: str
    alert_number: int = Field(strict=True)
    request_id: str | None
    snapshot_id: str
    policy_digest: str
    claim: str
    citations: tuple[RepositoryFact, ...]
    uncertainty: str
    proposed_recommendation: Literal["approve", "deny", "human_review"]
    policy_reason_code: str
    confidence: float = Field(ge=0.0, le=1.0)
    insufficient_context: bool = Field(strict=True)
    injection_detected: bool = Field(strict=True)

    @field_validator("confidence", mode="before")
    @classmethod
    def require_numeric_confidence(cls, value: object) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("confidence must be a JSON number")
        return float(value)

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
    report_schema_version: Literal["3.0"] = "3.0"
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
