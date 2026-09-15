"""Validated atomic local workflow artifacts."""

from __future__ import annotations

import html
import os
import re
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel

from dependabot_validator_grunt.models import (
    DismissalDecision,
    Report,
    TriageDecision,
    canonical_json,
)


def _remove_exact_file(path: Path) -> OSError | None:
    try:
        path.unlink()
    except FileNotFoundError:
        return None
    except OSError as error:
        return error
    return None


def _raise_cleanup_failure(
    operation_error: OSError,
    cleanup_errors: list[tuple[Path, OSError]],
) -> None:
    if not cleanup_errors:
        return
    details = "; ".join(f"{path}: {error}" for path, error in cleanup_errors)
    raise OSError(f"{operation_error}; exact-file cleanup failed: {details}") from operation_error


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    except OSError as error:
        cleanup_error = _remove_exact_file(temporary)
        _raise_cleanup_failure(
            error,
            [] if cleanup_error is None else [(temporary, cleanup_error)],
        )
        raise


def _json_content(value: BaseModel | Mapping[str, object]) -> str:
    data = value.model_dump(mode="json") if isinstance(value, BaseModel) else dict(value)
    return canonical_json(data) + "\n"


def write_json(path: Path, value: BaseModel | Mapping[str, object]) -> None:
    """Write canonical JSON atomically."""
    _atomic_write(path, _json_content(value))


def render_markdown(report: Report) -> str:
    """Render Markdown only from validated report data."""
    result = report.result
    if result.result_kind == "dismissal_decision":
        outcome = result.recommendation
    elif result.result_kind == "dismissal_lifecycle":
        outcome = f"lifecycle: {result.lifecycle}"
    else:
        outcome = f"{result.assessment} / {result.recommended_action}"
    untrusted = [report.alert.summary]
    if report.request is not None:
        untrusted.append(report.request.justification)
    if isinstance(result, (DismissalDecision, TriageDecision)):
        untrusted.extend(result.missing_evidence)
        untrusted.extend(finding.claim for finding in result.agent_findings)
        untrusted.extend(finding.uncertainty for finding in result.agent_findings)
        untrusted.extend(
            citation.path for finding in result.agent_findings for citation in finding.citations
        )
    longest = max(
        (len(match) for text in untrusted for match in re.findall(r"`+", text)),
        default=0,
    )
    fence = "`" * max(3, longest + 1)

    def fenced(text: str) -> str:
        return f"{fence}text\n{html.escape(text)}\n{fence}"

    def inline(text: str) -> str:
        return html.escape(text).replace("`", "&#96;").replace("\r", " ").replace("\n", " ")

    details: list[str] = []
    if isinstance(result, (DismissalDecision, TriageDecision)):
        details.extend(f"- Proof: {html.escape(proof.summary)}" for proof in result.proofs)
        details.extend(f"- Missing evidence:\n\n{fenced(item)}" for item in result.missing_evidence)
        for finding in result.agent_findings:
            details.append(f"- Agent finding:\n\n{fenced(finding.claim)}")
            if finding.uncertainty:
                details.append(f"- Agent uncertainty:\n\n{fenced(finding.uncertainty)}")
            details.extend(
                f"- Citation path:\n\n{fenced(citation.path)}\n\n  Line: {citation.line}"
                for citation in finding.citations
            )
    validated_details = "\n".join(details) or "- None"
    title = (
        "# Dependabot dismissal review"
        if report.workflow_mode == "dismissal"
        else "# Dependabot alert triage"
    )
    request_section = ""
    if report.request is not None:
        request_section = (
            "## Request facts\n\n"
            f"- ID: `{inline(report.request.request_id)}`\n"
            f"- Reason: `{inline(report.request.reason)}`\n"
            f"- Status: `{report.request.status}`\n\n"
            f"- Provenance: `{report.request.provenance}`\n\n"
            "## Request justification\n\n"
            f"{fenced(report.request.justification)}\n\n"
        )
    triage_section = ""
    if result.result_kind == "triage_decision":
        triage_section = (
            "## Triage decision\n\n"
            f"- Priority: `{result.priority}`\n"
            f"- Assessment: `{result.assessment}`\n"
            f"- Recommended action: `{result.recommended_action}`\n\n"
        )
    lifecycle_section = ""
    if result.result_kind == "dismissal_lifecycle":
        lifecycle_section = (
            f"## Lifecycle details\n\n- Observed status: `{inline(result.observed_status)}`\n"
        )
        if result.drift_source is not None:
            lifecycle_section += (
                f"- Drift source: `{result.drift_source}`\n"
                f"- Changed fields: `{', '.join(result.changed_fields)}`\n"
            )
        lifecycle_section += "\n"
    binding_section = ""
    if report.run_mode == "live_ghec":
        binding_section = (
            "- **Alert-to-snapshot binding:** GitHub alert metadata does not identify "
            "a commit; analysis used the recorded default-branch snapshot.\n"
        )
    return (
        f"{title}\n\n"
        f"- **Run mode:** `{report.run_mode}`\n"
        f"- **Workflow mode:** `{report.workflow_mode}`\n"
        f"- **Repository provenance:** `{report.repository.provenance}`\n"
        f"- **Repository snapshot:** `{report.repository.snapshot_id}`\n"
        f"{binding_section}"
        f"- **Policy:** `{inline(report.policy.policy_id)}@{inline(report.policy.version)}`\n"
        f"- **Collector:** `{inline(report.collector_version)}`\n"
        f"- **Model boundary:** `{inline(report.model_identity)}`\n"
        f"- **Outcome:** `{outcome}`\n\n"
        f"{request_section}"
        "## Advisory summary\n\n"
        f"{fenced(report.alert.summary)}\n\n"
        "## Alert facts\n\n"
        f"- Alert: `{report.alert.alert_number}`\n"
        f"- Advisory: `{inline(report.alert.advisory_id)}`\n"
        f"- Package: `{inline(report.alert.package_name)}`\n"
        f"- Vulnerable range: `{inline(report.alert.vulnerable_range)}`\n"
        f"- Severity: `{report.alert.severity}`\n"
        f"- Manifest: `{inline(report.alert.manifest_path)}`\n\n"
        f"{triage_section}"
        f"{lifecycle_section}"
        f"## Reason code\n\n`{inline(result.reason_code)}`\n\n"
        f"## Validated findings\n\n{validated_details}\n"
    )


