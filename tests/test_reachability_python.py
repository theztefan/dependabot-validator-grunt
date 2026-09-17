"""Python structural interpretation tests."""

from pathlib import Path

from reachability_test_support import analyze

from dependabot_validator_grunt.models import PYTHON_REACHABILITY_OPERATIONS


def test_ast_grep_python_profile_ignores_javascript_in_mixed_repository(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    (root / "a.js").write_text(
        "\n".join(f"import irrelevant_{index} from 'irrelevant-{index}'" for index in range(100)),
        encoding="utf-8",
    )
    (root / "z-app.py").write_text("import requests\n", encoding="utf-8")

    evidence = analyze(
        root,
        package_name="requests",
        profile="python",
        target_identifiers=("requests",),
        max_output_bytes=1024,
    )

    assert evidence.profile == "python"
    assert evidence.operations == PYTHON_REACHABILITY_OPERATIONS
    assert evidence.completed_operations == PYTHON_REACHABILITY_OPERATIONS
    assert [(finding.citation.path, finding.language) for finding in evidence.findings] == [
        ("z-app.py", "Python")
    ]
    assert evidence.candidate_files == evidence.staged_files == 1


def test_ast_grep_finds_python_imports_aliases_dynamic_imports_and_bound_calls(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    (root / "app.py").write_text(
        "import requests\n"
        "import requests as req\n"
        "from requests import get\n"
        "from requests import Session as Client\n"
        'module = importlib.import_module("requests.sessions")\n'
        'legacy = __import__("requests")\n'
        'requests.get("https://example.test")\n'
        'req.get("https://example.test")\n'
        'get("https://example.test")\n'
        "Client()\n"
        "module.Session()\n"
        'legacy.get("https://example.test")\n',
        encoding="utf-8",
    )

    evidence = analyze(
        root,
        package_name="requests-distribution",
        profile="python",
        target_identifiers=("requests",),
    )

    assert evidence.target_identifiers == ("requests",)
    assert {
        (
            finding.kind,
            finding.language,
            finding.matched_target,
            finding.binding,
            finding.citation.line,
        )
        for finding in evidence.findings
    } == {
        ("static_import", "Python", "requests", "requests", 1),
        ("static_import", "Python", "requests", "req", 2),
        ("static_import", "Python", "requests", "get", 3),
        ("static_import", "Python", "requests", "Client", 4),
        ("dynamic_import", "Python", "requests", "module", 5),
        ("dynamic_import", "Python", "requests", "legacy", 6),
        ("bound_call", "Python", "requests", "requests", 7),
        ("bound_call", "Python", "requests", "req", 8),
        ("bound_call", "Python", "requests", "get", 9),
        ("bound_call", "Python", "requests", "Client", 10),
        ("bound_call", "Python", "requests", "module", 11),
        ("bound_call", "Python", "requests", "legacy", 12),
    }


def test_python_dunder_import_requires_absolute_static_level(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    (root / "app.py").write_text(
        'absolute = __import__("requests")\n'
        'zero = __import__("requests", globals(), locals(), [], 0)\n'
        'zero_keyword = __import__("requests", level=0)\n'
        'relative = __import__("requests", globals(), locals(), [], 1)\n'
        'relative_keyword = __import__("requests", level=1)\n'
        'indeterminate = __import__("requests", *arguments)\n'
        'indeterminate_keyword = __import__("requests", **options)\n',
        encoding="utf-8",
    )

    evidence = analyze(
        root,
        package_name="requests",
        profile="python",
        target_identifiers=("requests",),
    )

    assert {
        (finding.kind, finding.binding, finding.citation.line) for finding in evidence.findings
    } == {
        ("dynamic_import", "absolute", 1),
        ("dynamic_import", "zero", 2),
        ("dynamic_import", "zero_keyword", 3),
    }


def test_ast_grep_binds_multiple_application_selected_targets(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    (root / "app.py").write_text(
        "import alpha\nfrom beta import run\nalpha.start()\nrun()\n",
        encoding="utf-8",
    )

    evidence = analyze(
        root,
        package_name="distribution",
        profile="python",
        target_identifiers=("alpha", "beta"),
    )

    assert evidence.target_identifiers == ("alpha", "beta")
    assert {(finding.matched_target, finding.binding) for finding in evidence.findings} == {
        ("alpha", "alpha"),
        ("beta", "run"),
    }


def test_ast_grep_python_does_not_reuse_bindings_across_files(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    (root / "python_import.py").write_text("import lodash\n", encoding="utf-8")
    (root / "python_unrelated.py").write_text("lodash()\n", encoding="utf-8")

    evidence = analyze(root, profile="python")

    assert [(finding.kind, finding.citation.path) for finding in evidence.findings] == [
        ("static_import", "python_import.py"),
    ]
