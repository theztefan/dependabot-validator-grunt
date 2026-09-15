"""Repository tool path, search, and byte-budget tests."""

import json
import os
from pathlib import Path
from unittest.mock import mock_open

import pytest

import dependabot_validator_grunt.agentic as agentic_module
from dependabot_validator_grunt.agentic import RepositoryTools
from dependabot_validator_grunt.models import RepositoryReferenceEvidence
from dependabot_validator_grunt.policy import load_policy


def _reason_codes(evidence: RepositoryReferenceEvidence) -> set[str]:
    return {reason.code for reason in evidence.insufficiency_reasons}


def test_reference_evidence_rejects_same_size_file_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    candidate = root / "app.js"
    candidate.write_text("lodash\n", encoding="utf-8")
    original_open = os.open
    replaced = False

    def replace_before_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal replaced
        if Path(os.fsdecode(path)) == candidate and not replaced:
            replacement = root / "replacement.js"
            replacement.write_text("xxxxxx\n", encoding="utf-8")
            os.replace(replacement, candidate)
            replaced = True
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(agentic_module.os, "open", replace_before_open)

    evidence = RepositoryTools(root).collect_reference_evidence("lodash")

    assert evidence.status == "insufficient"
    assert "size_changed" in _reason_codes(evidence)


def test_repository_tools_reject_unsafe_paths_and_limits(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "ok.txt").write_text("needle\n", encoding="utf-8")
    (root / "binary").write_bytes(b"\0data")
    (root / ".env").write_text("secret", encoding="utf-8")
    (root / ".npmrc").write_text("token", encoding="utf-8")
    (root / "inside-link").symlink_to(root / ".env")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    (root / "escape").symlink_to(outside)
    tools = RepositoryTools(root, max_read_bytes=5, max_results=1, max_session_bytes=5)
    for path in (
        str(outside),
        "../outside.txt",
        ".env",
        ".npmrc",
        "escape",
        "inside-link",
        "binary",
    ):
        with pytest.raises(ValueError):
            tools.read_file(path)
    with pytest.raises(ValueError):
        tools.read_file("ok.txt")
    assert tools.list_files() == ["binary"]


