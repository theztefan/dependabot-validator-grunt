"""Trusted ast-grep staging, subprocess, output, and citation mechanics."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import re
import signal
import stat
import subprocess
import sysconfig
import tempfile
import threading
import time
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Literal

from pydantic import TypeAdapter, ValidationError

from dependabot_validator_grunt.agentic import path_is_denied
from dependabot_validator_grunt.models import (
    NPM_REACHABILITY_OPERATIONS,
    PYTHON_REACHABILITY_OPERATIONS,
    ReachabilityFinding,
    ReachabilityOperation,
    ReachabilityProfile,
    RepositoryFact,
    validate_safe_identifier,
)

AST_GREP_DISTRIBUTION = "ast-grep-cli"
AST_GREP_VERSION = "0.45.3"
AST_GREP_CONFIG = "ruleDirs: []\n"
NPM_AST_GREP_LANGUAGES = ("JavaScript", "TypeScript", "Tsx")
PYTHON_AST_GREP_LANGUAGES = ("Python",)
NPM_PROFILE_SUFFIXES = frozenset({".cjs", ".cts", ".js", ".jsx", ".mjs", ".mts", ".ts", ".tsx"})
PYTHON_PROFILE_SUFFIXES = frozenset({".py", ".pyi"})

type RawMatch = dict[str, object]
type OperationMatches = dict[ReachabilityOperation, tuple[RawMatch, ...]]
type FindingKind = Literal["static_import", "dynamic_import", "runtime_require", "bound_call"]


@dataclass(frozen=True)
class AstGrepAvailability:
    """Validated runtime availability or a fixed unavailable reason."""

    available: bool
    engine_version: str
    limitation: str | None = None


@dataclass(frozen=True)
class StagedInput:
    """Bounded immutable source bytes copied into the analyzer workspace."""

    paths: tuple[str, ...]
    sources: dict[str, bytes]
    candidate_files: int
    staged_files: int
    skipped_files: int
    staged_bytes: int


@dataclass(frozen=True)
class AstGrepWorkspace:
    """Application-owned configuration and staged repository paths."""

    staging: Path
    config: Path
    staged: StagedInput


@dataclass(frozen=True)
class OperationCollection:
    """Raw matches and the fixed operations that completed."""

    matches: OperationMatches
    completed_operations: tuple[ReachabilityOperation, ...]


def default_executable() -> Path:
    """Return the pinned distribution's expected script location."""

    return (Path(sysconfig.get_path("scripts")) / "ast-grep").resolve()


def validate_targets(
    package_name: str,
    target_identifiers: Sequence[str] | None,
) -> tuple[str, ...]:
    """Validate and de-duplicate application-selected target identifiers."""

    if isinstance(target_identifiers, str):
        raise ValueError("target identifiers must be a sequence of identifiers")
    targets = (package_name,) if target_identifiers is None else tuple(target_identifiers)
    if not targets:
        raise ValueError("at least one analyzer target identifier is required")
    unique: list[str] = []
    for target in targets:
        validate_safe_identifier(target)
        if target not in unique:
            unique.append(target)
    return tuple(unique)


def operations_for_profile(
    profile: ReachabilityProfile,
) -> tuple[ReachabilityOperation, ...]:
    """Return the fixed operation set for one explicit profile."""

    if profile == "npm":
        return NPM_REACHABILITY_OPERATIONS
    if profile == "python":
        return PYTHON_REACHABILITY_OPERATIONS
    raise ValueError("unsupported reachability profile")


