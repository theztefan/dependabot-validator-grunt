"""Bounded ast-grep structural-analysis tests."""

from pathlib import Path

from dependabot_validator_grunt.agentic import RepositoryTools
from dependabot_validator_grunt.models import ReachabilityEvidence
from dependabot_validator_grunt.reachability import AstGrepRunner


def _analyze(root: Path, **overrides: int):
    limits = {
        "wall_seconds": 30,
        "max_files": 100,
        "max_input_bytes": 1024 * 1024,
        "max_output_bytes": 1024 * 1024,
        "max_stderr_bytes": 64 * 1024,
        "max_findings": 100,
    }
    limits.update(overrides)
    return AstGrepRunner().analyze(
        root,
        snapshot_id="snapshot",
        package_name="lodash",
        **limits,
    )


def test_ast_grep_finds_package_import_require_and_bound_call(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    source = root / "src" / "app.ts"
    source.parent.mkdir(parents=True)
    source.write_text(
        "import lodash from 'lodash'\nconst other = require('lodash')\nlodash.get(value, 'x')\n",
        encoding="utf-8",
    )
    (root / "src" / "dynamic.ts").write_text(
        "const lazy = import /* webpackChunkName: 'lazy' */ ('lodash')\n",
        encoding="utf-8",
    )
    (root / "src" / "spaced.js").write_text(
        "const spaced = require /* deliberate trivia */ ('lodash')\n",
        encoding="utf-8",
    )

    evidence = _analyze(root)

    assert evidence.status == "syntax_usage_found"
    assert evidence.engine == "ast-grep"
    assert evidence.engine_version == "0.45.3"
    assert evidence.scanned_files == 3
    assert evidence.scanned_bytes == sum(
        path.stat().st_size for path in root.rglob("*") if path.is_file()
    )
    assert [(finding.kind, finding.binding) for finding in evidence.findings] == [
        ("import", "lodash"),
        ("require", "other"),
        ("dynamic_import", "lazy"),
        ("require", "spaced"),
        ("bound_call", "lodash"),
    ]
    assert {finding.citation.path for finding in evidence.findings} == {
        "src/app.ts",
        "src/dynamic.ts",
        "src/spaced.js",
    }


def test_ast_grep_no_match_is_only_syntax_absence(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    (root / "app.js").write_text("console.log('safe')\n", encoding="utf-8")

    evidence = _analyze(root)

    assert evidence.status == "no_syntax_match"
    assert evidence.findings == ()
    assert any("not a call graph" in limitation for limitation in evidence.limitations)


def test_ast_grep_excludes_denied_and_non_source_files(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    denied = root / ".github" / "instructions.js"
    denied.parent.mkdir(parents=True)
    denied.write_text("import lodash from 'lodash'\n", encoding="utf-8")
    (root / "notes.txt").write_text("require('lodash')\n", encoding="utf-8")

    evidence = _analyze(root)

    assert evidence.status == "no_syntax_match"
    assert evidence.scanned_files == 0
    assert evidence.scanned_bytes == 0


def test_ast_grep_does_not_reuse_bindings_across_files(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    (root / "import.js").write_text("import lodash from 'lodash'\n", encoding="utf-8")
    (root / "unrelated.js").write_text("lodash()\n", encoding="utf-8")

    evidence = _analyze(root)

    assert [(finding.kind, finding.citation.path) for finding in evidence.findings] == [
        ("import", "import.js")
    ]


def test_ast_grep_resource_limit_failures_are_incomplete(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    (root / "app.js").write_text(
        "\n".join("require('lodash')" for _ in range(20)),
        encoding="utf-8",
    )

    assert _analyze(root, max_input_bytes=1).status == "incomplete"
    assert _analyze(root, max_output_bytes=1).status == "incomplete"
    limited = _analyze(root, max_findings=1)
    assert limited.status == "syntax_usage_found"
    assert len(limited.findings) == 1
    assert any("capped" in limitation for limitation in limited.limitations)


def test_ast_grep_preserves_positive_evidence_from_partial_file_set(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    (root / "a.js").write_text("require('lodash')\n", encoding="utf-8")
    (root / "b.js").write_text("console.log('later')\n", encoding="utf-8")

    evidence = _analyze(root, max_files=1)

    assert evidence.status == "syntax_usage_found"
    assert len(evidence.findings) == 1
    assert evidence.scanned_files == 1
    assert any("partial" in limitation.casefold() for limitation in evidence.limitations)


def test_ast_grep_partial_no_match_remains_incomplete(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    (root / "a.js").write_text("console.log('first')\n", encoding="utf-8")
    (root / "b.js").write_text("require('lodash')\n", encoding="utf-8")

    evidence = _analyze(root, max_files=1)

    assert evidence.status == "incomplete"
    assert evidence.findings == ()
    assert evidence.scanned_files == 1


def test_ast_grep_skips_oversized_file_and_reaches_later_candidate(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    (root / "a.js").write_text("x" * 100, encoding="utf-8")
    (root / "b.js").write_text("require('lodash')\n", encoding="utf-8")

    evidence = _analyze(root, max_input_bytes=32)

    assert evidence.status == "syntax_usage_found"
    assert [finding.citation.path for finding in evidence.findings] == ["b.js"]
    assert any("partial" in limitation.casefold() for limitation in evidence.limitations)


def test_ast_grep_preserves_import_when_later_operation_exceeds_output_limit(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    (root / "app.js").write_text(
        "import lodash from 'lodash'\n"
        + "\n".join(f"console.log({index})" for index in range(3_000)),
        encoding="utf-8",
    )

    evidence = _analyze(root, max_output_bytes=1024)

    assert evidence.status == "syntax_usage_found"
    assert [(finding.kind, finding.citation.line) for finding in evidence.findings] == [
        ("import", 1)
    ]
    assert any("capped" in limitation for limitation in evidence.limitations)


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
        wall_seconds: int,
        max_files: int,
        max_input_bytes: int,
        max_output_bytes: int,
        max_stderr_bytes: int,
        max_findings: int,
    ) -> ReachabilityEvidence:
        del (
            root,
            wall_seconds,
            max_files,
            max_input_bytes,
            max_output_bytes,
            max_stderr_bytes,
            max_findings,
        )
        self.calls += 1
        return ReachabilityEvidence(
            snapshot_id=snapshot_id,
            package_name=package_name,
            engine="ast-grep",
            engine_version="test",
            status="no_syntax_match",
            scanned_files=0,
            scanned_bytes=0,
            limitations=("Synthetic result.",),
        )


def test_repository_tools_cache_repeated_reachability_invocations(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    runner = CountingRunner()
    tools = RepositoryTools(root, reachability_runner=runner)

    first = tools.analyze_reachability(snapshot_id="snapshot", package_name="lodash")
    second = tools.analyze_reachability(snapshot_id="snapshot", package_name="lodash")

    assert first is second
    assert runner.calls == 1
    assert tools.reachability_invocation_count == 2


def test_ast_grep_missing_executable_is_unavailable(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    (root / "app.js").write_text("require('lodash')\n", encoding="utf-8")

    evidence = AstGrepRunner(tmp_path / "missing-ast-grep").analyze(
        root,
        snapshot_id="snapshot",
        package_name="lodash",
        wall_seconds=30,
        max_files=100,
        max_input_bytes=1024,
        max_output_bytes=1024,
        max_stderr_bytes=1024,
        max_findings=10,
    )

    assert evidence.status == "unavailable"
    assert evidence.findings == ()
