"""Public reachability facade and repository-tool integration tests."""

from collections.abc import Sequence
from pathlib import Path

import pytest

from dependabot_validator_grunt.agentic import RepositoryTools
from dependabot_validator_grunt.models import (
    NPM_REACHABILITY_OPERATIONS,
    PYTHON_REACHABILITY_OPERATIONS,
    ReachabilityEvidence,
    ReachabilityProfile,
)
from dependabot_validator_grunt.reachability import (
    AstGrepReachabilityRunner,
    AstGrepRunner,
)


class CountingRunner:
    """Record analyzer execution while returning stable evidence."""

    def __init__(self) -> None:
        self.calls = 0

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
        del (
            root,
            wall_seconds,
            max_files,
            max_input_bytes,
            max_batch_files,
            max_batch_bytes,
            max_output_bytes,
            max_stderr_bytes,
            max_findings,
        )
        self.calls += 1
        targets = (package_name,) if target_identifiers is None else tuple(target_identifiers)
        operations = (
            NPM_REACHABILITY_OPERATIONS if profile == "npm" else PYTHON_REACHABILITY_OPERATIONS
        )
        return ReachabilityEvidence(
            snapshot_id=snapshot_id,
            package_name=package_name,
            target_identifiers=targets,
            analysis_root=analysis_root,
            profile=profile,
            engine="ast-grep",
            engine_version="test",
            status="no_syntax_match",
            candidate_files=0,
            staged_files=0,
            skipped_files=0,
            staged_bytes=0,
            operations=operations,
            completed_operations=operations,
            limitations=("Synthetic result.",),
        )


def test_ast_grep_runner_compatibility_alias_is_stable() -> None:
    assert AstGrepReachabilityRunner is AstGrepRunner


def test_repository_tools_cache_repeated_reachability_invocations(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    runner = CountingRunner()
    tools = RepositoryTools(root, reachability_runner=runner)

    first = tools.analyze_reachability(
        snapshot_id="snapshot",
        package_name="lodash",
        profile="npm",
    )
    second = tools.analyze_reachability(
        snapshot_id="snapshot",
        package_name="lodash",
        profile="npm",
        target_identifiers=("lodash",),
    )

    assert first is second
    assert first.target_identifiers == ("lodash",)
    assert runner.calls == 1
    assert tools.reachability_invocation_count == 2
    with pytest.raises(ValueError, match="identity mismatch"):
        tools.analyze_reachability(
            snapshot_id="snapshot",
            package_name="lodash",
            profile="npm",
            target_identifiers=("underscore",),
        )
    with pytest.raises(ValueError, match="identity mismatch"):
        tools.analyze_reachability(
            snapshot_id="snapshot",
            package_name="lodash",
            profile="python",
            target_identifiers=("lodash",),
        )


def test_analyzer_requires_application_selected_target_identifiers(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    runner = AstGrepRunner()

    with pytest.raises(ValueError, match="at least one"):
        runner.analyze(
            root,
            snapshot_id="snapshot",
            package_name="distribution",
            profile="python",
            target_identifiers=(),
            wall_seconds=30,
            max_files=100,
            max_input_bytes=1024,
            max_batch_files=100,
            max_batch_bytes=1024,
            max_output_bytes=1024,
            max_stderr_bytes=1024,
            max_findings=10,
        )
    with pytest.raises(ValueError, match="sequence"):
        runner.analyze(
            root,
            snapshot_id="snapshot",
            package_name="distribution",
            profile="python",
            target_identifiers="requests",
            wall_seconds=30,
            max_files=100,
            max_input_bytes=1024,
            max_batch_files=100,
            max_batch_bytes=1024,
            max_output_bytes=1024,
            max_stderr_bytes=1024,
            max_findings=10,
        )
