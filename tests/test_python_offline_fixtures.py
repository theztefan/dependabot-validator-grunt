"""Production-shaped offline acceptance cases for Python dependency workflows."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from dependabot_validator_grunt.models import (
    PYTHON_REACHABILITY_OPERATIONS,
    AgentFinding,
    AgentTask,
    DependencyPath,
    DismissalDecision,
    EvidenceBundle,
    ReachabilityEvidence,
    Report,
)
from dependabot_validator_grunt.workflow import review_offline_fixture

ROOT = Path(__file__).parents[1]
CASES = ROOT / "examples" / "offline-cases"


def _read_model[ModelT: BaseModel](path: Path, model: type[ModelT]) -> ModelT:
    return model.model_validate_json(path.read_text(encoding="utf-8"))


def _path_packages(paths: tuple[DependencyPath, ...]) -> list[list[str]]:
    return [[node.package_name for node in path.nodes] for path in paths]


async def test_poetry_transitive_import_fixture_denies_with_python_authority(
    tmp_path: Path,
) -> None:
    output = await review_offline_fixture(
        CASES / "python-poetry-transitive-import",
        tmp_path,
    )

    evidence = _read_model(output / "evidence.json", EvidenceBundle)
    task = _read_model(output / "agent-task.json", AgentTask)
    reachability = _read_model(output / "reachability-evidence.json", ReachabilityEvidence)
    report = _read_model(output / "report.json", Report)

    assert evidence.evidence_format_version == "3.0"
    assert task.task_format_version == "3.0"
    assert report.report_schema_version == "3.0"
    assert _path_packages(evidence.dependency.dependency_paths) == [
        ["<project>", "transport-parent", "requests"]
    ]
    assert _path_packages(task.dependency_paths) == [["<project>", "transport-parent", "requests"]]
    assert evidence.dependency.dependency_paths[0].edge_requirements == (
        ">=1.4,<2",
        ">=2.0,<3.0",
    )
    assert task.dependency_paths[0].edge_requirements == (
        ">=1.4,<2",
        ">=2.0,<3.0",
    )
    assert evidence.dependency.package_manager == "poetry"
    assert evidence.dependency.dependency_consumers == ("poetry.lock:package[0]",)
    assert task.dependency_relationship == "transitive"
    assert [target.model_dump(mode="json") for target in task.import_targets] == [
        {
            "value": "requests",
            "provenance": "canonical_distribution",
            "authoritative": True,
        }
    ]
    assert reachability.target_identifiers == ("requests",)
    assert reachability.profile == "python"
    assert reachability.operations == PYTHON_REACHABILITY_OPERATIONS
    assert reachability.status == "syntax_usage_found"
    assert {
        finding.language for finding in reachability.findings if finding.kind == "static_import"
    } == {"Python"}
    assert all(finding.citation.path != "web/status.js" for finding in reachability.findings)
    assert isinstance(report.result, DismissalDecision)
    assert report.result.recommendation == "deny"
    assert report.result.reason_code == "advisory_applies"


async def test_uv_parent_only_fixture_keeps_target_reachability_unproven(
    tmp_path: Path,
) -> None:
    output = await review_offline_fixture(CASES / "python-uv-parent-only", tmp_path)

    evidence = _read_model(output / "evidence.json", EvidenceBundle)
    task = _read_model(output / "agent-task.json", AgentTask)
    reachability = _read_model(output / "reachability-evidence.json", ReachabilityEvidence)
    finding = _read_model(output / "agent-findings.json", AgentFinding)
    report = _read_model(output / "report.json", Report)

    assert evidence.evidence_format_version == "3.0"
    assert task.task_format_version == "3.0"
    assert report.report_schema_version == "3.0"
    assert _path_packages(evidence.dependency.dependency_paths) == [
        ["<project>", "transport-parent", "requests"]
    ]
    assert _path_packages(task.dependency_paths) == [["<project>", "transport-parent", "requests"]]
    assert evidence.dependency.dependency_paths[0].edge_requirements == ("==1.4.0", None)
    assert task.dependency_paths[0].edge_requirements == ("==1.4.0", None)
    assert reachability.target_identifiers == ("requests",)
    assert reachability.status == "no_syntax_match"
    assert reachability.findings == ()
    assert any(
        citation.path == "service/worker.py" and "transport_parent" in citation.excerpt
        for citation in finding.citations
    )
    assert isinstance(report.result, DismissalDecision)
    assert report.result.recommendation == "human_review"
    assert report.result.reason_code == "agent_denial_unproven"


async def test_pip_compile_fixture_preserves_pin_and_advisory_provenance(
    tmp_path: Path,
) -> None:
    output = await review_offline_fixture(
        CASES / "python-pip-compile-provenance",
        tmp_path,
    )

    evidence = _read_model(output / "evidence.json", EvidenceBundle)
    task = _read_model(output / "agent-task.json", AgentTask)
    reachability = _read_model(output / "reachability-evidence.json", ReachabilityEvidence)
    report = _read_model(output / "report.json", Report)

    assert evidence.evidence_format_version == "3.0"
    assert task.task_format_version == "3.0"
    assert report.report_schema_version == "3.0"
    assert evidence.dependency.package_manager == "pip"
    assert evidence.dependency.instances == ()
    assert evidence.dependency.dependency_paths == ()
    assert [
        provenance.model_dump(mode="json")
        for provenance in evidence.dependency.dependency_provenance
    ] == [
        {
            "kind": "requirement_include",
            "source_path": "requirements.txt",
            "line": 1,
            "target": "requirements/base.txt",
            "authoritative": False,
        },
        {
            "kind": "pip_compile_via",
            "source_path": "requirements.txt",
            "line": 2,
            "target": "transport-parent",
            "authoritative": False,
        },
    ]
    assert task.dependency_paths == ()
    assert [declaration.model_dump(mode="json") for declaration in task.manifest_declarations] == [
        {
            "manifest_path": "requirements.txt",
            "name": "requests",
            "spec": "==2.31.0",
            "relationship": "direct",
            "alias_target": None,
            "exact_version": "2.31.0",
            "marker": None,
            "source_kind": "registry",
            "source_locator": None,
        }
    ]
    assert reachability.status == "no_syntax_match"
    assert isinstance(report.result, DismissalDecision)
    assert report.result.recommendation == "human_review"
    assert report.result.reason_code == "insufficient_context"


async def test_reviewed_distribution_import_mapping_authorizes_positive_use(
    tmp_path: Path,
) -> None:
    output = await review_offline_fixture(
        CASES / "python-distribution-import-mismatch",
        tmp_path,
    )

    task = _read_model(output / "agent-task.json", AgentTask)
    finding = _read_model(output / "agent-findings.json", AgentFinding)
    report = _read_model(output / "report.json", Report)

    assert task.task_format_version == "3.0"
    assert task.package_identity == "pyyaml"
    assert [target.model_dump(mode="json") for target in task.import_targets] == [
        {
            "value": "yaml",
            "provenance": "curated_mapping",
            "authoritative": True,
        }
    ]
    reachability = _read_model(output / "reachability-evidence.json", ReachabilityEvidence)
    assert reachability.analysis_root == ""
    assert reachability.status == "syntax_usage_found"
    assert any(
        citation.path == "service/parser.py" and "yaml" in citation.excerpt
        for citation in finding.citations
    )
    assert isinstance(report.result, DismissalDecision)
    assert report.report_schema_version == "3.0"
    assert report.result.recommendation == "deny"
    assert report.result.reason_code == "advisory_applies"
