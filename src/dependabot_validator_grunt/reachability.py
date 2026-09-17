"""Public structural reachability runner and explicit profile coordination."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from dependabot_validator_grunt.models import (
    ReachabilityEvidence,
    ReachabilityProfile,
)
from dependabot_validator_grunt.reachability_ast_grep import (
    AST_GREP_VERSION,
    OperationCollection,
    StagedInput,
    check_availability,
    collect_operations,
    default_executable,
    operations_for_profile,
    temporary_workspace,
    validate_targets,
    verify_sources,
)
from dependabot_validator_grunt.reachability_npm import interpret_npm
from dependabot_validator_grunt.reachability_python import interpret_python


class ReachabilityRunner(Protocol):
    """External analyzer seam used by offline fakes and the real subprocess."""

    def analyze(
        self,
        root: Path,
        *,
        snapshot_id: str,
        package_name: str,
        profile: ReachabilityProfile,
        analysis_root: str = "",
        target_identifiers: Sequence[str] | None = None,
        wall_seconds: int,
        max_files: int,
        max_input_bytes: int,
        max_batch_files: int,
        max_batch_bytes: int,
        max_output_bytes: int,
        max_stderr_bytes: int,
        max_findings: int,
    ) -> ReachabilityEvidence: ...


class AstGrepRunner:
    """Coordinate the pinned ast-grep boundary and explicit profile interpreter."""

    def __init__(self, executable: Path | None = None) -> None:
        self.executable = (executable or default_executable()).resolve()

    def analyze(
        self,
        root: Path,
        *,
        snapshot_id: str,
        package_name: str,
        profile: ReachabilityProfile,
        analysis_root: str = "",
        target_identifiers: Sequence[str] | None = None,
        wall_seconds: int,
        max_files: int,
        max_input_bytes: int,
        max_batch_files: int,
        max_batch_bytes: int,
        max_output_bytes: int,
        max_stderr_bytes: int,
        max_findings: int,
    ) -> ReachabilityEvidence:
        targets = validate_targets(package_name, target_identifiers)
        profile_operations = operations_for_profile(profile)
        deadline = time.monotonic() + wall_seconds
        try:
            availability = check_availability(self.executable, deadline)
        except (OSError, subprocess.SubprocessError, TimeoutError):
            return _unavailable(
                snapshot_id,
                package_name,
                targets,
                profile,
                analysis_root,
                "unavailable",
                "The pinned ast-grep runtime could not be verified within trusted limits.",
            )
        if not availability.available:
            if availability.limitation is None:
                raise ValueError("unavailable analyzer result requires a limitation")
            return _unavailable(
                snapshot_id,
                package_name,
                targets,
                profile,
                analysis_root,
                availability.engine_version,
                availability.limitation,
            )

        staged = StagedInput((), {}, 0, 0, 0, 0)
        operations = OperationCollection({}, ())
        try:
            with temporary_workspace(
                root,
                analysis_root=analysis_root,
                profile=profile,
                deadline=deadline,
                max_files=max_files,
                max_input_bytes=max_input_bytes,
                max_batch_bytes=max_batch_bytes,
            ) as workspace:
                staged = workspace.staged
                operations = collect_operations(
                    self.executable,
                    workspace,
                    profile=profile,
                    target_identifiers=targets,
                    deadline=deadline,
                    max_batch_files=max_batch_files,
                    max_batch_bytes=max_batch_bytes,
                    max_output_bytes=max_output_bytes,
                    max_stderr_bytes=max_stderr_bytes,
                )
                if profile == "npm":
                    findings, findings_complete = interpret_npm(
                        operations.matches,
                        staged.sources,
                        target_identifiers=targets,
                        max_findings=max_findings,
                    )
                elif profile == "python":
                    findings, findings_complete = interpret_python(
                        operations.matches,
                        staged.sources,
                        target_identifiers=targets,
                        max_findings=max_findings,
                    )
                else:
                    raise ValueError("unsupported reachability profile")
                verify_sources(root, staged.sources, deadline)
        except (
            OSError,
            TimeoutError,
            ValueError,
            subprocess.SubprocessError,
            ValidationError,
        ):
            return ReachabilityEvidence(
                snapshot_id=snapshot_id,
                package_name=package_name,
                target_identifiers=targets,
                analysis_root=analysis_root,
                profile=profile,
                engine="ast-grep",
                engine_version=AST_GREP_VERSION,
                status="incomplete",
                candidate_files=staged.candidate_files,
                staged_files=staged.staged_files,
                skipped_files=staged.skipped_files,
                staged_bytes=staged.staged_bytes,
                operations=profile_operations,
                completed_operations=operations.completed_operations,
                limitations=(
                    "Structural analysis did not complete within trusted limits.",
                    "No result is not evidence of non-reachability.",
                    "ast-grep may not support every staged language or syntax form.",
                ),
            )

        operation_complete = operations.completed_operations == profile_operations
        coverage_complete = staged.skipped_files == 0 and operation_complete
        return ReachabilityEvidence(
            snapshot_id=snapshot_id,
            package_name=package_name,
            target_identifiers=targets,
            analysis_root=analysis_root,
            profile=profile,
            engine="ast-grep",
            engine_version=AST_GREP_VERSION,
            status=(
                "syntax_usage_found"
                if findings
                else "no_syntax_match"
                if coverage_complete
                else "incomplete"
            ),
            candidate_files=staged.candidate_files,
            staged_files=staged.staged_files,
            skipped_files=staged.skipped_files,
            staged_bytes=staged.staged_bytes,
            operations=profile_operations,
            completed_operations=operations.completed_operations,
            findings=tuple(findings),
            limitations=(
                "Results are syntactic evidence, not a call graph or exploitability proof.",
                "ast-grep may not support every staged language or syntax form.",
                "Computed imports, generated code, and dependency-internal calls may be missed.",
                *(
                    ("No syntax match is not evidence of non-reachability.",)
                    if not findings
                    else ()
                ),
                *(
                    (
                        "Analyzer input coverage is partial because one or more candidate files "
                        "could not be staged within trusted limits.",
                    )
                    if staged.skipped_files
                    else ()
                ),
                *(
                    (
                        "Analyzer operation coverage is partial because not every fixed "
                        "operation completed within trusted limits.",
                    )
                    if not operation_complete
                    else ()
                ),
                *(
                    ("Analyzer findings were capped at the configured limit.",)
                    if not findings_complete
                    else ()
                ),
            ),
        )


AstGrepReachabilityRunner = AstGrepRunner


def _unavailable(
    snapshot_id: str,
    package_name: str,
    target_identifiers: tuple[str, ...],
    profile: ReachabilityProfile,
    analysis_root: str,
    engine_version: str,
    limitation: str,
) -> ReachabilityEvidence:
    return ReachabilityEvidence(
        snapshot_id=snapshot_id,
        package_name=package_name,
        target_identifiers=target_identifiers,
        analysis_root=analysis_root,
        profile=profile,
        engine="ast-grep",
        engine_version=engine_version,
        status="unavailable",
        candidate_files=0,
        staged_files=0,
        skipped_files=0,
        staged_bytes=0,
        operations=operations_for_profile(profile),
        completed_operations=(),
        limitations=(
            limitation,
            "Analyzer unavailability is not evidence of non-reachability.",
        ),
    )