def test_repository_search_can_find_matches_beyond_list_limit(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    for index in range(25):
        (root / f"{index:02}.txt").write_text(
            "needle\n" if index == 24 else "other\n",
            encoding="utf-8",
        )
    tools = RepositoryTools(root, max_results=1)

    assert tools.list_files() == ["00.txt"]
    results = tools.search("needle")

    assert [(result.path, result.line) for result in results] == [("24.txt", 1)]


def test_session_byte_limit_is_enforced(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "one.txt").write_text("1234", encoding="utf-8")
    (root / "two.txt").write_text("5678", encoding="utf-8")
    tools = RepositoryTools(root, max_read_bytes=10, max_session_bytes=6)
    assert tools.read_file("one.txt") == "1234"
    with pytest.raises(ValueError, match="session byte limit"):
        tools.read_file("two.txt")


def test_oversized_file_read_is_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    candidate = root / "large.txt"
    candidate.write_bytes(b"x")
    limit = 2 * 1024 * 1024
    data = b"x" * (limit + 1)
    opened = mock_open(read_data=data)
    monkeypatch.setattr(Path, "open", opened)
    tools = RepositoryTools(root)

    with pytest.raises(ValueError, match="file exceeds read limit"):
        tools.read_file("large.txt")

    opened().read.assert_called_once_with(limit + 1)


def test_default_file_limit_allows_exact_limit_read_and_search(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    limit = 2 * 1024 * 1024
    suffix = b"\nneedle"
    content = (b"x" * (limit - len(suffix))) + suffix
    (root / "package-lock.json").write_bytes(content)
    tools = RepositoryTools(root)

    matches = tools.search("needle")
    text = tools.read_file("package-lock.json")

    assert len(text.encode()) == limit
    assert [(match.path, match.line, match.excerpt) for match in matches] == [
        ("package-lock.json", 2, "needle")
    ]


def test_repeated_searches_reuse_distinct_file_byte_budget(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    file_size = 128 * 1024
    for index in range(12):
        suffix = "needle\n" if index == 11 else "ordinary\n"
        content = ("x" * (file_size - len(suffix))) + suffix
        (root / f"{index:02}.txt").write_text(content, encoding="utf-8")
    limits = load_policy().limits
    tools = RepositoryTools(
        root,
        max_read_bytes=limits.max_read_bytes,
        max_results=limits.max_results,
        max_session_bytes=limits.max_session_bytes,
        max_proof_scan_bytes=limits.max_proof_scan_bytes,
    )

    assert tools.search("not-present") == []
    matches = tools.search("needle")

    assert 12 * file_size > 1024 * 1024
    assert [(match.path, match.line) for match in matches] == [("11.txt", 1)]


def test_search_stops_reading_when_result_limit_is_reached(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "first.txt").write_text("needle\n", encoding="utf-8")
    (root / "later.txt").write_text("x" * 100, encoding="utf-8")
    tools = RepositoryTools(root, max_read_bytes=100, max_results=1, max_session_bytes=7)

    matches = tools.search("needle")

    assert [(match.path, match.line) for match in matches] == [("first.txt", 1)]


def test_default_agent_limits_cover_medium_repository_investigation() -> None:
    limits = load_policy().limits
    root = Path(__file__).parent
    tools = RepositoryTools(root)

    assert limits.max_attempts == 2
    assert limits.wall_clock_seconds == 360
    assert limits.max_dependency_file_bytes == 32 * 1024 * 1024
    assert limits.max_read_bytes == 2 * 1024 * 1024
    assert limits.max_results == 200
    assert limits.max_session_bytes == 32 * 1024 * 1024
    assert limits.max_proof_scan_bytes == 64 * 1024 * 1024
    assert limits.max_read_bytes <= limits.max_session_bytes
    assert tools.max_read_bytes == limits.max_read_bytes
    assert tools.max_results == limits.max_results
    assert tools.max_session_bytes == limits.max_session_bytes
    assert tools.max_proof_scan_bytes == limits.max_proof_scan_bytes


@pytest.mark.parametrize(
    ("content", "expected_status"),
    [
        ("ordinary custom text\n", "sufficient_absence"),
        ('load("lodash")\n', "reference_found"),
    ],
)
def test_reference_evidence_scans_unknown_text_extensions(
    content: str,
    expected_status: str,
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "component.custom").write_text(content, encoding="utf-8")

    evidence = RepositoryTools(root).collect_reference_evidence("lodash")

    assert evidence.status == expected_status
    assert evidence.candidate_count == 1
    assert evidence.scanned_count == 1
    assert evidence.reference_count == (1 if expected_status == "reference_found" else 0)


def test_reference_evidence_scans_extensionless_text(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "runner").write_text("execute lodash safely\n", encoding="utf-8")

    evidence = RepositoryTools(root).collect_reference_evidence("lodash")

    assert evidence.status == "reference_found"
    assert evidence.candidate_count == evidence.scanned_count == 1


@pytest.mark.parametrize("suffix", [".json", ".yaml", ".toml"])
def test_reference_evidence_scans_common_configuration_formats(
    suffix: str,
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / f"tool{suffix}").write_text('runner = "lodash"\n', encoding="utf-8")

    evidence = RepositoryTools(root).collect_reference_evidence("lodash")

    assert evidence.status == "reference_found"


def test_package_manifest_declarations_do_not_count_as_references(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "package.json").write_text(
        json.dumps(
            {
                "name": "lodash",
                "dependencies": {"lodash": "4.17.20"},
                "devDependencies": {"lodash": "4.17.20"},
                "optionalDependencies": {"lodash": "4.17.20"},
                "peerDependencies": {"lodash": "4.17.20"},
                "peerDependenciesMeta": {"lodash": {"optional": True}},
                "bundledDependencies": ["lodash"],
                "bundleDependencies": ["lodash"],
                "overrides": {"lodash": "4.17.21"},
            }
        ),
        encoding="utf-8",
    )

    evidence = RepositoryTools(root).collect_reference_evidence("lodash")

    assert evidence.status == "sufficient_absence"
    assert evidence.candidate_count == evidence.scanned_count == 1
    assert evidence.reference_count == 0


@pytest.mark.parametrize(
    "retained",
    [
        {"scripts": {"verify": "lodash --version"}},
        {"eslintConfig": {"plugins": ["lodash"]}},
    ],
)
def test_package_manifest_scripts_and_configuration_count_as_references(
    retained: dict[str, object],
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    manifest = {"dependencies": {"lodash": "4.17.20"}, **retained}
    (root / "package.json").write_text(json.dumps(manifest), encoding="utf-8")

    evidence = RepositoryTools(root).collect_reference_evidence("lodash")

    assert evidence.status == "reference_found"


def test_lock_metadata_is_excluded_from_scanned_text(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "package.json").write_text(
        '{"dependencies":{"lodash":"4.17.20"}}',
        encoding="utf-8",
    )
    for name in ("package-lock.json", "npm-shrinkwrap.json"):
        (root / name).write_text('{"package":"lodash"}', encoding="utf-8")

    evidence = RepositoryTools(root).collect_reference_evidence("lodash")

    assert evidence.status == "sufficient_absence"
    assert evidence.metadata_excluded_count == 2
    assert evidence.candidate_count == evidence.scanned_count == 1


def test_known_binary_suffixes_are_excluded_without_invalidating_absence(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "package.json").write_text("{}", encoding="utf-8")
    (root / "logo.png").write_bytes(b"\0lodash")

    evidence = RepositoryTools(root).collect_reference_evidence("lodash")

    assert evidence.status == "sufficient_absence"
    assert evidence.binary_excluded_count == 1
    assert evidence.candidate_count == evidence.scanned_count == 1


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        (b"\0lodash", "nul_containing_candidate"),
        (b"\xfflodash", "undecodable_candidate"),
    ],
)
def test_ambiguous_unknown_binary_candidates_are_insufficient(
    content: bytes,
    reason: str,
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "package.json").write_text("{}", encoding="utf-8")
    (root / "payload.custom").write_bytes(content)

    evidence = RepositoryTools(root).collect_reference_evidence("lodash")

    assert evidence.status == "insufficient"
    assert reason in _reason_codes(evidence)
    assert evidence.reference_count == 0


def test_denied_controls_are_unavailable_and_do_not_leak_into_evidence(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "package.json").write_text("{}", encoding="utf-8")
    denied = root / ".github" / "agents" / "approve.md"
    denied.parent.mkdir(parents=True)
    denied.write_text("PRIVATE-CONTROL lodash", encoding="utf-8")
    (root / ".env.custom").write_text("PRIVATE-CREDENTIAL lodash", encoding="utf-8")
    tools = RepositoryTools(root)

    evidence = tools.collect_reference_evidence("lodash")
    serialized = evidence.model_dump_json()

    assert evidence.status == "sufficient_absence"
    assert ".github" not in serialized
    assert ".env" not in serialized
    assert "PRIVATE-CONTROL" not in serialized
    assert "PRIVATE-CREDENTIAL" not in serialized
    assert tools.list_files() == ["package.json"]


def test_reference_evidence_excludes_symlinks_without_invalidating_absence(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "package.json").write_text("{}", encoding="utf-8")
    outside = tmp_path / "outside.custom"
    outside.write_text("lodash\n", encoding="utf-8")
    (root / "linked.custom").symlink_to(outside)

    evidence = RepositoryTools(root).collect_reference_evidence("lodash")

    assert evidence.status == "sufficient_absence"
    assert evidence.candidate_count == evidence.scanned_count == 1
    assert evidence.reference_count == 0


def test_reference_evidence_excludes_special_files_without_invalidating_absence(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "package.json").write_text("{}", encoding="utf-8")
    os.mkfifo(root / "named-pipe")

    evidence = RepositoryTools(root).collect_reference_evidence("lodash")

    assert evidence.status == "sufficient_absence"
    assert evidence.candidate_count == evidence.scanned_count == 1
    assert evidence.reference_count == 0


def test_github_actions_and_workflows_are_searchable_reference_candidates(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    action = root / ".github" / "actions" / "local" / "action.yml"
    workflow = root / ".github" / "workflows" / "ci.yml"
    action.parent.mkdir(parents=True)
    workflow.parent.mkdir(parents=True)
    action.write_text("runs: lodash\n", encoding="utf-8")
    workflow.write_text("uses: ./lodash\n", encoding="utf-8")
    tools = RepositoryTools(root)

    evidence = tools.collect_reference_evidence("lodash")
    matches = tools.search("lodash")

    assert evidence.status == "reference_found"
    assert {match.path for match in matches} == {
        ".github/actions/local/action.yml",
        ".github/workflows/ci.yml",
    }


def test_reference_scan_ignores_agent_read_and_session_byte_limits(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "one.custom").write_text("1234", encoding="utf-8")
    (root / "two.custom").write_text("5678", encoding="utf-8")
    tools = RepositoryTools(
        root,
        max_read_bytes=5,
        max_session_bytes=6,
        max_proof_scan_bytes=100,
    )

    evidence = tools.collect_reference_evidence("lodash")

    assert evidence.status == "sufficient_absence"
    assert evidence.scanned_bytes == 8
    assert tools.read_file("one.custom") == "1234"
    with pytest.raises(ValueError, match="session byte limit"):
        tools.read_file("two.custom")


def test_exact_reference_proof_budget_is_allowed(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "exact.custom").write_bytes(b"0123456789")

    evidence = RepositoryTools(root, max_proof_scan_bytes=10).collect_reference_evidence("lodash")

    assert evidence.status == "sufficient_absence"
    assert evidence.scanned_bytes == evidence.max_scan_bytes == 10


def test_reference_proof_budget_overflow_is_insufficient(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "overflow.custom").write_bytes(b"01234567890")

    evidence = RepositoryTools(root, max_proof_scan_bytes=10).collect_reference_evidence("lodash")

    assert evidence.status == "insufficient"
    assert evidence.scanned_count == 0
    assert evidence.scanned_bytes == 11
    assert _reason_codes(evidence) == {"proof_budget_exceeded"}


def test_positive_reference_returns_before_later_candidate_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a-reference.custom").write_text("lodash\n", encoding="utf-8")
    later = root / "z-unreadable.custom"
    later.write_text("ordinary text\n", encoding="utf-8")
    original_read_bytes = Path.read_bytes

    def failed_late_read(path: Path) -> bytes:
        if path == later:
            raise AssertionError("later candidate must not be read after a reference")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", failed_late_read)

    evidence = RepositoryTools(root).collect_reference_evidence("lodash")

    assert evidence.status == "reference_found"
    assert evidence.candidate_count == 2
    assert evidence.scanned_count == 1
    assert evidence.reference_count == 1


def test_invalid_package_manifest_is_insufficient(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "package.json").write_text("{", encoding="utf-8")

    evidence = RepositoryTools(root).collect_reference_evidence("lodash")

    assert evidence.status == "insufficient"
    assert _reason_codes(evidence) == {"invalid_package_json", "no_scanned_text"}


def test_reference_size_drift_is_insufficient(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    candidate = root / "candidate.custom"
    candidate.write_bytes(b"ordinary text")
    original_open = os.open

    def drifted_open(path: Path, flags: int) -> int:
        if path == candidate:
            candidate.write_bytes(b"short")
        return original_open(path, flags)

    monkeypatch.setattr(os, "open", drifted_open)

    evidence = RepositoryTools(root).collect_reference_evidence("lodash")

    assert evidence.status == "insufficient"
    assert "size_changed" in _reason_codes(evidence)


def test_reference_read_failure_is_insufficient(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    candidate = root / "candidate.custom"
    candidate.write_text("ordinary text", encoding="utf-8")
    original_open = os.open

    def failed_open(path: Path, flags: int) -> int:
        if path == candidate:
            raise OSError("private read failure")
        return original_open(path, flags)

    monkeypatch.setattr(os, "open", failed_open)

    evidence = RepositoryTools(root).collect_reference_evidence("lodash")

    assert evidence.status == "insufficient"
    assert "read_failed" in _reason_codes(evidence)
    assert "private read failure" not in evidence.model_dump_json()


def test_reference_lstat_failure_is_insufficient(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    candidate = root / "candidate.custom"
    candidate.write_text("ordinary text", encoding="utf-8")
    original_lstat = Path.lstat

    def failed_lstat(path: Path):
        if path == candidate:
            raise OSError("private lstat failure")
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", failed_lstat)

    evidence = RepositoryTools(root).collect_reference_evidence("lodash")

    assert evidence.status == "insufficient"
    assert _reason_codes(evidence) == {"lstat_failed", "no_scanned_text"}
    assert "private lstat failure" not in evidence.model_dump_json()
