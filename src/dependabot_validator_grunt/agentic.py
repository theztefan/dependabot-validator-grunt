"""Bounded repository tools and untrusted agent-output validation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import unicodedata
from collections import Counter
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from pydantic import TypeAdapter, ValidationError

from dependabot_validator_grunt.models import (
    NPM_REACHABILITY_OPERATIONS,
    PYTHON_REACHABILITY_OPERATIONS,
    AgentFinding,
    AgentTask,
    ReachabilityEvidence,
    ReachabilityProfile,
    RepositoryFact,
    RepositoryReferenceEvidence,
    RepositoryReferenceInsufficiencyCode,
    RepositoryReferenceInsufficiencyReason,
    RepositoryReferenceStatus,
    canonical_json,
    validate_safe_identifier,
)

if TYPE_CHECKING:
    from dependabot_validator_grunt.reachability import ReachabilityRunner

DENIED_NAMES = {
    ".git",
    ".gitconfig",
    ".gitmodules",
    ".mcp.json",
    "copilot-instructions.md",
    "claude.md",
    "agents.md",
    ".npmrc",
    ".netrc",
    ".ssh",
    ".copilot",
}

KNOWN_BINARY_SUFFIXES = {
    ".7z",
    ".avi",
    ".bmp",
    ".class",
    ".dll",
    ".dylib",
    ".eot",
    ".exe",
    ".gif",
    ".gz",
    ".ico",
    ".jar",
    ".jpeg",
    ".jpg",
    ".mov",
    ".mp3",
    ".mp4",
    ".o",
    ".otf",
    ".pdf",
    ".png",
    ".so",
    ".tar",
    ".ttf",
    ".wav",
    ".webm",
    ".webp",
    ".woff",
    ".woff2",
    ".zip",
}
NPM_REFERENCE_METADATA_NAMES = {
    "package-lock.json",
    "npm-shrinkwrap.json",
    "pnpm-lock.yaml",
    "yarn.lock",
}
NPM_PACKAGE_DECLARATION_FIELDS = {
    "name",
    "dependencies",
    "devDependencies",
    "optionalDependencies",
    "peerDependencies",
    "peerDependenciesMeta",
    "bundledDependencies",
    "bundleDependencies",
    "overrides",
}
REFERENCE_INSUFFICIENCY_ORDER: tuple[RepositoryReferenceInsufficiencyCode, ...] = (
    "snapshot_excluded_path",
    "lstat_failed",
    "proof_budget_exceeded",
    "read_failed",
    "size_changed",
    "nul_containing_candidate",
    "undecodable_candidate",
    "invalid_package_json",
    "no_scanned_text",
)


def path_is_denied(relative: str) -> bool:
    """Return whether a repository-relative path belongs to a denied class."""
    parts = tuple(
        unicodedata.normalize("NFKC", part).casefold() for part in PurePosixPath(relative).parts
    )
    for index, part in enumerate(parts):
        if part == ".github" and (
            index + 1 == len(parts) or parts[index + 1] not in {"actions", "workflows"}
        ):
            return True
    return any(
        part in DENIED_NAMES
        or part == ".claude"
        or part == "mcp.json"
        or part.startswith((".env", ".yarnrc"))
        or part.endswith((".pem", ".key"))
        or part.startswith("id_")
        for part in parts
    )


class RepositoryTools:
    """Read-only, bounded tools over a synthetic repository snapshot."""

    def __init__(
        self,
        root: Path,
        *,
        max_read_bytes: int = 2 * 1024 * 1024,
        max_results: int = 200,
        max_session_bytes: int = 32 * 1024 * 1024,
        max_proof_scan_bytes: int = 64 * 1024 * 1024,
        reachability_runner: ReachabilityRunner | None = None,
        analyzer_wall_seconds: int = 120,
        max_analyzer_files: int = 20_000,
        max_analyzer_input_bytes: int = 128 * 1024 * 1024,
        max_analyzer_batch_files: int = 1_000,
        max_analyzer_batch_bytes: int = 16 * 1024 * 1024,
        max_analyzer_output_bytes: int = 4 * 1024 * 1024,
        max_analyzer_stderr_bytes: int = 256 * 1024,
        max_analyzer_findings: int = 500,
        coverage_excluded_path_count: int = 0,
    ) -> None:
        self.root = root.resolve(strict=True)
        self.max_read_bytes = max_read_bytes
        self.max_results = max_results
        self.max_session_bytes = max_session_bytes
        self.max_proof_scan_bytes = max_proof_scan_bytes
        self.reachability_runner = reachability_runner
        self.analyzer_wall_seconds = analyzer_wall_seconds
        self.max_analyzer_files = max_analyzer_files
        self.max_analyzer_input_bytes = max_analyzer_input_bytes
        self.max_analyzer_batch_files = max_analyzer_batch_files
        self.max_analyzer_batch_bytes = max_analyzer_batch_bytes
        self.max_analyzer_output_bytes = max_analyzer_output_bytes
        self.max_analyzer_stderr_bytes = max_analyzer_stderr_bytes
        self.max_analyzer_findings = max_analyzer_findings
        self.coverage_excluded_path_count = coverage_excluded_path_count
        self._used_bytes = 0
        self._text_cache: dict[Path, str] = {}
        self.observations: dict[tuple[str, int, str], RepositoryFact] = {}
        self.reachability_invocation_count = 0
        self.reachability_evidence: ReachabilityEvidence | None = None
        self._reference_file_digests: dict[Path, bytes] = {}

    def analyze_reachability(
        self,
        *,
        snapshot_id: str,
        package_name: str,
        profile: ReachabilityProfile,
        analysis_root: str = "",
        target_identifiers: Sequence[str] | None = None,
    ) -> ReachabilityEvidence:
        """Run the task-bound structural analyzer and register its citations."""
        if isinstance(target_identifiers, str):
            raise ValueError("target identifiers must be a sequence of identifiers")
        selected_targets = (
            (package_name,) if target_identifiers is None else tuple(target_identifiers)
        )
        if not selected_targets:
            raise ValueError("at least one analyzer target identifier is required")
        targets = tuple(
            dict.fromkeys(validate_safe_identifier(value) for value in selected_targets)
        )
        self.reachability_invocation_count += 1
        if self.reachability_evidence is not None:
            if (
                self.reachability_evidence.snapshot_id != snapshot_id
                or self.reachability_evidence.package_name != package_name
                or self.reachability_evidence.target_identifiers != targets
                or self.reachability_evidence.profile != profile
                or self.reachability_evidence.analysis_root != analysis_root
            ):
                raise ValueError("cached reachability evidence identity mismatch")
            return self.reachability_evidence
        if self.reachability_runner is None:
            evidence = ReachabilityEvidence(
                snapshot_id=snapshot_id,
                package_name=package_name,
                target_identifiers=targets,
                analysis_root=analysis_root,
                profile=profile,
                engine="ast-grep",
                engine_version="unavailable",
                status="unavailable",
                candidate_files=0,
                staged_files=0,
                skipped_files=0,
                staged_bytes=0,
                operations=(
                    NPM_REACHABILITY_OPERATIONS
                    if profile == "npm"
                    else PYTHON_REACHABILITY_OPERATIONS
                ),
                completed_operations=(),
                limitations=(
                    "The structural analyzer is not configured.",
                    "Analyzer unavailability is not evidence of non-reachability.",
                ),
            )
        else:
            evidence = self.reachability_runner.analyze(
                self.root,
                snapshot_id=snapshot_id,
                package_name=package_name,
                profile=profile,
                analysis_root=analysis_root,
                target_identifiers=targets,
                wall_seconds=self.analyzer_wall_seconds,
                max_files=self.max_analyzer_files,
                max_input_bytes=self.max_analyzer_input_bytes,
                max_batch_files=self.max_analyzer_batch_files,
                max_batch_bytes=self.max_analyzer_batch_bytes,
                max_output_bytes=self.max_analyzer_output_bytes,
                max_stderr_bytes=self.max_analyzer_stderr_bytes,
                max_findings=self.max_analyzer_findings,
            )
        if (
            evidence.snapshot_id != snapshot_id
            or evidence.package_name != package_name
            or evidence.target_identifiers != targets
            or evidence.profile != profile
            or evidence.analysis_root != analysis_root
        ):
            raise ValueError("reachability evidence identity mismatch")
        self.reachability_evidence = evidence
        for finding in evidence.findings:
            fact = finding.citation
            self.observations[(fact.path, fact.line, fact.digest)] = fact
        return evidence

    def _resolve(self, relative: str) -> Path:
        candidate = PurePosixPath(relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("path must be relative and cannot contain '..'")
        if path_is_denied(relative):
            raise ValueError("path is denied")
        unresolved = self.root / Path(*candidate.parts)
        current = self.root
        for part in candidate.parts:
            current /= part
            if current.is_symlink():
                raise ValueError("symlinks are denied")
        path = unresolved.resolve(strict=True)
        if path == self.root or self.root not in path.parents:
            raise ValueError("path escapes repository snapshot")
        if path_is_denied(path.relative_to(self.root).as_posix()):
            raise ValueError("resolved path is denied")
        return path

    def _text(self, path: Path) -> str:
        cached = self._text_cache.get(path)
        if cached is not None:
            return cached
        with path.open("rb") as file:
            data = file.read(self.max_read_bytes + 1)
        if len(data) > self.max_read_bytes:
            raise ValueError("file exceeds read limit")
        if b"\0" in data:
            raise ValueError("binary files are denied")
        next_used_bytes = self._used_bytes + len(data)
        if next_used_bytes > self.max_session_bytes:
            raise ValueError("session byte limit exceeded")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("binary files are denied") from error
        self._used_bytes = next_used_bytes
        self._text_cache[path] = text
        return text

    def _files(self, directory: Path) -> list[str]:
        results: list[str] = []
        for path in sorted(directory.rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            rel = path.relative_to(self.root).as_posix()
            try:
                self._resolve(rel)
            except ValueError:
                continue
            results.append(rel)
        return results

    def list_files(self, relative: str = ".") -> list[str]:
        """List files under a bounded directory."""
        directory = self.root if relative == "." else self._resolve(relative)
        if not directory.is_dir():
            raise ValueError("list target must be a directory")
        results = self._files(directory)
        return results[: self.max_results]

    def read_file(self, relative: str) -> str:
        """Read one bounded UTF-8 text file."""
        path = self._resolve(relative)
        if not path.is_file():
            raise ValueError("read target must be a file")
        return self._text(path)

    def search(self, query: str, relative: str = ".") -> list[RepositoryFact]:
        """Search literal text and record digest-bound observations."""
        if not query:
            raise ValueError("search query cannot be empty")
        pattern = re.compile(re.escape(query), re.IGNORECASE)
        results: list[RepositoryFact] = []
        directory = self.root if relative == "." else self._resolve(relative)
        if not directory.is_dir():
            raise ValueError("search target must be a directory")
        paths = self._files(directory)
        for rel in paths:
            try:
                text = self._text(self._resolve(rel))
            except ValueError as error:
                if str(error) in {"binary files are denied", "file exceeds read limit"}:
                    continue
                raise
            for line_number, line in enumerate(text.splitlines(), 1):
                if not pattern.search(line):
                    continue
                if len(results) >= self.max_results:
                    return results
                fact = RepositoryFact(
                    path=rel,
                    line=line_number,
                    digest=hashlib.sha256(line.encode()).hexdigest(),
                    excerpt=line[:500],
                )
                self.observations[(fact.path, fact.line, fact.digest)] = fact
                results.append(fact)
                if len(results) >= self.max_results:
                    return results
        return results

    def collect_reference_evidence(self, target_identifier: str) -> RepositoryReferenceEvidence:
        """Collect bounded aggregate reference evidence without exposing repository content."""
        pattern = re.compile(re.escape(target_identifier), re.IGNORECASE)
        candidates: list[tuple[Path, os.stat_result, bool]] = []
        candidate_count = 0
        metadata_excluded_count = 0
        binary_excluded_count = 0
        scanned_bytes = 0
        reason_counts: Counter[RepositoryReferenceInsufficiencyCode] = Counter()
        if self.coverage_excluded_path_count:
            reason_counts["snapshot_excluded_path"] = self.coverage_excluded_path_count

        try:
            paths = sorted(self.root.rglob("*"))
        except OSError:
            paths = []
            reason_counts["lstat_failed"] += 1

        for path in paths:
            relative = path.relative_to(self.root).as_posix()
            if path_is_denied(relative):
                continue
            try:
                metadata = path.lstat()
            except OSError:
                reason_counts["lstat_failed"] += 1
                continue
            if not stat.S_ISREG(metadata.st_mode):
                continue
            if path.name in NPM_REFERENCE_METADATA_NAMES:
                metadata_excluded_count += 1
                continue
            if path.suffix.casefold() in KNOWN_BINARY_SUFFIXES:
                binary_excluded_count += 1
                continue
            candidate_count += 1
            scanned_bytes += metadata.st_size
            candidates.append((path, metadata, path.name == "package.json"))

        if scanned_bytes > self.max_proof_scan_bytes:
            reason_counts["proof_budget_exceeded"] += 1
            return self._reference_evidence(
                target_identifier=target_identifier,
                status="insufficient",
                candidate_count=candidate_count,
                scanned_count=0,
                metadata_excluded_count=metadata_excluded_count,
                binary_excluded_count=binary_excluded_count,
                scanned_bytes=scanned_bytes,
                reference_count=0,
                reason_counts=reason_counts,
            )

        scanned_count = 0
        self._reference_file_digests = {}
        for path, expected, package_manifest in candidates:
            try:
                flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                descriptor = os.open(path, flags)
                try:
                    opened = os.fstat(descriptor)
                    if (
                        not stat.S_ISREG(opened.st_mode)
                        or (opened.st_dev, opened.st_ino) != (expected.st_dev, expected.st_ino)
                        or opened.st_size != expected.st_size
                        or opened.st_mtime_ns != expected.st_mtime_ns
                    ):
                        reason_counts["size_changed"] += 1
                        continue
                    with os.fdopen(descriptor, "rb", closefd=False) as file:
                        data = file.read(expected.st_size + 1)
                    closed = os.fstat(descriptor)
                    if (
                        (closed.st_dev, closed.st_ino) != (expected.st_dev, expected.st_ino)
                        or closed.st_size != expected.st_size
                        or closed.st_mtime_ns != expected.st_mtime_ns
                    ):
                        reason_counts["size_changed"] += 1
                        continue
                finally:
                    os.close(descriptor)
            except OSError:
                reason_counts["read_failed"] += 1
                continue
            if len(data) != expected.st_size:
                reason_counts["size_changed"] += 1
                continue
            if b"\0" in data:
                reason_counts["nul_containing_candidate"] += 1
                continue
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                reason_counts["undecodable_candidate"] += 1
                continue
            if package_manifest:
                try:
                    manifest = TypeAdapter(dict[str, object]).validate_python(json.loads(text))
                    text = canonical_json(
                        {
                            key: value
                            for key, value in manifest.items()
                            if key not in NPM_PACKAGE_DECLARATION_FIELDS
                        }
                    )
                except (json.JSONDecodeError, ValidationError, ValueError):
                    reason_counts["invalid_package_json"] += 1
                    continue
            scanned_count += 1
            self._reference_file_digests[path] = hashlib.sha256(data).digest()
            reference_count = len(pattern.findall(text))
            if reference_count:
                return self._reference_evidence(
                    target_identifier=target_identifier,
                    status="reference_found",
                    candidate_count=candidate_count,
                    scanned_count=scanned_count,
                    metadata_excluded_count=metadata_excluded_count,
                    binary_excluded_count=binary_excluded_count,
                    scanned_bytes=scanned_bytes,
                    reference_count=reference_count,
                    reason_counts=Counter(),
                )

        if scanned_count == 0:
            reason_counts["no_scanned_text"] += 1
        return self._reference_evidence(
            target_identifier=target_identifier,
            status="insufficient" if reason_counts else "sufficient_absence",
            candidate_count=candidate_count,
            scanned_count=scanned_count,
            metadata_excluded_count=metadata_excluded_count,
            binary_excluded_count=binary_excluded_count,
            scanned_bytes=scanned_bytes,
            reference_count=0,
            reason_counts=reason_counts,
        )

    def validate_reference_snapshot(self) -> None:
        """Re-prove that files supporting aggregate reference evidence did not drift."""
        for path, expected_digest in self._reference_file_digests.items():
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags)
            try:
                opened = os.fstat(descriptor)
                if not stat.S_ISREG(opened.st_mode):
                    raise ValueError("reference evidence snapshot changed")
                digest = hashlib.sha256()
                with os.fdopen(descriptor, "rb", closefd=False) as file:
                    for chunk in iter(lambda: file.read(64 * 1024), b""):
                        digest.update(chunk)
                if digest.digest() != expected_digest:
                    raise ValueError("reference evidence snapshot changed")
            finally:
                os.close(descriptor)

    def _reference_evidence(
        self,
        *,
        target_identifier: str,
        status: RepositoryReferenceStatus,
        candidate_count: int,
        scanned_count: int,
        metadata_excluded_count: int,
        binary_excluded_count: int,
        scanned_bytes: int,
        reference_count: int,
        reason_counts: Counter[RepositoryReferenceInsufficiencyCode],
    ) -> RepositoryReferenceEvidence:
        reasons = tuple(
            RepositoryReferenceInsufficiencyReason(
                code=code,
                count=reason_counts[code],
            )
            for code in REFERENCE_INSUFFICIENCY_ORDER
            if reason_counts[code]
        )
        return RepositoryReferenceEvidence(
            target_identifier=target_identifier,
            status=status,
            candidate_count=candidate_count,
            scanned_count=scanned_count,
            metadata_excluded_count=metadata_excluded_count,
            binary_excluded_count=binary_excluded_count,
            scanned_bytes=scanned_bytes,
            max_scan_bytes=self.max_proof_scan_bytes,
            reference_count=reference_count,
            insufficiency_reasons=reasons,
        )


def validate_finding(
    raw: dict[str, object], task: AgentTask, tools: RepositoryTools
) -> AgentFinding:
    """Validate identity bindings, permitted shape, and repository citations."""
    finding = AgentFinding.model_validate(raw)
    expected = (
        task.workflow_mode,
        task.correlation_id,
        task.repository_id,
        task.alert_number,
        task.request_id,
        task.snapshot_id,
        task.policy_digest,
    )
    actual = (
        finding.workflow_mode,
        finding.correlation_id,
        finding.repository_id,
        finding.alert_number,
        finding.request_id,
        finding.snapshot_id,
        finding.policy_digest,
    )
    if actual != expected:
        raise ValueError("agent finding identity does not match assigned task")
    if (
        not finding.insufficient_context
        and not finding.injection_detected
        and not task.permits(
            finding.proposed_recommendation,
            finding.policy_reason_code,
        )
    ):
        raise ValueError("agent finding recommendation and reason code are not permitted")
    validated_citations: list[RepositoryFact] = []
    for index, citation in enumerate(finding.citations):
        observed = tools.observations.get((citation.path, citation.line, citation.digest))
        if observed is None:
            if finding.proposed_recommendation == "human_review":
                continue
            raise ValueError(f"fabricated or stale citation at index {index}")
        validated_citations.append(observed)
    if tuple(validated_citations) != finding.citations:
        return finding.model_copy(update={"citations": tuple(validated_citations)})
    return finding
