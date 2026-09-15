"""Bounded ast-grep structural evidence over immutable repository snapshots."""

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
from collections.abc import Sequence
from pathlib import Path
from typing import BinaryIO, Literal, Protocol

from pydantic import TypeAdapter, ValidationError

from dependabot_validator_grunt.agentic import path_is_denied
from dependabot_validator_grunt.models import (
    ReachabilityEvidence,
    ReachabilityFinding,
    RepositoryFact,
)

AST_GREP_DISTRIBUTION = "ast-grep-cli"
AST_GREP_VERSION = "0.45.3"
ANALYZER_SUFFIXES = {
    ".cjs": "javascript",
    ".js": "javascript",
    ".jsx": "jsx",
    ".mjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
}
IDENTIFIER = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")


class ReachabilityRunner(Protocol):
    """External analyzer seam used by offline fakes and the real subprocess."""

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
    ) -> ReachabilityEvidence: ...


class AstGrepRunner:
    """Run the pinned ast-grep binary with fixed structural operations."""

    def __init__(self, executable: Path | None = None) -> None:
        scripts = Path(sysconfig.get_path("scripts"))
        self.executable = (executable or scripts / "ast-grep").resolve()

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
        deadline = time.monotonic() + wall_seconds
        try:
            unavailable = self._availability(snapshot_id, package_name, deadline)
        except (OSError, subprocess.SubprocessError, TimeoutError):
            unavailable = self._unavailable(
                snapshot_id,
                package_name,
                "unavailable",
                "The pinned ast-grep runtime could not be verified within trusted limits.",
            )
        if unavailable is not None:
            return unavailable
        with tempfile.TemporaryDirectory(prefix="dependabot-validator-ast-grep-") as directory:
            staging = Path(directory)
            try:
                files, input_bytes, sources, coverage_complete = self._stage(
                    root,
                    staging,
                    deadline=deadline,
                    max_files=max_files,
                    max_input_bytes=max_input_bytes,
                )
                findings, findings_complete = self._scan(
                    staging,
                    files,
                    sources,
                    package_name=package_name,
                    deadline=deadline,
                    max_output_bytes=max_output_bytes,
                    max_stderr_bytes=max_stderr_bytes,
                    max_findings=max_findings,
                )
                self._verify_sources(root, sources, deadline)
            except (OSError, ValueError, subprocess.SubprocessError, ValidationError):
                return ReachabilityEvidence(
                    snapshot_id=snapshot_id,
                    package_name=package_name,
                    engine="ast-grep",
                    engine_version=AST_GREP_VERSION,
                    status="incomplete",
                    scanned_files=0,
                    scanned_bytes=0,
                    limitations=(
                        "Structural analysis did not complete within trusted limits.",
                        "No result is not evidence of non-reachability.",
                    ),
                )
        return ReachabilityEvidence(
            snapshot_id=snapshot_id,
            package_name=package_name,
            engine="ast-grep",
            engine_version=AST_GREP_VERSION,
            status=(
                "syntax_usage_found"
                if findings
                else "no_syntax_match"
                if coverage_complete
                else "incomplete"
            ),
            scanned_files=sum(len(paths) for paths in files.values()),
            scanned_bytes=input_bytes,
            findings=tuple(findings),
            limitations=(
                "Results are syntactic evidence, not a call graph or exploitability proof.",
                "Dynamic loading, computed properties, generated code, and dependency-internal "
                "calls may be missed.",
                *(
                    (
                        "Analyzer coverage is partial because the configured source staging "
                        "limit was reached.",
                    )
                    if not coverage_complete
                    else ()
                ),
                *(
                    (
                        "Analyzer findings were capped or later operations stopped at a "
                        "configured limit.",
                    )
                    if not findings_complete
                    else ()
                ),
            ),
        )

    def _availability(
        self,
        snapshot_id: str,
        package_name: str,
        deadline: float,
    ) -> ReachabilityEvidence | None:
        try:
            package_version = importlib.metadata.version(AST_GREP_DISTRIBUTION)
        except importlib.metadata.PackageNotFoundError:
            package_version = ""
        if (
            package_version != AST_GREP_VERSION
            or not self.executable.is_file()
            or not os.access(self.executable, os.X_OK)
        ):
            return self._unavailable(
                snapshot_id,
                package_name,
                package_version or "unavailable",
                "The pinned ast-grep runtime is unavailable.",
            )
        process = subprocess.Popen(
            [str(self.executable), "--version"],
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
            return self._unavailable(
                snapshot_id,
                package_name,
                version_text or "invalid",
                "The ast-grep runtime version did not match the trusted pin.",
            )
        return None

    @staticmethod
    def _unavailable(
        snapshot_id: str,
        package_name: str,
        engine_version: str,
        limitation: str,
    ) -> ReachabilityEvidence:
        return ReachabilityEvidence(
            snapshot_id=snapshot_id,
            package_name=package_name,
            engine="ast-grep",
            engine_version=engine_version,
            status="unavailable",
            scanned_files=0,
            scanned_bytes=0,
            limitations=(limitation,),
        )

    def _stage(
        self,
        root: Path,
        staging: Path,
        *,
        deadline: float,
        max_files: int,
        max_input_bytes: int,
    ) -> tuple[dict[str, list[str]], int, dict[str, bytes], bool]:
        grouped: dict[str, list[str]] = {}
        sources: dict[str, bytes] = {}
        total = 0
        count = 0
        coverage_complete = True
        for path in sorted(root.rglob("*")):
            _check_deadline(deadline)
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            language = ANALYZER_SUFFIXES.get(path.suffix.casefold())
            if language is None or path_is_denied(relative):
                continue
            if count >= max_files:
                coverage_complete = False
                break
            metadata = path.lstat()
            if metadata.st_size > max_input_bytes - total:
                coverage_complete = False
                continue
            data = _read_regular_file(
                path,
                deadline=deadline,
                max_bytes=max_input_bytes - total,
            )
            try:
                data.decode("utf-8")
            except UnicodeDecodeError:
                coverage_complete = False
                continue
            count += 1
            total += len(data)
            if total > max_input_bytes:
                raise ValueError("analyzer input byte limit exceeded")
            target = staging.joinpath(*Path(relative).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            sources[relative] = data
            grouped.setdefault(language, []).append(relative)
        return grouped, total, sources, coverage_complete

    @staticmethod
    def _verify_sources(root: Path, sources: dict[str, bytes], deadline: float) -> None:
        for relative, staged in sources.items():
            current = _read_regular_file(
                root.joinpath(*Path(relative).parts),
                deadline=deadline,
                max_bytes=len(staged),
            )
            if current != staged:
                raise ValueError("analyzer input changed during analysis")

    def _scan(
        self,
        staging: Path,
        files: dict[str, list[str]],
        sources: dict[str, bytes],
        *,
        package_name: str,
        deadline: float,
        max_output_bytes: int,
        max_stderr_bytes: int,
        max_findings: int,
    ) -> tuple[list[ReachabilityFinding], bool]:
        findings: list[ReachabilityFinding] = []
        aliases: dict[str, set[str]] = {}
        calls: dict[str, list[dict[str, object]]] = {}
        remaining_output = max_output_bytes
        remaining_stderr = max_stderr_bytes

        def result(complete: bool) -> tuple[list[ReachabilityFinding], bool]:
            unique: dict[tuple[str, int, str, str], ReachabilityFinding] = {}
            for finding in findings:
                key = (
                    finding.citation.path,
                    finding.citation.line,
                    finding.citation.digest,
                    finding.kind,
                )
                unique[key] = finding
            unique_findings = list(unique.values())
            return (
                unique_findings[:max_findings],
                complete and len(unique_findings) <= max_findings,
            )

        for language, paths in files.items():
            try:
                imports, used_out, used_err = self._run(
                    staging,
                    ["--kind", "import_statement", "--lang", language],
                    paths,
                    deadline=deadline,
                    max_output_bytes=remaining_output,
                    max_stderr_bytes=remaining_stderr,
                )
            except (OSError, ValueError, subprocess.SubprocessError):
                if findings:
                    return result(False)
                raise
            remaining_output -= used_out
            remaining_stderr -= used_err
            for raw in imports:
                text = TypeAdapter(str).validate_python(raw.get("text"))
                if not _contains_package_literal(text, package_name):
                    continue
                relative = TypeAdapter(str).validate_python(raw.get("file"))
                alias = _import_binding(text)
                if alias is not None:
                    aliases.setdefault(relative, set()).add(alias)
                findings.append(self._finding(sources, raw, kind="import", binding=alias))
            if len(findings) >= max_findings:
                return result(False)
            try:
                language_calls, used_out, used_err = self._run(
                    staging,
                    ["--kind", "call_expression", "--lang", language],
                    paths,
                    deadline=deadline,
                    max_output_bytes=remaining_output,
                    max_stderr_bytes=remaining_stderr,
                )
            except (OSError, ValueError, subprocess.SubprocessError):
                if findings:
                    return result(False)
                raise
            remaining_output -= used_out
            remaining_stderr -= used_err
            for raw in language_calls:
                relative = TypeAdapter(str).validate_python(raw.get("file"))
                calls.setdefault(relative, []).append(raw)
                text = TypeAdapter(str).validate_python(raw.get("text"))
                kind: Literal["require", "dynamic_import"] | None = None
                if re.match(r"^require\s*(?:/\*.*?\*/\s*)?\(", text, re.DOTALL) and (
                    _contains_package_literal(text, package_name)
                ):
                    kind = "require"
                elif re.match(r"^import\s*(?:/\*.*?\*/\s*)?\(", text, re.DOTALL) and (
                    _contains_package_literal(text, package_name)
                ):
                    kind = "dynamic_import"
                if kind is None:
                    continue
                alias = _require_binding(
                    TypeAdapter(str).validate_python(raw.get("lines")),
                    text,
                )
                if alias is not None:
                    aliases.setdefault(relative, set()).add(alias)
                findings.append(self._finding(sources, raw, kind=kind, binding=alias))
            if len(findings) >= max_findings:
                return result(False)
        for relative, file_aliases in aliases.items():
            for alias in sorted(file_aliases):
                if not IDENTIFIER.fullmatch(alias):
                    continue
                bound_call = re.compile(rf"^{re.escape(alias)}(?:\.[A-Za-z_$][A-Za-z0-9_$]*)?\s*\(")
                for raw in calls.get(relative, []):
                    text = TypeAdapter(str).validate_python(raw.get("text"))
                    if bound_call.match(text):
                        findings.append(
                            self._finding(sources, raw, kind="bound_call", binding=alias)
                        )
        return result(True)

    def _run(
        self,
        staging: Path,
        operation: list[str],
        paths: Sequence[str],
        *,
        deadline: float,
        max_output_bytes: int,
        max_stderr_bytes: int,
    ) -> tuple[list[dict[str, object]], int, int]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("analyzer deadline exceeded")
        command = [
            str(self.executable),
            "run",
            *operation,
            "--json=stream",
            "--color",
            "never",
            "--threads",
            "1",
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
        output_size = len(stdout)
        stderr_size = len(stderr)
        raw_output = stdout.decode("utf-8")
        objects: list[dict[str, object]] = []
        for line in raw_output.splitlines():
            objects.append(TypeAdapter(dict[str, object]).validate_python(json.loads(line)))
        return objects, output_size, stderr_size

    def _finding(
        self,
        sources: dict[str, bytes],
        raw: dict[str, object],
        *,
        kind: Literal["import", "require", "dynamic_import", "bound_call"],
        binding: str | None,
    ) -> ReachabilityFinding:
        relative = TypeAdapter(str).validate_python(raw.get("file"))
        if Path(relative).is_absolute() or ".." in Path(relative).parts or path_is_denied(relative):
            raise ValueError("analyzer returned an invalid path")
        data = sources.get(relative)
        if data is None:
            raise ValueError("analyzer citation target is invalid")
        range_data = TypeAdapter(dict[str, object]).validate_python(raw.get("range"))
        start = TypeAdapter(dict[str, object]).validate_python(range_data.get("start"))
        byte_offsets = TypeAdapter(dict[str, object]).validate_python(range_data.get("byteOffset"))
        start_byte = TypeAdapter(int).validate_python(byte_offsets.get("start"))
        end_byte = TypeAdapter(int).validate_python(byte_offsets.get("end"))
        if start_byte < 0 or end_byte < start_byte or end_byte > len(data):
            raise ValueError("analyzer returned an invalid byte range")
        matched = TypeAdapter(str).validate_python(raw.get("text")).encode()
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
            citation=citation,
            binding=binding,
        )


def _contains_package_literal(text: str, package_name: str) -> bool:
    literal = re.compile(rf"""(?P<quote>["']){re.escape(package_name)}(?:/[^"']+)?(?P=quote)""")
    return literal.search(text) is not None


def _import_binding(text: str) -> str | None:
    match = re.match(r"\s*import\s+(?P<binding>[A-Za-z_$][A-Za-z0-9_$]*)\s+from\b", text)
    if match:
        return match.group("binding")
    namespace = re.match(
        r"\s*import\s+\*\s+as\s+(?P<binding>[A-Za-z_$][A-Za-z0-9_$]*)\s+from\b",
        text,
    )
    return namespace.group("binding") if namespace else None


def _require_binding(line: str, expression: str) -> str | None:
    match = re.search(
        rf"\b(?:const|let|var)\s+(?P<binding>[A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*"
        rf"{re.escape(expression)}",
        line,
    )
    return match.group("binding") if match else None


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
