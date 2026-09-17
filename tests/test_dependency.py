"""Ecosystem-neutral dependency identity and version tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dependabot_validator_grunt.dependency import version_is_vulnerable
from dependabot_validator_grunt.models import (
    AlertSnapshot,
    DependencyEvidence,
    DependencyInstance,
    EvidenceBundle,
    PolicyIdentity,
    RepositorySnapshot,
)


def test_python_alert_uses_canonical_distribution_identity() -> None:
    alert = AlertSnapshot(
        alert_number=1,
        advisory_id="GHSA-test",
        summary="Test advisory",
        severity="high",
        ecosystem="pip",
        package_name="Zope_Interface",
        vulnerable_range="< 6",
        raw_response_digest="digest",
    )

    assert alert.package_name == "Zope_Interface"
    assert alert.package_identity == "zope-interface"


def test_dependency_evidence_rejects_mismatched_identity() -> None:
    with pytest.raises(ValidationError, match="identity"):
        DependencyEvidence(
            ecosystem="pip",
            package_manager="pip",
            version_scheme="pep440",
            lockfile_version=None,
            package_name="Zope.Interface",
            package_identity="different",
            instances=(),
            manifest_paths=("requirements.txt",),
            completeness="partial",
        )


@pytest.mark.parametrize(
    ("version", "vulnerable_range", "expected"),
    (
        ("1.2.3", ">=1,<2", True),
        ("2.0.0", ">=1,<2", False),
        ("1!1.0", ">=1!0.5,<1!2", True),
        ("1.0rc1", "<1.0", False),
    ),
)
def test_python_vulnerability_ranges_use_pep_440(
    version: str,
    vulnerable_range: str,
    expected: bool,
) -> None:
    assert version_is_vulnerable("pip", version, vulnerable_range) is expected


def test_npm_version_dispatch_preserves_semver_behavior() -> None:
    assert version_is_vulnerable("npm", "1.2.3", ">= 1.0.0, < 2.0.0")


def test_dependency_instance_requires_explicit_source_and_rejects_removed_fields() -> None:
    with pytest.raises(ValidationError):
        DependencyInstance.model_validate(
            {
                "path": "node_modules/target",
                "version": "1.0.0",
                "relationship": "direct",
            }
        )
    with pytest.raises(ValidationError):
        DependencyInstance.model_validate(
            {
                "path": "node_modules/target",
                "version": "1.0.0",
                "relationship": "direct",
                "version_scheme": "npm",
                "source_kind": "registry",
            }
        )
    with pytest.raises(ValidationError):
        DependencyInstance.model_validate(
            {
                "path": ".",
                "version": "1.0.0",
                "relationship": "root",
                "source_kind": "workspace",
            }
        )


def test_evidence_bundle_rejects_mismatched_alert_and_dependency_identity() -> None:
    alert = AlertSnapshot(
        alert_number=1,
        advisory_id="GHSA-test",
        summary="Test advisory",
        severity="high",
        ecosystem="pip",
        package_name="target",
        vulnerable_range="<2",
        raw_response_digest="alert",
    )
    dependency = DependencyEvidence(
        ecosystem="pip",
        package_manager="pip",
        version_scheme="pep440",
        lockfile_version=None,
        package_name="other",
        instances=(),
        manifest_paths=("requirements.txt",),
        completeness="partial",
    )

    with pytest.raises(ValidationError, match="identities"):
        EvidenceBundle(
            run_mode="offline_fixture",
            workflow_mode="triage",
            correlation_id="correlation",
            alert=alert,
            repository=RepositorySnapshot(
                owner="owner",
                name="repo",
                snapshot_id="snapshot",
                provenance="offline_fixture",
                included_paths=("requirements.txt",),
            ),
            dependency=dependency,
            evidence_items=(),
            policy=PolicyIdentity(policy_id="policy", version="1", digest="digest"),
            digest="bundle",
        )
