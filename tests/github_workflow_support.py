"""Stateless live-workflow builders and an in-memory GitHub client fake."""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

from dependabot_validator_grunt.github import GitHubClient

OWNER = "approved-org"
REPO = "approved-repo"
ALERT = 19
COMMIT_SHA = "a" * 40


def request(*, status: str = "pending", reason: str = "no_bandwidth") -> dict[str, object]:
    return {
        "id": 42,
        "number": 9,
        "repository": {
            "id": 1,
            "name": REPO,
            "full_name": f"{OWNER}/{REPO}",
        },
        "organization": {"id": 2, "name": OWNER},
        "requester": {"actor_id": 3, "actor_name": "requester"},
        "request_type": "dependabot_alert_dismissal",
        "data": [
            {
                "reason": reason,
                "alert_number": str(ALERT),
                "alert_title": "Synthetic alert",
            }
        ],
        "resource_identifier": "synthetic",
        "status": status,
        "requester_comment": "Synthetic justification.",
        "expires_at": "2099-01-01T00:00:00Z",
        "created_at": "2026-09-03T00:00:00Z",
        "responses": [],
        "url": (
            f"https://api.github.com/repos/{OWNER}/{REPO}/dismissal-requests/dependabot/{ALERT}"
        ),
        "html_url": f"https://github.com/{OWNER}/{REPO}/security/dependabot/{ALERT}",
    }


def alert(*, severity: str = "high") -> dict[str, object]:
    package = {"ecosystem": "npm", "name": "lodash"}
    return {
        "number": ALERT,
        "state": "open",
        "dependency": {
            "package": package,
            "manifest_path": "package.json",
            "scope": "runtime",
        },
        "security_advisory": {
            "ghsa_id": "GHSA-test-test-test",
            "summary": "Synthetic advisory.",
            "cvss_severities": {
                "cvss_v3": {"score": 7.5},
                "cvss_v4": None,
            },
            "epss": {"percentage": 1.5},
            "cwes": [{"cwe_id": "CWE-79"}],
        },
        "security_vulnerability": {
            "package": package,
            "severity": severity,
            "vulnerable_version_range": "< 4.17.21",
            "first_patched_version": {"identifier": "4.17.21"},
        },
    }


def make_tarball(*, package_version: str | None = "4.17.20") -> bytes:
    buffer = io.BytesIO()
    root_package: dict[str, object] = {}
    lock_packages: dict[str, object] = {"": root_package}
    if package_version is not None:
        root_package["dependencies"] = {"lodash": package_version}
        lock_packages["node_modules/lodash"] = {"version": package_version}
    files = {
        "root/package.json": json.dumps(root_package).encode(),
        "root/package-lock.json": json.dumps(
            {
                "lockfileVersion": 3,
                "packages": lock_packages,
            }
        ).encode(),
        "root/src/index.js": b'const lodash = require("lodash");\n',
    }
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        root = tarfile.TarInfo("root")
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
        for name, content in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
    return buffer.getvalue()


class FakeGitHubClient(GitHubClient):
    """Read-only in-memory GitHub boundary fake."""

    def __init__(
        self,
        *,
        requests: list[dict[str, object]] | None = None,
        alerts: list[dict[str, object]] | None = None,
        request_error: Exception | None = None,
        alert_error: Exception | None = None,
        request_error_at: int | None = None,
        repository: dict[str, object] | None = None,
        tarball: bytes | None = None,
    ) -> None:
        self.requests = requests or [request(), request()]
        self.alerts = alerts or [alert(), alert()]
        self.request_error = request_error
        self.alert_error = alert_error
        self.request_error_at = request_error_at
        self.repository = repository or {
            "full_name": f"{OWNER}/{REPO}",
            "default_branch": "main",
        }
        self.tarball = tarball if tarball is not None else make_tarball()
        self.calls: list[str] = []
        self.arguments: list[tuple[str, str, str, int | None]] = []
        self.request_calls = 0

    async def get_dismissal_request(
        self,
        owner: str,
        repo: str,
        alert_number: int,
    ) -> dict[str, object]:
        self.calls.append("dismissal")
        self.arguments.append(("dismissal", owner, repo, alert_number))
        self.request_calls += 1
        if self.request_error is not None and (
            self.request_error_at is None or self.request_calls == self.request_error_at
        ):
            raise self.request_error
        return self.requests.pop(0)

    async def get_dependabot_alert(
        self,
        owner: str,
        repo: str,
        alert_number: int,
    ) -> dict[str, object]:
        self.calls.append("alert")
        self.arguments.append(("alert", owner, repo, alert_number))
        if self.alert_error is not None:
            raise self.alert_error
        return self.alerts.pop(0)

    async def get_repository(self, owner: str, repo: str) -> dict[str, object]:
        self.calls.append("repository")
        self.arguments.append(("repository", owner, repo, None))
        return self.repository

    async def get_branch(
        self,
        owner: str,
        repo: str,
        branch: str,
    ) -> dict[str, object]:
        self.calls.append("branch")
        self.arguments.append(("branch", owner, repo, None))
        return {"name": branch, "commit": {"sha": COMMIT_SHA}}

    async def download_tarball(
        self,
        owner: str,
        repo: str,
        commit_sha: str,
        max_bytes: int,
    ) -> bytes:
        del commit_sha, max_bytes
        self.calls.append("tarball")
        self.arguments.append(("tarball", owner, repo, None))
        return self.tarball


def report(path: Path) -> dict[str, object]:
    return json.loads((path / "report.json").read_text(encoding="utf-8"))


def paths(root: Path, pattern: str) -> list[Path]:
    return list(root.rglob(pattern))
