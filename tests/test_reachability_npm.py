"""npm JavaScript and TypeScript structural interpretation tests."""

from pathlib import Path

from reachability_test_support import analyze

from dependabot_validator_grunt.models import NPM_REACHABILITY_OPERATIONS


def test_ast_grep_preserves_npm_finding_order_and_common_semantics(tmp_path: Path) -> None:
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

    evidence = analyze(root)

    assert evidence.status == "syntax_usage_found"
    assert evidence.engine == "ast-grep"
    assert evidence.engine_version == "0.45.3"
    assert evidence.profile == "npm"
    assert evidence.target_identifiers == ("lodash",)
    assert evidence.candidate_files == evidence.staged_files == 3
    assert evidence.skipped_files == 0
    assert evidence.staged_bytes == sum(
        path.stat().st_size for path in root.rglob("*") if path.is_file()
    )
    assert evidence.operations == evidence.completed_operations == NPM_REACHABILITY_OPERATIONS
    assert [
        (
            finding.kind,
            finding.language,
            finding.matched_target,
            finding.binding,
        )
        for finding in evidence.findings
    ] == [
        ("static_import", "TypeScript", "lodash", "lodash"),
        ("runtime_require", "TypeScript", "lodash", "other"),
        ("dynamic_import", "TypeScript", "lodash", "lazy"),
        ("runtime_require", "JavaScript", "lodash", "spaced"),
        ("bound_call", "TypeScript", "lodash", "lodash"),
    ]


def test_ast_grep_npm_profile_ignores_python_in_mixed_repository(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    (root / "a.py").write_text(
        "\n".join(f"import irrelevant_{index}" for index in range(100)),
        encoding="utf-8",
    )
    (root / "z-app.js").write_text("import lodash from 'lodash'\n", encoding="utf-8")

    evidence = analyze(root, max_output_bytes=1024)

    assert evidence.profile == "npm"
    assert evidence.operations == NPM_REACHABILITY_OPERATIONS
    assert evidence.completed_operations == NPM_REACHABILITY_OPERATIONS
    assert [(finding.citation.path, finding.language) for finding in evidence.findings] == [
        ("z-app.js", "JavaScript")
    ]
    assert evidence.candidate_files == evidence.staged_files == 1


def test_ast_grep_npm_does_not_reuse_bindings_across_files(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    (root / "import.js").write_text("import lodash from 'lodash'\n", encoding="utf-8")
    (root / "unrelated.js").write_text("lodash()\n", encoding="utf-8")

    evidence = analyze(root)

    assert [(finding.kind, finding.citation.path) for finding in evidence.findings] == [
        ("static_import", "import.js"),
    ]
