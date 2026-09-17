"""Trusted ast-grep staging, subprocess, and citation tests."""

import hashlib
import os
from pathlib import Path

import pytest
from reachability_test_support import analyze

from dependabot_validator_grunt.models import NPM_REACHABILITY_OPERATIONS
from dependabot_validator_grunt.reachability import AstGrepRunner
from dependabot_validator_grunt.reachability_ast_grep import build_finding


def test_ast_grep_excludes_non_profile_and_denied_paths(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    denied = root / ".github" / "instructions.js"
    denied.parent.mkdir(parents=True)
    denied.write_text("import lodash from 'lodash'\n", encoding="utf-8")
    (root / "notes.txt").write_text("require('lodash')\n", encoding="utf-8")
    (root / "source.custom").write_text("import lodash\n", encoding="utf-8")

    evidence = analyze(root)

    assert evidence.status == "no_syntax_match"
    assert evidence.candidate_files == evidence.staged_files == 0
    assert evidence.skipped_files == 0
    assert evidence.staged_bytes == 0
    assert evidence.findings == ()
    assert any(
        "may not support every staged language" in limitation for limitation in evidence.limitations
    )
    assert any(
        "not evidence of non-reachability" in limitation for limitation in evidence.limitations
    )


@pytest.mark.parametrize(
    "repository_config",
    [
        "not: [valid\n",
        'languageGlobs:\n  yaml:\n    - "*.js"\n',
    ],
)
def test_ast_grep_ignores_repository_config(
    tmp_path: Path,
    repository_config: str,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    (root / "app.js").write_text("require('lodash')\n", encoding="utf-8")
    (root / "sgconfig.yml").write_text(repository_config, encoding="utf-8")

    evidence = analyze(root)

    assert evidence.status == "syntax_usage_found"
    assert [finding.citation.path for finding in evidence.findings] == ["app.js"]
    assert evidence.candidate_files == evidence.staged_files == 1
    assert evidence.completed_operations == NPM_REACHABILITY_OPERATIONS


def test_ast_grep_treats_option_shaped_filename_as_path(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    (root / "--help.js").write_text("require('lodash')\n", encoding="utf-8")

    evidence = analyze(root)

    assert evidence.status == "syntax_usage_found"
    assert [finding.citation.path for finding in evidence.findings] == ["--help.js"]
    assert evidence.completed_operations == NPM_REACHABILITY_OPERATIONS


def test_ast_grep_excludes_symlinks_and_special_files(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    source = root / "source.js"
    source.write_text("require('lodash')\n", encoding="utf-8")
    (root / "linked.js").symlink_to(source)
    os.mkfifo(root / "named-pipe")

    evidence = analyze(root)

    assert evidence.candidate_files == evidence.staged_files == 1
    assert evidence.skipped_files == 0
    assert [finding.citation.path for finding in evidence.findings] == ["source.js"]


def test_ast_grep_profile_filter_excludes_metadata_and_docs_from_file_limit(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    (root / "a-package-lock.json").write_text('{"lockfileVersion": 3}\n', encoding="utf-8")
    (root / "README.md").write_text("require('lodash')\n", encoding="utf-8")
    (root / "z-source.js").write_text("require('lodash')\n", encoding="utf-8")

    evidence = analyze(root, max_files=1)

    assert evidence.status == "syntax_usage_found"
    assert [finding.citation.path for finding in evidence.findings] == ["z-source.js"]
    assert (evidence.candidate_files, evidence.staged_files, evidence.skipped_files) == (1, 1, 0)


def test_ast_grep_resource_limit_failures_are_incomplete(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    (root / "app.js").write_text(
        "\n".join("require('lodash')" for _ in range(20)),
        encoding="utf-8",
    )

    input_limited = analyze(root, max_input_bytes=1)
    assert input_limited.status == "incomplete"
    assert (input_limited.candidate_files, input_limited.staged_files) == (1, 0)

    assert analyze(root, max_output_bytes=1).status == "incomplete"
    limited = analyze(root, max_findings=1)
    assert limited.status == "syntax_usage_found"
    assert len(limited.findings) == 1
    assert any("capped" in limitation for limitation in limited.limitations)


def test_ast_grep_preserves_positive_evidence_from_partial_file_set(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    (root / "a.js").write_text("require('lodash')\n", encoding="utf-8")
    (root / "b.js").write_text("console.log('later')\n", encoding="utf-8")

    evidence = analyze(root, max_files=1)

    assert evidence.status == "syntax_usage_found"
    assert len(evidence.findings) == 1
    assert (evidence.candidate_files, evidence.staged_files, evidence.skipped_files) == (2, 1, 1)
    assert any("partial" in limitation.casefold() for limitation in evidence.limitations)


def test_ast_grep_partial_no_match_remains_incomplete(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    (root / "a.js").write_text("console.log('first')\n", encoding="utf-8")
    (root / "b.js").write_text("require('lodash')\n", encoding="utf-8")

    evidence = analyze(root, max_files=1)

    assert evidence.status == "incomplete"
    assert evidence.findings == ()
    assert (evidence.candidate_files, evidence.staged_files, evidence.skipped_files) == (2, 1, 1)


def test_ast_grep_skips_oversized_file_and_reaches_later_candidate(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    (root / "a.js").write_text("x" * 100, encoding="utf-8")
    (root / "b.js").write_text("require('lodash')\n", encoding="utf-8")

    evidence = analyze(root, max_input_bytes=32)

    assert evidence.status == "syntax_usage_found"
    assert [finding.citation.path for finding in evidence.findings] == ["b.js"]
    assert (evidence.candidate_files, evidence.staged_files, evidence.skipped_files) == (2, 1, 1)


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

    evidence = analyze(root, max_output_bytes=1024)

    assert evidence.status == "syntax_usage_found"
    assert [(finding.kind, finding.citation.line) for finding in evidence.findings] == [
        ("static_import", 1)
    ]
    assert evidence.completed_operations == ("import_statement",)
    assert any("operation coverage is partial" in limitation for limitation in evidence.limitations)


def test_ast_grep_filters_unrelated_import_output_before_collection(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    unrelated = "\n".join(f"import module{index} from 'package-{index}'" for index in range(3_000))
    (root / "app.js").write_text(
        f"{unrelated}\nimport lodash from 'lodash'\nlodash.get(value, 'x')\n",
        encoding="utf-8",
    )

    evidence = analyze(root, max_output_bytes=2048)

    assert evidence.status == "syntax_usage_found"
    assert [finding.matched_target for finding in evidence.findings] == [
        "lodash",
        "lodash",
    ]
    assert evidence.completed_operations == NPM_REACHABILITY_OPERATIONS


def test_ast_grep_citation_is_bound_to_exact_snapshot_line(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    line = "import lodash from 'lodash'"
    (root / "app.js").write_text(f"{line}\n", encoding="utf-8")

    evidence = analyze(root)

    citation = evidence.findings[0].citation
    assert citation.path == "app.js"
    assert citation.line == 1
    assert citation.excerpt == line
    assert citation.digest == hashlib.sha256(line.encode()).hexdigest()

    raw: dict[str, object] = {
        "file": "app.js",
        "language": "JavaScript",
        "text": "import other from 'other'",
        "range": {
            "byteOffset": {"start": 0, "end": len(line)},
            "start": {"line": 0, "column": 0},
        },
    }
    with pytest.raises(ValueError, match="does not match snapshot bytes"):
        build_finding(
            {"app.js": f"{line}\n".encode()},
            raw,
            kind="static_import",
            language="JavaScript",
            matched_target="lodash",
            binding="lodash",
        )


def test_ast_grep_missing_executable_is_unavailable(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    (root / "app.js").write_text("require('lodash')\n", encoding="utf-8")

    evidence = AstGrepRunner(tmp_path / "missing-ast-grep").analyze(
        root,
        snapshot_id="snapshot",
        package_name="lodash",
        profile="npm",
        wall_seconds=30,
        max_files=100,
        max_input_bytes=1024,
        max_batch_files=100,
        max_batch_bytes=1024,
        max_output_bytes=1024,
        max_stderr_bytes=1024,
        max_findings=10,
    )

    assert evidence.status == "unavailable"
    assert evidence.target_identifiers == ("lodash",)
    assert evidence.findings == ()
    assert evidence.completed_operations == ()
    assert any(
        "not evidence of non-reachability" in limitation for limitation in evidence.limitations
    )


def test_ast_grep_scopes_analysis_to_selected_project(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    selected = root / "services" / "selected"
    sibling = root / "services" / "sibling"
    selected.mkdir(parents=True)
    sibling.mkdir(parents=True)
    (selected / "app.py").write_text("print('selected')\n", encoding="utf-8")
    (sibling / "app.py").write_text("import requests\n", encoding="utf-8")

    evidence = analyze(
        root,
        package_name="requests",
        profile="python",
        analysis_root="services/selected",
        target_identifiers=("requests",),
    )

    assert evidence.analysis_root == "services/selected"
    assert evidence.status == "no_syntax_match"
    assert evidence.candidate_files == evidence.staged_files == 1
    assert evidence.findings == ()


def test_ast_grep_batches_profile_files_under_shared_limits(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    for index in range(25):
        (root / f"module-{index:02}.js").write_text(
            "require('lodash')\n" if index == 24 else "console.log('ok')\n",
            encoding="utf-8",
        )

    evidence = analyze(root, max_batch_files=10, max_batch_bytes=1024)

    assert evidence.status == "syntax_usage_found"
    assert evidence.candidate_files == evidence.staged_files == 25
    assert [finding.citation.path for finding in evidence.findings] == ["module-24.js"]
    assert evidence.completed_operations == NPM_REACHABILITY_OPERATIONS
