"""Pure deterministic policy reasoning and reconciliation."""

from __future__ import annotations

from typing import Literal

from dependabot_validator_grunt.models import (
    AgentFinding,
    AgentProposalPermission,
    AgentTask,
    DeterministicProof,
    DismissalDecision,
    EvidenceBundle,
    RepositoryReferenceEvidence,
    TriageDecision,
)
from dependabot_validator_grunt.npm import version_is_vulnerable
from dependabot_validator_grunt.policy import AGENT_APPROVAL_CODES_BY_REASON, Policy

DENIAL_REASON_CODES = (
    "advisory_applies",
    "decommission_not_valid",
    "reason_justification_mismatch",
)
TRIAGE_DENIAL_REASON_CODES = ("advisory_applies",)
HUMAN_REVIEW_REASON_CODES = ("insufficient_context", "injection_detected")
FIRST_PARTY_RELATIONSHIPS = {"direct", "development", "optional", "workspace"}
ANALYSIS_REASONS = {"tolerable_risk", "not_used", "inaccurate"}
PUBLIC_APPROVAL_REASON_CODES = {
    "approve_package_absent": "dependency_no_longer_present",
    "approve_unaffected_versions": "version_not_affected",
}


def _task_context(
    bundle: EvidenceBundle,
    *,
    request_id: str | None,
    dismissal_reason: str | None,
    justification: str,
    permitted_outcomes: tuple[Literal["approve", "deny", "human_review"], ...],
    approval_codes: tuple[str, ...],
    denial_codes: tuple[str, ...],
) -> AgentTask:
    installed = tuple(
        f"{instance.path}:{instance.version or 'unknown'}:{instance.relationship}"
        for instance in bundle.npm.instances[:100]
    )
    reason_codes = {
        "approve": approval_codes,
        "deny": denial_codes,
        "human_review": HUMAN_REVIEW_REASON_CODES,
    }
    permitted_proposals = tuple(
        AgentProposalPermission(
            recommendation=outcome,
            reason_codes=reason_codes[outcome],
        )
        for outcome in permitted_outcomes
        if reason_codes[outcome]
    )
    return AgentTask(
        workflow_mode=bundle.workflow_mode,
        correlation_id=bundle.correlation_id,
        repository_id=f"{bundle.repository.owner}/{bundle.repository.name}",
        alert_number=bundle.alert.alert_number,
        request_id=request_id,
        snapshot_id=bundle.repository.snapshot_id,
        policy_digest=bundle.policy.digest,
        dismissal_reason=dismissal_reason,
        justification=justification[:4000],
        advisory_summary=bundle.alert.summary[:4000],
        package_name=bundle.alert.package_name,
        vulnerable_range=bundle.alert.vulnerable_range,
        manifest_path=bundle.alert.manifest_path,
        dependency_scope=bundle.alert.scope,
        installed_instances=installed,
        installed_instance_count=len(bundle.npm.instances),
        installed_instance_details=bundle.npm.instances,
        dependency_package_manager=bundle.npm.package_manager,
        dependency_lockfile_version=bundle.npm.lockfile_version,
        npm_completeness=bundle.npm.completeness,
        dependency_evidence_capabilities=bundle.npm.proof_capabilities,
        dependency_consumers=bundle.npm.dependency_consumers,
        manifest_declarations=bundle.npm.declarations,
        repository_file_count=len(bundle.repository.included_paths),
        permitted_proposals=permitted_proposals,
    )


def _all_instances_unaffected(bundle: EvidenceBundle) -> bool:
    """Return whether complete npm evidence proves every instance unaffected."""
    if not bundle.npm.instances:
        return False
    try:
        return all(
            instance.version is not None
            and instance.comparable
            and not version_is_vulnerable(instance.version, bundle.alert.vulnerable_range)
            for instance in bundle.npm.instances
        )
    except ValueError:
        return False