def write_report(path: Path, report: Report) -> None:
    """Write authoritative JSON and derived Markdown."""
    report_json = path / "report.json"
    report_markdown = path / "report.md"
    staged_json = path / ".report.json.staged"
    staged_markdown = path / ".report.md.staged"
    publication_lock = path / ".report-publication.lock"
    json_content = _json_content(report)
    markdown_content = render_markdown(report)
    path.mkdir(parents=True, exist_ok=True)
    publication_lock.touch(mode=0o600, exist_ok=False)
    markdown_published = False
    authoritative_published = False
    try:
        if report_json.exists():
            raise FileExistsError(f"authoritative report already exists: {report_json}")
        _atomic_write(staged_json, json_content)
        _atomic_write(staged_markdown, markdown_content)
        os.replace(staged_markdown, report_markdown)
        markdown_published = True
        os.replace(staged_json, report_json)
        authoritative_published = True
        lock_cleanup_error = _remove_exact_file(publication_lock)
        if lock_cleanup_error is not None:
            raise lock_cleanup_error
    except OSError as error:
        cleanup_paths = [staged_json, staged_markdown]
        if authoritative_published:
            cleanup_paths.append(report_json)
        if markdown_published:
            cleanup_paths.append(report_markdown)
        cleanup_paths.append(publication_lock)
        cleanup_errors = [
            (cleanup_path, cleanup_error)
            for cleanup_path in cleanup_paths
            if (cleanup_error := _remove_exact_file(cleanup_path)) is not None
        ]
        _raise_cleanup_failure(error, cleanup_errors)
        raise


def write_failure(path: Path, stage: str, message: str) -> None:
    """Preserve a structured stage failure."""
    write_json(path / "failure.json", {"stage": stage, "message": message})