def check_availability(executable: Path, deadline: float) -> AstGrepAvailability:
    """Verify the installed package and executable against the trusted pin."""

    try:
        package_version = importlib.metadata.version(AST_GREP_DISTRIBUTION)
    except importlib.metadata.PackageNotFoundError:
        package_version = ""
    if (
        package_version != AST_GREP_VERSION
        or not executable.is_file()
        or not os.access(executable, os.X_OK)
    ):
        return AstGrepAvailability(
            available=False,
            engine_version=package_version or "unavailable",
            limitation="The pinned ast-grep runtime is unavailable.",
        )
    process = subprocess.Popen(
        [str(executable), "--version"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={"NO_COLOR": "1"},
        start_new_session=True,
    )
    stdout, _ = _capture_bounded(
        process,
        deadline=min(deadline, time.monotonic() + 5),
        max_output_bytes=4096,
        max_stderr_bytes=4096,
    )
    version_text = stdout.decode("utf-8", errors="replace").strip()
    if process.returncode != 0 or version_text != f"ast-grep {AST_GREP_VERSION}":
        return AstGrepAvailability(
            available=False,
            engine_version=version_text or "invalid",
            limitation="The ast-grep runtime version did not match the trusted pin.",
        )
    return AstGrepAvailability(available=True, engine_version=AST_GREP_VERSION)


@contextmanager
def temporary_workspace(
    root: Path,
    *,
    analysis_root: str,
    profile: ReachabilityProfile,
    deadline: float,
    max_files: int,
    max_input_bytes: int,
    max_batch_bytes: int,
) -> Generator[AstGrepWorkspace]:
    """Stage trusted input with application-owned configuration."""

    with tempfile.TemporaryDirectory(prefix="dependabot-validator-ast-grep-") as directory:
        workspace = Path(directory)
        staging = workspace / "repository"
        config = workspace / "sgconfig.yml"
        staging.mkdir()
        config.write_text(AST_GREP_CONFIG, encoding="utf-8")
        staged = _stage(
            root,
            staging,
            analysis_root=analysis_root,
            profile=profile,
            deadline=deadline,
            max_files=max_files,
            max_input_bytes=max_input_bytes,
            max_batch_bytes=max_batch_bytes,
        )
        yield AstGrepWorkspace(staging=staging, config=config, staged=staged)


def collect_operations(
    executable: Path,
    workspace: AstGrepWorkspace,
    *,
    profile: ReachabilityProfile,
    target_identifiers: Sequence[str],
    deadline: float,
    max_batch_files: int,
    max_batch_bytes: int,
    max_output_bytes: int,
    max_stderr_bytes: int,
) -> OperationCollection:
    """Run the profile's fixed operations under shared output bounds."""

    profile_operations = operations_for_profile(profile)
    if not workspace.staged.paths:
        return OperationCollection(
            matches={operation: () for operation in profile_operations},
            completed_operations=profile_operations,
        )
    matches: OperationMatches = {}
    completed: list[ReachabilityOperation] = []
    remaining_output = max_output_bytes
    remaining_stderr = max_stderr_bytes
    for operation in profile_operations:
        operation_paths = _operation_paths(
            operation,
            workspace.staged,
            matches,
            target_identifiers=target_identifiers,
        )
        batches = _path_batches(
            operation_paths,
            workspace.staged.sources,
            max_batch_files=max_batch_files,
            max_batch_bytes=max_batch_bytes,
        )
        operation_matches: list[RawMatch] = []
        operation_complete = True
        for batch in batches:
            try:
                raw_matches, used_out, used_err = _run_operation(
                    executable,
                    workspace.staging,
                    workspace.config,
                    _operation_rules(
                        profile,
                        operation,
                        target_identifiers=target_identifiers,
                    ),
                    batch,
                    deadline=deadline,
                    max_output_bytes=remaining_output,
                    max_stderr_bytes=remaining_stderr,
                )
            except (
                OSError,
                TimeoutError,
                ValueError,
                subprocess.SubprocessError,
                ValidationError,
            ):
                operation_complete = False
                break
            operation_matches.extend(raw_matches)
            remaining_output -= used_out
            remaining_stderr -= used_err
        matches[operation] = tuple(operation_matches)
        if not operation_complete:
            break
        completed.append(operation)
    return OperationCollection(
        matches=matches,
        completed_operations=tuple(completed),
    )


def verify_sources(root: Path, sources: dict[str, bytes], deadline: float) -> None:
    """Confirm staged bytes still match regular snapshot files."""

    for relative, staged in sources.items():
        current = _read_regular_file(
            root.joinpath(*Path(relative).parts),
            deadline=deadline,
            max_bytes=len(staged),
        )
        if current != staged:
            raise ValueError("analyzer input changed during analysis")


def match_language(raw: RawMatch) -> str:
    """Return one validated non-empty ast-grep language."""

    language = TypeAdapter(str).validate_python(raw.get("language"))
    if not language:
        raise ValueError("analyzer returned an empty language")
    return language


def match_text(raw: RawMatch) -> str:
    """Return validated matched source text."""

    return TypeAdapter(str).validate_python(raw.get("text"))


def match_file(raw: RawMatch) -> str:
    """Return the validated relative file value before citation validation."""

    return TypeAdapter(str).validate_python(raw.get("file"))


def match_lines(raw: RawMatch) -> str:
    """Return the validated source-line context emitted by ast-grep."""

    return TypeAdapter(str).validate_python(raw.get("lines"))


def build_finding(
    sources: dict[str, bytes],
    raw: RawMatch,
    *,
    kind: FindingKind,
    language: str,
    matched_target: str,
    binding: str | None,
) -> ReachabilityFinding:
    """Validate one raw match and bind its citation to staged snapshot bytes."""

    relative = match_file(raw)
    if Path(relative).is_absolute() or ".." in Path(relative).parts or path_is_denied(relative):
        raise ValueError("analyzer returned an invalid path")
    data = sources.get(relative)
    if data is None:
        raise ValueError("analyzer citation target is invalid")
    if match_language(raw) != language:
        raise ValueError("analyzer language changed during interpretation")
    range_data = TypeAdapter(dict[str, object]).validate_python(raw.get("range"))
    start = TypeAdapter(dict[str, object]).validate_python(range_data.get("start"))
    byte_offsets = TypeAdapter(dict[str, object]).validate_python(range_data.get("byteOffset"))
    start_byte = TypeAdapter(int).validate_python(byte_offsets.get("start"))
    end_byte = TypeAdapter(int).validate_python(byte_offsets.get("end"))
    if start_byte < 0 or end_byte < start_byte or end_byte > len(data):
        raise ValueError("analyzer returned an invalid byte range")
    matched = match_text(raw).encode()
    if data[start_byte:end_byte] != matched:
        raise ValueError("analyzer result does not match snapshot bytes")
    line_index = data[:start_byte].count(b"\n")
    reported_line = TypeAdapter(int).validate_python(start.get("line"))
    lines = data.decode("utf-8").splitlines()
    if reported_line != line_index or line_index >= len(lines):
        raise ValueError("analyzer returned an invalid line")
    excerpt = lines[line_index][:500]
    citation = RepositoryFact(
        path=relative,
        line=line_index + 1,
        digest=hashlib.sha256(excerpt.encode()).hexdigest(),
        excerpt=excerpt,
    )
    return ReachabilityFinding(
        kind=kind,
        language=language,
        matched_target=matched_target,
        citation=citation,
        binding=binding,
    )


def limit_findings(
    findings: list[ReachabilityFinding],
    max_findings: int,
) -> tuple[list[ReachabilityFinding], bool]:
    """De-duplicate findings in encounter order and apply the configured cap."""

    unique: dict[
        tuple[str, int, str, str, str, str, str | None],
        ReachabilityFinding,
    ] = {}
    for finding in findings:
        key = (
            finding.citation.path,
            finding.citation.line,
            finding.citation.digest,
            finding.kind,
            finding.language,
            finding.matched_target,
            finding.binding,
        )
        unique.setdefault(key, finding)
    unique_findings = list(unique.values())
    return unique_findings[:max_findings], len(unique_findings) <= max_findings


def _stage(
    root: Path,
    staging: Path,
    *,
    analysis_root: str,
    profile: ReachabilityProfile,
    deadline: float,
    max_files: int,
    max_input_bytes: int,
    max_batch_bytes: int,
) -> StagedInput:
    project = root.joinpath(*Path(analysis_root).parts) if analysis_root else root
    resolved_root = root.resolve(strict=True)
    resolved_project = project.resolve(strict=True)
    if resolved_project != resolved_root and resolved_root not in resolved_project.parents:
        raise ValueError("analyzer project root escapes the repository snapshot")
    if not resolved_project.is_dir():
        raise ValueError("analyzer project root is not a directory")
    candidates: list[tuple[str, Path, os.stat_result]] = []
    for path in resolved_project.rglob("*"):
        _check_deadline(deadline)
        relative = path.relative_to(resolved_root).as_posix()
        if path_is_denied(relative):
            continue
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            continue
        if not _profile_accepts(relative, profile):
            continue
        candidates.append((relative, path, metadata))
    candidates.sort(key=lambda item: (item[0].casefold(), item[0]))

    sources: dict[str, bytes] = {}
    total = 0
    skipped = 0
    for relative, path, metadata in candidates:
        _check_deadline(deadline)
        if (
            len(sources) >= max_files
            or metadata.st_size > max_input_bytes - total
            or metadata.st_size > max_batch_bytes
        ):
            skipped += 1
            continue
        try:
            data = _read_regular_file(
                path,
                deadline=deadline,
                max_bytes=max_input_bytes - total,
            )
            data.decode("utf-8")
        except (OSError, UnicodeDecodeError, ValueError):
            skipped += 1
            continue
        total += len(data)
        if total > max_input_bytes:
            raise ValueError("analyzer input byte limit exceeded")
        target = staging.joinpath(*Path(relative).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        sources[relative] = data
    return StagedInput(
        paths=tuple(sources),
        sources=sources,
        candidate_files=len(candidates),
        staged_files=len(sources),
        skipped_files=skipped,
        staged_bytes=total,
    )


def _profile_accepts(relative: str, profile: ReachabilityProfile) -> bool:
    suffix = Path(relative).suffix.casefold()
    if profile == "npm":
        return suffix in NPM_PROFILE_SUFFIXES
    if profile == "python":
        return suffix in PYTHON_PROFILE_SUFFIXES
    raise ValueError("unsupported reachability profile")


def _operation_paths(
    operation: ReachabilityOperation,
    staged: StagedInput,
    matches: OperationMatches,
    *,
    target_identifiers: Sequence[str],
) -> tuple[str, ...]:
    if operation in {"import_statement", "import_from_statement"}:
        return staged.paths
    relevant = {
        path
        for path, data in staged.sources.items()
        if any(target.encode() in data for target in target_identifiers)
    }
    for operation_matches in matches.values():
        for raw in operation_matches:
            path = raw.get("file")
            if isinstance(path, str) and path in staged.sources:
                relevant.add(path)
    return tuple(path for path in staged.paths if path in relevant)


def _path_batches(
    paths: Sequence[str],
    sources: dict[str, bytes],
    *,
    max_batch_files: int,
    max_batch_bytes: int,
) -> tuple[tuple[str, ...], ...]:
    batches: list[tuple[str, ...]] = []
    current: list[str] = []
    current_bytes = 0
    for path in paths:
        size = len(sources[path])
        if current and (len(current) >= max_batch_files or current_bytes + size > max_batch_bytes):
            batches.append(tuple(current))
            current = []
            current_bytes = 0
        current.append(path)
        current_bytes += size
    if current:
        batches.append(tuple(current))
    return tuple(batches)


def _run_operation(
    executable: Path,
    staging: Path,
    config: Path,
    rules: str,
    paths: Sequence[str],
    *,
    deadline: float,
    max_output_bytes: int,
    max_stderr_bytes: int,
) -> tuple[list[RawMatch], int, int]:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("analyzer deadline exceeded")
    command = [
        str(executable),
        "scan",
        "--inline-rules",
        rules,
        "--json=stream",
        "--color",
        "never",
        "--threads",
        "1",
        "--config",
        str(config),
        "--",
        *paths,
    ]
    process = subprocess.Popen(
        command,
        cwd=staging,
        env={
            "HOME": str(staging),
            "TMPDIR": str(staging),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "NO_COLOR": "1",
        },
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    stdout, stderr = _capture_bounded(
        process,
        deadline=deadline,
        max_output_bytes=max_output_bytes,
        max_stderr_bytes=max_stderr_bytes,
    )
    if process.returncode not in {0, 1}:
        raise subprocess.SubprocessError("ast-grep failed")
    raw_output = stdout.decode("utf-8")
    objects: list[RawMatch] = []
    for line in raw_output.splitlines():
        objects.append(TypeAdapter(dict[str, object]).validate_python(json.loads(line)))
    return objects, len(stdout), len(stderr)


def _operation_rules(
    profile: ReachabilityProfile,
    operation: ReachabilityOperation,
    *,
    target_identifiers: Sequence[str],
) -> str:
    if profile == "npm":
        languages = NPM_AST_GREP_LANGUAGES
    elif profile == "python":
        languages = PYTHON_AST_GREP_LANGUAGES
    else:
        raise ValueError("unsupported reachability profile")
    target_regex = "(?:" + "|".join(re.escape(target) for target in target_identifiers) + ")"
    rules: list[str] = []
    for language in languages:
        rule_lines = [f"  kind: {operation}"]
        if operation in {"import_statement", "import_from_statement"}:
            rule_lines = [
                "  all:",
                f"    - kind: {operation}",
                f"    - regex: {json.dumps(target_regex)}",
            ]
        rules.append(
            "\n".join(
                (
                    f"id: {profile}-{language.casefold()}-{operation}",
                    f"language: {language}",
                    "rule:",
                    *rule_lines,
                    "severity: info",
                    "message: Application-owned structural operation.",
                )
            )
        )
    return "\n---\n".join(rules)


def _check_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise TimeoutError("analyzer deadline exceeded")


def _read_regular_file(path: Path, *, deadline: float, max_bytes: int) -> bytes:
    if max_bytes < 0:
        raise ValueError("analyzer input byte limit exceeded")
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("analyzer input is not a regular file")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError("analyzer input changed during open")
        chunks: list[bytes] = []
        total = 0
        while True:
            _check_deadline(deadline)
            chunk = os.read(descriptor, min(64 * 1024, max_bytes - total + 1))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes:
                raise ValueError("analyzer input byte limit exceeded")
        after = os.fstat(descriptor)
        if (after.st_dev, after.st_ino) != (
            before.st_dev,
            before.st_ino,
        ) or after.st_size != before.st_size:
            raise ValueError("analyzer input changed during read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _capture_bounded(
    process: subprocess.Popen[bytes],
    *,
    deadline: float,
    max_output_bytes: int,
    max_stderr_bytes: int,
) -> tuple[bytes, bytes]:
    if process.stdout is None or process.stderr is None:
        raise ValueError("analyzer pipes are unavailable")
    stdout = bytearray()
    stderr = bytearray()
    overflow = threading.Event()

    def drain(stream: BinaryIO, target: bytearray, limit: int) -> None:
        while True:
            chunk = stream.read(min(64 * 1024, limit - len(target) + 1))
            if not chunk:
                return
            target.extend(chunk)
            if len(target) > limit:
                overflow.set()
                return

    threads = (
        threading.Thread(target=drain, args=(process.stdout, stdout, max_output_bytes)),
        threading.Thread(target=drain, args=(process.stderr, stderr, max_stderr_bytes)),
    )
    for thread in threads:
        thread.start()
    try:
        while process.poll() is None:
            if overflow.is_set():
                _terminate(process)
                raise ValueError("analyzer output limit exceeded")
            _check_deadline(deadline)
            time.sleep(0.01)
        for thread in threads:
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
        if any(thread.is_alive() for thread in threads):
            _terminate(process)
            raise TimeoutError("analyzer output drain exceeded deadline")
        if overflow.is_set():
            raise ValueError("analyzer output limit exceeded")
        return bytes(stdout), bytes(stderr)
    except (TimeoutError, ValueError):
        _terminate(process)
        raise


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "posix":
        os.killpg(process.pid, signal.SIGTERM)
    else:
        process.terminate()
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=1)