def _tolerable_risk_context_proofs(
    bundle: EvidenceBundle,
    policy: Policy,
) -> tuple[DeterministicProof, ...]:
    if (
        bundle.request is None
        or bundle.request.reason != "tolerable_risk"
        or bundle.npm.completeness != "complete"
    ):
        return ()
    if not bundle.npm.instances and "approve_package_absent" in policy.enabled_rules:
        return (
            DeterministicProof(
                rule_id="approve_package_absent",
                summary="The alerted package has no installed instances.",
                evidence_ids=("npm.instances",),
            ),
        )
    if (
        bundle.npm.instances
        and _all_instances_unaffected(bundle)
        and "approve_unaffected_versions" in policy.enabled_rules
    ):
        return (
            DeterministicProof(
                rule_id="approve_unaffected_versions",
                summary="Every installed instance is outside the vulnerable range.",
                evidence_ids=("npm.instances", "alert.vulnerable_range"),
            ),
        )
    return ()


def decide(bundle: EvidenceBundle, policy: Policy) -> DismissalDecision | AgentTask:
    """Return a terminal decision or a bounded agent task."""
    if bundle.workflow_mode != "dismissal" or bundle.request is None:
        raise ValueError("dismissal decision requires dismissal evidence")
    reason = bundle.request.reason
    route = policy.routes.get(reason)
    if route is None:
        return DismissalDecision(
            recommendation="human_review",
            reason_code="unknown_dismissal_reason",
            missing_evidence=("supported dismissal reason",),
        )
    if route.mode == "human_review":
        return DismissalDecision(
            recommendation="human_review",
            reason_code="policy_requires_human_review",
            missing_evidence=("policy-configured human review",),
        )
    if reason in {"fix_started", "no_bandwidth"}:
        rule = f"deny_{reason}"
        if rule not in policy.enabled_rules:
            return DismissalDecision(
                recommendation="human_review",
                reason_code="deterministic_rule_disabled",
                missing_evidence=(rule,),
            )
        return DismissalDecision(
            recommendation="deny",
            reason_code=rule,
            proofs=(
                DeterministicProof(
                    rule_id=rule, summary="Policy requires denial.", evidence_ids=()
                ),
            ),
        )
    npm = bundle.npm
    if reason in ANALYSIS_REASONS and npm.completeness == "complete":
        if not npm.instances and "approve_package_absent" in policy.enabled_rules:
            proof = DeterministicProof(
                rule_id="approve_package_absent",
                summary="The alerted package has no installed instances.",
                evidence_ids=("npm.instances",),
            )
            if reason != "tolerable_risk" and "approve" not in route.permitted_final:
                return DismissalDecision(
                    recommendation="human_review",
                    reason_code="deterministic_approval_not_permitted",
                    proofs=(proof,),
                    missing_evidence=("policy-permitted deterministic approval",),
                )
            if reason != "tolerable_risk":
                return DismissalDecision(
                    recommendation="approve",
                    reason_code=PUBLIC_APPROVAL_REASON_CODES[proof.rule_id],
                    proofs=(proof,),
                )
        all_unaffected = _all_instances_unaffected(bundle)
        if (
            npm.instances
            and all_unaffected
            and "approve_unaffected_versions" in policy.enabled_rules
        ):
            proof = DeterministicProof(
                rule_id="approve_unaffected_versions",
                summary="Every installed instance is outside the vulnerable range.",
                evidence_ids=("npm.instances", "alert.vulnerable_range"),
            )
            if reason != "tolerable_risk" and "approve" not in route.permitted_final:
                return DismissalDecision(
                    recommendation="human_review",
                    reason_code="deterministic_approval_not_permitted",
                    proofs=(proof,),
                    missing_evidence=("policy-permitted deterministic approval",),
                )
            if reason != "tolerable_risk":
                return DismissalDecision(
                    recommendation="approve",
                    reason_code=PUBLIC_APPROVAL_REASON_CODES[proof.rule_id],
                    proofs=(proof,),
                )
    if route.mode != "deterministic_then_agentic":
        return DismissalDecision(
            recommendation="human_review",
            reason_code="deterministic_evidence_inconclusive",
            missing_evidence=("conclusive deterministic proof",),
        )
    agent_outcomes = route.agent_permitted
    if not agent_outcomes:
        return DismissalDecision(
            recommendation="human_review",
            reason_code="no_permitted_agent_outcome",
            missing_evidence=("permitted agent outcome",),
        )
    return _task_context(
        bundle,
        request_id=bundle.request.request_id,
        dismissal_reason=reason,
        justification=bundle.request.justification,
        permitted_outcomes=agent_outcomes,
        approval_codes=route.agent_approval_codes,
        denial_codes=DENIAL_REASON_CODES,
    )


