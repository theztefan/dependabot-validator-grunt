"""Ecosystem-neutral dependency version evaluation."""

from __future__ import annotations

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from dependabot_validator_grunt.models import Ecosystem, analysis_family
from dependabot_validator_grunt.npm import version_is_vulnerable as npm_version_is_vulnerable


def version_is_vulnerable(
    ecosystem: Ecosystem,
    version: str,
    vulnerable_range: str,
) -> bool:
    """Evaluate one version against the alert's ecosystem range syntax."""
    match analysis_family(ecosystem):
        case "javascript_typescript":
            return npm_version_is_vulnerable(version, vulnerable_range)
        case "python":
            try:
                return Version(version) in SpecifierSet(vulnerable_range)
            except (InvalidSpecifier, InvalidVersion) as error:
                raise ValueError("invalid Python version or vulnerable range") from error
