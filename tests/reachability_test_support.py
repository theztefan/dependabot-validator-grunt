"""Shared setup for structural reachability tests."""

from collections.abc import Sequence
from pathlib import Path

from dependabot_validator_grunt.models import ReachabilityEvidence, ReachabilityProfile
from dependabot_validator_grunt.reachability import AstGrepRunner


def analyze(
    root: Path,
    *,
    package_name: str = "lodash",
    profile: ReachabilityProfile = "npm",
    analysis_root: str = "",
    target_identifiers: Sequence[str] | None = None,
    **overrides: int,
) -> ReachabilityEvidence:
    """Run the real bounded analyzer with small test limits."""

    limits = {
        "wall_seconds": 30,
        "max_files": 100,
        "max_input_bytes": 1024 * 1024,
        "max_batch_files": 100,
        "max_batch_bytes": 1024 * 1024,
        "max_output_bytes": 1024 * 1024,
        "max_stderr_bytes": 64 * 1024,
        "max_findings": 100,
    }
    limits.update(overrides)
    return AstGrepRunner().analyze(
        root,
        snapshot_id="snapshot",
        package_name=package_name,
        profile=profile,
        analysis_root=analysis_root,
        target_identifiers=target_identifiers,
        **limits,
    )