def decide_triage(bundle: EvidenceBundle, policy: Policy) -> TriageDecision:
    """Return a deterministic, policy-governed alert-triage decision."""
    if bundle.workflow_mode != "triage" or bundle.request is not None:
        raise ValueError("triage decision requires triage evidence")
    priority = bundle.alert.severity
    vulnerable_paths: list[str] = []
    range_error = False
    for instance in bundle.npm.instances:
        if not instance.comparable or instance.version is None:
            continue
        try:
            if version_is_vulnerable(instance.version, bundle.alert.vulnerable_range):
                vulnerable_paths.append(instance.path)
        except ValueError:
            range_error = True
            break
    if (
        vulnerable_paths
        and not range_error
        and "resolved_instances" in bundle.npm.proof_capabilities
        and "triage_vulnerable_applies" in policy.enabled_rules
    ):
        proof = DeterministicProof(
            rule_id="triage_vulnerable_applies",
            summary="At least one installed instance is in the vulnerable range.",
            evidence_ids=("npm.instances", "alert.vulnerable_range"),
        )
        return TriageDecision(
            priority=priority,
            assessment="applies",
            recommended_action="remediate",
            reason_code=proof.rule_id,
            proofs=(proof,),
        )
    if range_error:
        return TriageDecision(
            priority=priority,
            assessment="human_review",
            recommended_action="investigate",
            reason_code="triage_unparseable_range",
            missing_evidence=("parseable vulnerable range",),
        )
    if bundle.npm.completeness != "complete":
        return TriageDecision(
            priority=priority,
            assessment="human_review",
            recommended_action="investigate",
            reason_code="triage_incomplete_evidence",
            missing_evidence=tuple(bundle.npm.issues) or ("complete npm evidence",),
        )
    if vulnerable_paths:
        return TriageDecision(
            priority=priority,
            assessment="human_review",
            recommended_action="investigate",
            reason_code="triage_rule_disabled",
            missing_evidence=("enabled triage_vulnerable_applies rule",),
        )
    if not bundle.npm.instances and "triage_absent_does_not_apply" in policy.enabled_rules:
        proof = DeterministicProof(
            rule_id="triage_absent_does_not_apply",
            summary="The alerted package has no installed instances.",
            evidence_ids=("npm.instances",),
        )
        return TriageDecision(
            priority=priority,
            assessment="does_not_apply",
            recommended_action="none",
            reason_code=proof.rule_id,
            proofs=(proof,),
        )
    if (
        bundle.npm.instances
        and _all_instances_unaffected(bundle)
        and "triage_unaffected_does_not_apply" in policy.enabled_rules
    ):
        proof = DeterministicProof(
            rule_id="triage_unaffected_does_not_apply",
            summary="Every installed instance is outside the vulnerable range.",
            evidence_ids=("npm.instances", "alert.vulnerable_range"),
        )
        return TriageDecision(
            priority=priority,
            assessment="does_not_apply",
            recommended_action="none",
            reason_code=proof.rule_id,
            proofs=(proof,),
        )
    reason_code = (
        "triage_inconclusive_human_review"
        if "triage_inconclusive_human_review" in policy.enabled_rules
        else "triage_rule_disabled"
    )
    missing_evidence = (
        ("complete npm evidence",)
        if reason_code == "triage_inconclusive_human_review"
        else ("enabled triage_inconclusive_human_review rule",)
    )
    return TriageDecision(
        priority=priority,
        assessment="human_review",
        recommended_action="investigate",
        reason_code=reason_code,
        missing_evidence=missing_evidence,
    )


def create_triage_agent_task(bundle: EvidenceBundle, policy: Policy) -> AgentTask:
    """Create a bounded alert-verification task after deterministic triage."""
    if bundle.workflow_mode != "triage" or bundle.request is not None:
        raise ValueError("triage task requires triage evidence")
    return _task_context(
        bundle,
        request_id=None,
        dismissal_reason=None,
        justification="",
        permitted_outcomes=policy.triage_agent_permitted,
        approval_codes=policy.triage_agent_approval_codes,
        denial_codes=TRIAGE_DENIAL_REASON_CODES,
    )


def _approval_is_proven(
    finding: AgentFinding,
    bundle: EvidenceBundle,
    *,
    repository_reference_evidence: RepositoryReferenceEvidence | None,
) -> bool:
    if (
        bundle.request is not None
        and finding.policy_reason_code not in AGENT_APPROVAL_CODES_BY_REASON[bundle.request.reason]
    ):
        return False
    if (
        bundle.npm.completeness != "complete"
        or finding.injection_detected
        or finding.insufficient_context
    ):
        return False
    if finding.policy_reason_code == "vulnerable_symbol_unused":
        return (
            bool(bundle.npm.instances)
            and all(
                instance.relationship in FIRST_PARTY_RELATIONSHIPS
                for instance in bundle.npm.instances
            )
            and not bundle.npm.dependency_consumers
            and repository_reference_evidence is not None
            and repository_reference_evidence.target_identifier == bundle.alert.package_name
            and repository_reference_evidence.status == "sufficient_absence"
        )
    if finding.policy_reason_code == "dev_only_scope":
        return (
            bundle.alert.scope == "development"
            and bool(bundle.npm.instances)
            and all(instance.relationship == "development" for instance in bundle.npm.instances)
            and all(instance.development_only for instance in bundle.npm.instances)
            and not bundle.npm.dependency_consumers
        )
    return False


def _finding_is_permitted(finding: AgentFinding, task: AgentTask) -> bool:
    return task.permits(
        finding.proposed_recommendation,
        finding.policy_reason_code,
    )


def _denial_is_proven(finding: AgentFinding) -> bool:
    if finding.policy_reason_code == "advisory_applies":
        return bool(finding.citations)
    return True


def reconcile(
    finding: AgentFinding,
    task: AgentTask,
    bundle: EvidenceBundle,
    policy: Policy,
    *,
    repository_reference_evidence: RepositoryReferenceEvidence | None,
) -> DismissalDecision:
    """Apply reason-specific certainty checks to a validated dismissal finding."""
    contextual_proofs = _tolerable_risk_context_proofs(bundle, policy)
    if finding.injection_detected:
        return DismissalDecision(
            recommendation="human_review",
            reason_code="injection_detected",
            proofs=contextual_proofs,
            agent_findings=(finding,),
            missing_evidence=("trusted review of untrusted input",),
        )
    if finding.insufficient_context:
        return DismissalDecision(
            recommendation="human_review",
            reason_code="insufficient_context",
            proofs=contextual_proofs,
            agent_findings=(finding,),
            missing_evidence=("complete evidence for the proposed conclusion",),
        )
    if not _finding_is_permitted(finding, task):
        return DismissalDecision(
            recommendation="human_review",
            reason_code="agent_outcome_not_permitted",
            proofs=contextual_proofs,
            agent_findings=(finding,),
            missing_evidence=("policy-permitted agent outcome",),
        )
    if finding.proposed_recommendation == "approve" and not _approval_is_proven(
        finding,
        bundle,
        repository_reference_evidence=repository_reference_evidence,
    ):
        return DismissalDecision(
            recommendation="human_review",
            reason_code="agent_approval_unproven",
            proofs=contextual_proofs,
            agent_findings=(finding,),
            missing_evidence=("complete trusted non-applicability proof",),
        )
    if finding.proposed_recommendation == "deny" and not _denial_is_proven(finding):
        return DismissalDecision(
            recommendation="human_review",
            reason_code="agent_denial_unproven",
            proofs=contextual_proofs,
            agent_findings=(finding,),
            missing_evidence=("validated repository evidence of package use",),
        )
    return DismissalDecision(
        recommendation=finding.proposed_recommendation,
        reason_code=finding.policy_reason_code,
        proofs=contextual_proofs,
        agent_findings=(finding,),
    )


def reconcile_triage(
    finding: AgentFinding,
    task: AgentTask,
    baseline: TriageDecision,
    bundle: EvidenceBundle,
    policy: Policy,
    *,
    repository_reference_evidence: RepositoryReferenceEvidence | None,
) -> TriageDecision:
    """Map a validated agent finding to the triage result vocabulary."""
    unresolved_assessment: Literal["applies", "human_review"] = (
        "applies" if baseline.assessment == "applies" else "human_review"
    )
    if finding.injection_detected:
        return TriageDecision(
            priority=baseline.priority,
            assessment=unresolved_assessment,
            recommended_action="investigate",
            reason_code="injection_detected",
            proofs=baseline.proofs,
            agent_findings=(finding,),
            missing_evidence=("trusted review of untrusted input",),
        )
    if finding.insufficient_context:
        return TriageDecision(
            priority=baseline.priority,
            assessment=unresolved_assessment,
            recommended_action="investigate",
            reason_code="insufficient_context",
            proofs=baseline.proofs,
            agent_findings=(finding,),
            missing_evidence=baseline.missing_evidence
            + ("complete evidence for the proposed conclusion",),
        )
    if not _finding_is_permitted(finding, task):
        return TriageDecision(
            priority=baseline.priority,
            assessment=unresolved_assessment,
            recommended_action="investigate",
            reason_code="agent_outcome_not_permitted",
            proofs=baseline.proofs,
            agent_findings=(finding,),
            missing_evidence=("policy-permitted agent outcome",),
        )
    if finding.proposed_recommendation == "approve" and _approval_is_proven(
        finding,
        bundle,
        repository_reference_evidence=repository_reference_evidence,
    ):
        return TriageDecision(
            priority=baseline.priority,
            assessment="does_not_apply",
            recommended_action="none",
            reason_code=finding.policy_reason_code,
            proofs=baseline.proofs,
            agent_findings=(finding,),
        )
    if finding.proposed_recommendation == "deny":
        if not _denial_is_proven(finding):
            return TriageDecision(
                priority=baseline.priority,
                assessment=unresolved_assessment,
                recommended_action="investigate",
                reason_code="agent_denial_unproven",
                proofs=baseline.proofs,
                agent_findings=(finding,),
                missing_evidence=baseline.missing_evidence
                + ("validated repository evidence of package use",),
            )
        return TriageDecision(
            priority=baseline.priority,
            assessment="applies",
            recommended_action="remediate",
            reason_code=finding.policy_reason_code,
            proofs=baseline.proofs,
            agent_findings=(finding,),
        )
    return TriageDecision(
        priority=baseline.priority,
        assessment=unresolved_assessment,
        recommended_action="investigate",
        reason_code="insufficient_context",
        proofs=baseline.proofs,
        agent_findings=(finding,),
        missing_evidence=baseline.missing_evidence + ("complete exploitability evidence",),
    )
