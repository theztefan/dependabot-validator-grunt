"""Read-only GHEC REST access, response normalization, and safe archive extraction.

This module owns the only five permitted GitHub API operations, converts their
raw JSON shapes into project-owned evidence models, and safely extracts a
downloaded repository tarball into a read-only snapshot. It never performs a
GitHub write and never sends the GHEC token to a non-GitHub host.
"""

from __future__ import annotations

import asyncio
import io
import json
import re
import tarfile
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal, Protocol, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
)

from dependabot_validator_grunt.agentic import path_is_denied
from dependabot_validator_grunt.models import (
    AlertSnapshot,
    Ecosystem,
    RepositorySnapshot,
    RequestSnapshot,
    normalize_package_identifier,
    stable_digest,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from dependabot_validator_grunt.policy import Limits

DEPENDENCY_FILE_NAMES = {
    "package.json",
    "package-lock.json",
    "npm-shrinkwrap.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "pyproject.toml",
    "poetry.lock",
    "uv.lock",
}

GHEC_API_URL = "https://api.github.com"
API_VERSION = "2026-03-10"
USER_AGENT = "dependabot-validator-grunt-github-client/1"
ACCEPT_HEADER = "application/vnd.github+json"

_TIMEOUT_SECONDS = 30
_CHUNK_BYTES = 65_536
_DEFAULT_JSON_MAX_BYTES = 10 * 1024 * 1024
_MAX_REDIRECTS = 5
_REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})

_OWNER_REPO_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_BRANCH_INVALID_CHARS = frozenset(" ~^:?*[\\")
_ALLOWED_REDIRECT_EXACT_HOSTS = frozenset({"api.github.com", "github.com", "codeload.github.com"})

_JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, object])


class GitHubAuthError(Exception):
    """Raised when GHEC reports 401 or 403 for an authenticated request."""


class GitHubCollectionError(Exception):
    """Raised for any other GHEC HTTP, network, or response-shape failure."""


def _validate_repo_component(value: str, field: str) -> str:
    if not _OWNER_REPO_PATTERN.fullmatch(value):
        raise ValueError(f"{field} must be a valid GitHub owner or repository name")
    return value


def _validate_alert_number(value: int) -> int:
    if isinstance(value, bool) or value <= 0:
        raise ValueError("alert_number must be a positive integer")
    return value


def _validate_commit_sha(value: str) -> str:
    if not _SHA_PATTERN.fullmatch(value):
        raise ValueError("commit_sha must be a 40-character lowercase hex SHA-1")
    return value


def _validate_branch(value: str) -> str:
    if (
        not value
        or value != value.strip()
        or value.startswith(("/", "."))
        or value.endswith(("/", "."))
        or value.endswith(".lock")
        or ".." in value
        or "//" in value
        or "@{" in value
        or any(char in _BRANCH_INVALID_CHARS for char in value)
        or any(ord(char) < 0x20 for char in value)
    ):
        raise ValueError("branch must be a valid Git reference name")
    return value


def _encode(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _is_allowed_redirect_host(hostname: str | None) -> bool:
    if not hostname:
        return False
    folded = hostname.lower()
    return folded in _ALLOWED_REDIRECT_EXACT_HOSTS or folded.endswith(".githubusercontent.com")


def _safe_redirect_request(
    previous: urllib.request.Request, new_url: str
) -> urllib.request.Request:
    """Build the next redirected request, stripping auth on any host change.

    This is a pure, directly testable function: it never opens a socket. It
    rejects any redirect target that is not an HTTPS GitHub-controlled host and
    removes the Authorization header whenever the redirect target host differs
    from the previous request's host.
    """
    parsed = urllib.parse.urlsplit(new_url)
    if parsed.scheme != "https" or not _is_allowed_redirect_host(parsed.hostname):
        raise GitHubCollectionError("GitHub request failed")
    original_host = (urllib.parse.urlsplit(previous.full_url).hostname or "").lower()
    new_host = (parsed.hostname or "").lower()
    # urllib adds Host to the opened request. Never forward that transport-
    # managed value because the redirect target must receive its own host.
    headers = {key: value for key, value in previous.header_items() if key.lower() != "host"}
    if new_host != original_host:
        headers = {key: value for key, value in headers.items() if key.lower() != "authorization"}
    return urllib.request.Request(new_url, headers=headers, method="GET")


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Disable automatic redirect handling so redirects surface as HTTPError."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> urllib.request.Request | None:
        return None


_OPENER = urllib.request.build_opener(_NoRedirectHandler)


class _ResponseHeaders(Protocol):
    def get(self, name: str, default: str | None = None) -> str | None: ...


class _StreamingResponse(Protocol):
    """The minimal streaming-response shape `_read_bounded` depends on."""

    headers: _ResponseHeaders

    def read(self, amount: int) -> bytes: ...


def _read_bounded(response: _StreamingResponse, max_bytes: int) -> bytes:
    content_length = response.headers.get("Content-Length")
    if content_length is not None:
        try:
            declared = int(content_length)
        except ValueError:
            declared = None
        if declared is not None and declared > max_bytes:
            raise GitHubCollectionError("archive exceeded the configured byte limit")
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise GitHubCollectionError("archive exceeded the configured byte limit")
        chunks.append(chunk)
    return b"".join(chunks)


def _download(url: str, headers: Mapping[str, str], max_bytes: int) -> bytes:
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    redirects = 0
    while True:
        try:
            response_cm = _OPENER.open(request, timeout=_TIMEOUT_SECONDS)
        except urllib.error.HTTPError as error:
            code = error.code
            location = error.headers.get("Location") if error.headers else None
            error.close()
            if code in _REDIRECT_CODES:
                if redirects >= _MAX_REDIRECTS:
                    raise GitHubCollectionError("GitHub request failed") from None
                if not location:
                    raise GitHubCollectionError("GitHub request failed") from None
                next_url = urllib.parse.urljoin(request.full_url, location)
                request = _safe_redirect_request(request, next_url)
                redirects += 1
                continue
            if code in (401, 403):
                raise GitHubAuthError("GitHub authentication or authorization failed") from None
            raise GitHubCollectionError("GitHub request failed") from None
        except urllib.error.URLError:
            raise GitHubCollectionError("GitHub request failed") from None
        break
    with response_cm as response:
        return _read_bounded(response, max_bytes)


class GitHubClient:
    """Read-only GHEC REST client limited to the five permitted GET operations."""

    def __init__(self, token: str, api_url: str = GHEC_API_URL) -> None:
        if not token or not token.strip():
            raise ValueError("token must not be empty")
        if api_url != GHEC_API_URL:
            raise ValueError("api_url must be the GitHub Enterprise Cloud API host")
        self._token = token
        self._api_url = api_url

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": ACCEPT_HEADER,
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": USER_AGENT,
            "Authorization": f"Bearer {self._token}",
        }

    def _get_json(self, path: str) -> dict[str, object]:
        raw = _download(f"{self._api_url}{path}", self._headers(), _DEFAULT_JSON_MAX_BYTES)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise GitHubCollectionError("GitHub response was malformed") from None
        try:
            return _JSON_OBJECT_ADAPTER.validate_python(parsed)
        except ValidationError:
            raise GitHubCollectionError("GitHub response was malformed") from None

    async def get_dismissal_request(
        self, owner: str, repo: str, alert_number: int
    ) -> dict[str, object]:
        """GET /repos/{owner}/{repo}/dismissal-requests/dependabot/{alert_number}."""
        owner_v = _validate_repo_component(owner, "owner")
        repo_v = _validate_repo_component(repo, "repo")
        number_v = _validate_alert_number(alert_number)
        path = (
            f"/repos/{_encode(owner_v)}/{_encode(repo_v)}/dismissal-requests/dependabot/{number_v}"
        )
        return await asyncio.to_thread(self._get_json, path)

    async def get_dependabot_alert(
        self, owner: str, repo: str, alert_number: int
    ) -> dict[str, object]:
        """GET /repos/{owner}/{repo}/dependabot/alerts/{alert_number}."""
        owner_v = _validate_repo_component(owner, "owner")
        repo_v = _validate_repo_component(repo, "repo")
        number_v = _validate_alert_number(alert_number)
        path = f"/repos/{_encode(owner_v)}/{_encode(repo_v)}/dependabot/alerts/{number_v}"
        return await asyncio.to_thread(self._get_json, path)

    async def get_repository(self, owner: str, repo: str) -> dict[str, object]:
        """GET /repos/{owner}/{repo}."""
        owner_v = _validate_repo_component(owner, "owner")
        repo_v = _validate_repo_component(repo, "repo")
        path = f"/repos/{_encode(owner_v)}/{_encode(repo_v)}"
        return await asyncio.to_thread(self._get_json, path)

    async def get_branch(self, owner: str, repo: str, branch: str) -> dict[str, object]:
        """GET /repos/{owner}/{repo}/branches/{branch}."""
        owner_v = _validate_repo_component(owner, "owner")
        repo_v = _validate_repo_component(repo, "repo")
        branch_v = _validate_branch(branch)
        path = f"/repos/{_encode(owner_v)}/{_encode(repo_v)}/branches/{_encode(branch_v)}"
        return await asyncio.to_thread(self._get_json, path)

    async def download_tarball(
        self, owner: str, repo: str, commit_sha: str, max_bytes: int
    ) -> bytes:
        """GET /repos/{owner}/{repo}/tarball/{commit_sha}, bounded to max_bytes."""
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        owner_v = _validate_repo_component(owner, "owner")
        repo_v = _validate_repo_component(repo, "repo")
        sha_v = _validate_commit_sha(commit_sha)
        path = f"/repos/{_encode(owner_v)}/{_encode(repo_v)}/tarball/{_encode(sha_v)}"
        url = f"{self._api_url}{path}"
        return await asyncio.to_thread(_download, url, self._headers(), max_bytes)


class _RawModel(BaseModel):
    """Lenient base for untrusted raw API shapes: strict required fields, ignored extras."""

    model_config = ConfigDict(frozen=True, extra="ignore")


class _RawDismissalData(_RawModel):
    reason: str
    alert_number: str
    alert_title: str = ""


class _RawRepositoryRef(_RawModel):
    full_name: str


class _RawDismissalResponse(_RawModel):
    status: str
    message: str = ""


class _RawDismissalRequest(_RawModel):
    id: int
    repository: _RawRepositoryRef
    data: tuple[_RawDismissalData, ...] = ()
    status: Literal["pending", "approved", "denied", "expired"]
    requester_comment: str = ""
    expires_at: datetime | None = None
    responses: tuple[_RawDismissalResponse, ...] = ()

    # The official schema permits `data`, `requester_comment`, and `responses`
    # to be JSON null (not merely absent); coerce null to the same empty
    # default used when the field is omitted entirely.
    @field_validator("data", "responses", mode="before")
    @classmethod
    def _null_sequence_to_empty(cls, value: object) -> object:
        return () if value is None else value

    @field_validator("requester_comment", mode="before")
    @classmethod
    def _null_string_to_empty(cls, value: object) -> object:
        return "" if value is None else value


class _RawPackage(_RawModel):
    ecosystem: str
    name: str


class _RawDependency(_RawModel):
    package: _RawPackage
    manifest_path: str
    scope: Literal["runtime", "development"] | None = None
    relationship: Literal["direct", "transitive", "inconclusive", "unknown"] | None = None


class _RawCvssEntry(_RawModel):
    score: float | None = None


class _RawCvssSeverities(_RawModel):
    cvss_v3: _RawCvssEntry | None = None
    cvss_v4: _RawCvssEntry | None = None


class _RawCwe(_RawModel):
    cwe_id: str


class _RawEpss(_RawModel):
    percentage: float | None = None


class _RawSecurityAdvisory(_RawModel):
    ghsa_id: str
    summary: str = ""
    cvss: _RawCvssEntry | None = None
    cvss_severities: _RawCvssSeverities | None = None
    cwes: tuple[_RawCwe, ...] = ()
    epss: _RawEpss | None = None


class _RawFirstPatchedVersion(_RawModel):
    identifier: str


class _RawSecurityVulnerability(_RawModel):
    package: _RawPackage
    severity: Literal["low", "medium", "high", "critical"]
    vulnerable_version_range: str
    first_patched_version: _RawFirstPatchedVersion | None = None


class _RawDependabotAlert(_RawModel):
    number: int = Field(gt=0)
    state: Literal["open", "dismissed", "fixed", "auto_dismissed"]
    dependency: _RawDependency
    security_advisory: _RawSecurityAdvisory
    security_vulnerability: _RawSecurityVulnerability


def normalize_dismissal_request(
    raw: dict[str, object],
    *,
    owner: str,
    repo: str,
    alert_number: int,
    operator_reason: str | None = None,
    operator_justification: str | None = None,
) -> RequestSnapshot:
    """Strictly normalize a raw dismissal-request payload into a RequestSnapshot.

    GitHub-attested `reason` (from the matching `data` entry) and
    `requester_comment` take precedence whenever non-empty. Operator-supplied
    `--reason`/`--justification-file` values are used only as an explicit
    fallback when the attested field is absent; a non-empty attested value is
    never overwritten. A missing reason with no operator fallback is a
    collection error. A missing justification with no operator fallback is not
    an error: `RequestSnapshot.justification` legitimately defaults to empty
    free-text commentary.

    The official schema permits `data` to be null or empty entirely (for
    example a dismissal request opened without a matching alert-scoped entry
    yet). When no attested `data` entries exist at all, there is nothing to
    cross-check against `alert_number`, so the request is bound to the alert
    using the endpoint arguments that scoped the API call
    (`owner`/`repo`/`alert_number`) instead of raising a mismatch error; the
    reason must then come from the operator fallback. When `data` entries do
    exist but none match `alert_number`, that is a genuine mismatch and still
    raises a collection error.
    """
    try:
        parsed = _RawDismissalRequest.model_validate(raw)
    except ValidationError:
        raise GitHubCollectionError("GitHub response was malformed") from None
    if parsed.repository.full_name.casefold() != f"{owner}/{repo}".casefold():
        raise GitHubCollectionError("GitHub response did not match the expected repository")
    attested_reason = ""
    if parsed.data:
        matching = [entry for entry in parsed.data if entry.alert_number == str(alert_number)]
        if not matching:
            raise GitHubCollectionError("GitHub response did not match the expected alert")
        attested_reason = matching[0].reason.strip()
    if attested_reason:
        reason = attested_reason
        used_operator_reason = False
    elif operator_reason and operator_reason.strip():
        reason = operator_reason.strip()
        used_operator_reason = True
    else:
        raise GitHubCollectionError("dismissal request is missing a reason")
    attested_justification = parsed.requester_comment.strip()
    if attested_justification:
        justification = attested_justification
        used_operator_justification = False
    elif operator_justification and operator_justification.strip():
        justification = operator_justification.strip()
        used_operator_justification = True
    else:
        justification = ""
        used_operator_justification = False
    responses = tuple(
        f"{entry.status}:{entry.message}" if entry.message else entry.status
        for entry in parsed.responses
    )
    return RequestSnapshot(
        request_id=str(parsed.id),
        reason=reason,
        justification=justification,
        status=parsed.status,
        expires_at=parsed.expires_at,
        provenance=(
            "operator_supplied"
            if used_operator_reason or used_operator_justification
            else "ghec_attested"
        ),
        responses=responses,
        raw_response_digest=stable_digest(raw),
    )


def normalize_dependabot_alert(raw: dict[str, object], *, alert_number: int) -> AlertSnapshot:
    """Strictly normalize a raw Dependabot alert payload into an AlertSnapshot.

    `security_vulnerability.package` is parsed and required to match
    `dependency.package` (ecosystem and name). GitHub's alert payload carries
    the affected package in both places; trusting `security_vulnerability`'s
    copy without cross-checking it against `dependency.package` would let
    contradictory vulnerability metadata silently pass through as if it
    described the alert's actual dependency.
    """
    try:
        parsed = _RawDependabotAlert.model_validate(raw)
    except ValidationError:
        raise GitHubCollectionError("GitHub response was malformed") from None
    if parsed.number != alert_number:
        raise GitHubCollectionError("GitHub response did not match the expected alert")
    raw_ecosystem = parsed.dependency.package.ecosystem
    if raw_ecosystem not in {"npm", "pip", "uv"}:
        raise GitHubCollectionError("only npm, pip, and uv ecosystems are supported")
    ecosystem = cast(Ecosystem, raw_ecosystem)
    advisory = parsed.security_advisory
    vulnerability = parsed.security_vulnerability
    try:
        dependency_identity = normalize_package_identifier(
            ecosystem,
            parsed.dependency.package.name,
        )
        vulnerability_identity = normalize_package_identifier(
            ecosystem,
            vulnerability.package.name,
        )
    except ValueError:
        raise GitHubCollectionError("GitHub response was malformed") from None
    if (
        vulnerability.package.ecosystem != ecosystem
        or vulnerability_identity != dependency_identity
    ):
        raise GitHubCollectionError("GitHub response contained contradictory package metadata")
    cvss: float | None = None
    if advisory.cvss_severities is not None:
        v4 = advisory.cvss_severities.cvss_v4
        v3 = advisory.cvss_severities.cvss_v3
        if v4 is not None and v4.score is not None:
            cvss = v4.score
        elif v3 is not None and v3.score is not None:
            cvss = v3.score
    if cvss is None and advisory.cvss is not None:
        cvss = advisory.cvss.score
    patched = (
        vulnerability.first_patched_version.identifier
        if vulnerability.first_patched_version is not None
        else None
    )
    scope: Literal["runtime", "development", "unknown"] = parsed.dependency.scope or "unknown"
    relationship: Literal["direct", "transitive", "inconclusive", "unknown"] = (
        parsed.dependency.relationship or "unknown"
    )
    try:
        return AlertSnapshot(
            alert_number=parsed.number,
            state=parsed.state,
            advisory_id=advisory.ghsa_id,
            summary=advisory.summary,
            severity=vulnerability.severity,
            cvss=cvss,
            epss=advisory.epss.percentage if advisory.epss is not None else None,
            cwes=tuple(cwe.cwe_id for cwe in advisory.cwes),
            ecosystem=ecosystem,
            package_name=parsed.dependency.package.name,
            vulnerable_range=vulnerability.vulnerable_version_range,
            patched_versions=patched,
            manifest_path=parsed.dependency.manifest_path,
            scope=scope,
            dependency_relationship=relationship,
            raw_response_digest=stable_digest(raw),
        )
    except ValidationError:
        raise GitHubCollectionError("GitHub response was malformed") from None


class _RawRepositoryOwner(_RawModel):
    login: str


class _RawRepository(_RawModel):
    default_branch: str
    full_name: str | None = None
    name: str | None = None
    owner: _RawRepositoryOwner | None = None


class _RawBranchCommit(_RawModel):
    sha: str


class _RawBranch(_RawModel):
    name: str
    commit: _RawBranchCommit


def normalize_repository(raw: dict[str, object], *, owner: str, repo: str) -> str:
    """Strictly normalize a raw repository payload into its default branch name.

    The response is bound to the requested `owner`/`repo` using either the
    `full_name` field or the `owner.login`/`name` pair; either representation
    is sufficient proof, since GitHub's own payload carries both derived from
    the same underlying repository record. Neither present, or present but
    disagreeing with the requested `owner`/`repo`, is a collection error.
    """
    try:
        parsed = _RawRepository.model_validate(raw)
    except ValidationError:
        raise GitHubCollectionError("GitHub response was malformed") from None
    matched = (
        parsed.full_name is not None and parsed.full_name.casefold() == f"{owner}/{repo}".casefold()
    )
    if not matched and parsed.owner is not None and parsed.name is not None:
        matched = (
            parsed.owner.login.casefold() == owner.casefold()
            and parsed.name.casefold() == repo.casefold()
        )
    if not matched:
        raise GitHubCollectionError("GitHub response did not match the expected repository")
    if not parsed.default_branch:
        raise GitHubCollectionError("GitHub response is missing a default branch")
    try:
        return _validate_branch(parsed.default_branch)
    except ValueError:
        raise GitHubCollectionError("GitHub response has an invalid default branch") from None


def normalize_branch_sha(raw: dict[str, object], *, expected_branch: str) -> str:
    """Strictly normalize a raw branch payload into its commit SHA-1.

    Validates that the payload's `name` matches `expected_branch` and that
    `commit.sha` is a well-formed lowercase 40-character hex SHA-1 before
    returning it.
    """
    try:
        parsed = _RawBranch.model_validate(raw)
    except ValidationError:
        raise GitHubCollectionError("GitHub response was malformed") from None
    if parsed.name != expected_branch:
        raise GitHubCollectionError("GitHub response did not match the expected branch")
    if not _SHA_PATTERN.fullmatch(parsed.commit.sha):
        raise GitHubCollectionError("GitHub response contained a malformed commit SHA")
    return parsed.commit.sha


def _root_and_relative_parts(name: str) -> tuple[str, tuple[str, ...]]:
    if not name or name.startswith("/") or PurePosixPath(name).is_absolute():
        raise GitHubCollectionError("archive contains an absolute path")
    parts = PurePosixPath(name).parts
    if not parts or ".." in parts:
        raise GitHubCollectionError("archive contains a path traversal segment")
    return parts[0], parts[1:]


def _validate_root_prefix(members: list[tarfile.TarInfo]) -> str:
    if not members:
        raise GitHubCollectionError("archive is empty")
    roots: set[str] = set()
    for member in members:
        root, _ = _root_and_relative_parts(member.name)
        roots.add(root)
    if len(roots) != 1:
        raise GitHubCollectionError("archive does not have a single root directory")
    return next(iter(roots))


def _member_relative_path(member: tarfile.TarInfo, root_prefix: str) -> str:
    root, remainder = _root_and_relative_parts(member.name)
    if root != root_prefix:
        raise GitHubCollectionError("archive member escapes the expected root directory")
    if any(part in ("", ".") for part in remainder):
        raise GitHubCollectionError("archive contains an invalid path segment")
    if not remainder and not member.isdir():
        raise GitHubCollectionError("archive contains an invalid path segment")
    return "/".join(remainder)


def _normalized_collision_prefixes(paths: list[str]) -> set[tuple[str, ...]]:
    spellings: dict[tuple[tuple[str, ...], str], set[str]] = {}
    normalized_path_counts: dict[tuple[str, ...], int] = {}
    for relative in paths:
        normalized_parent: tuple[str, ...] = ()
        for part in PurePosixPath(relative).parts:
            normalized_part = unicodedata.normalize("NFC", part).casefold()
            spellings.setdefault((normalized_parent, normalized_part), set()).add(part)
            normalized_parent = (*normalized_parent, normalized_part)
        normalized_path_counts[normalized_parent] = (
            normalized_path_counts.get(normalized_parent, 0) + 1
        )
    return {
        (*parent, normalized_part)
        for (parent, normalized_part), values in spellings.items()
        if len(values) > 1
    } | {path for path, count in normalized_path_counts.items() if count > 1}


def _normalized_path_parts(relative: str) -> tuple[str, ...]:
    return tuple(
        unicodedata.normalize("NFC", part).casefold() for part in PurePosixPath(relative).parts
    )


def _path_has_collision(
    relative: str,
    collision_prefixes: set[tuple[str, ...]],
) -> bool:
    parts = _normalized_path_parts(relative)
    return any(parts[: len(prefix)] == prefix for prefix in collision_prefixes)


def _safe_destination_path(destination: Path, relative: str) -> Path:
    parts = PurePosixPath(relative).parts
    if any(part in ("", ".", "..") for part in parts):
        raise GitHubCollectionError("archive member escapes the destination root")
    return destination.joinpath(*parts)


def dependency_file_uses_extended_limit(
    relative_path: str,
    *,
    selected_dependency_path: str | None = None,
) -> bool:
    """Return whether one normalized path receives the dependency-file limit."""
    normalized = PurePosixPath(relative_path).as_posix()
    if PurePosixPath(normalized).name in DEPENDENCY_FILE_NAMES:
        return True
    if selected_dependency_path is None:
        return False
    selected = PurePosixPath(selected_dependency_path).as_posix()
    return normalized == selected and PurePosixPath(selected).suffix in {".txt", ".in"}


def extract_repository_tarball(
    data: bytes,
    destination: Path,
    *,
    owner: str,
    repo: str,
    default_branch: str,
    commit_sha: str,
    limits: Limits,
    selected_dependency_path: str | None = None,
) -> RepositorySnapshot:
    """Validate the entire archive, then manually extract a read-only snapshot.

    Every member is counted and every regular member's size is summed against
    policy limits before any filesystem write occurs. Only directories and
    regular files are created; ownership, mode, and timestamp metadata from the
    archive are never applied. Links, special files, credential-like paths, and
    repository-provided agent configuration are excluded from the written tree
    but still recorded and counted toward archive limits. The completed tree,
    including the destination root, is made read-only.
    """
    if len(data) > limits.archive_bytes:
        raise GitHubCollectionError("archive exceeded the configured byte limit")
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
            members = archive.getmembers()
            if len(members) > limits.max_archive_members:
                raise GitHubCollectionError("archive exceeded the configured member limit")
            root_prefix = _validate_root_prefix(members)
            normalized_members = [
                (_member_relative_path(member, root_prefix), member) for member in members
            ]
            collision_prefixes = _normalized_collision_prefixes(
                [relative for relative, _ in normalized_members if relative]
            )
            if selected_dependency_path is not None and _path_has_collision(
                PurePosixPath(selected_dependency_path).as_posix(),
                collision_prefixes,
            ):
                raise GitHubCollectionError("selected dependency path collides after normalization")

            plan: list[tuple[str, tarfile.TarInfo, bool]] = []
            coverage_excluded_prefixes = {
                relative
                for relative, _ in normalized_members
                if relative and _path_has_collision(relative, collision_prefixes)
            }
            expanded_total = 0
            for relative, member in normalized_members:
                collides = _path_has_collision(relative, collision_prefixes)
                if relative == "":
                    continue  # the root directory entry itself; nothing to create
                if member.isdir():
                    plan.append((relative, member, collides))
                    continue
                if member.isreg() and not member.issparse():
                    expanded_total += member.size
                    if expanded_total > limits.expanded_bytes:
                        raise GitHubCollectionError(
                            "archive exceeded the configured expanded byte limit"
                        )
                    member_limit = (
                        limits.max_dependency_file_bytes
                        if dependency_file_uses_extended_limit(
                            relative,
                            selected_dependency_path=selected_dependency_path,
                        )
                        else limits.max_archive_file_bytes
                    )
                    if member.size > member_limit:
                        if (
                            selected_dependency_path is not None
                            and PurePosixPath(relative).as_posix()
                            == PurePosixPath(selected_dependency_path).as_posix()
                        ):
                            raise GitHubCollectionError(
                                "selected dependency file exceeded the configured byte limit"
                            )
                        coverage_excluded_prefixes.add(relative)
                        plan.append((relative, member, True))
                        continue
                    plan.append((relative, member, collides))
                    continue
                plan.append((relative, member, True))
            resolved_destination = destination.resolve()
            resolved_destination.mkdir(parents=True, exist_ok=True)
            included: list[str] = []
            excluded: list[str] = []
            coverage_excluded: list[str] = []
            excluded_prefixes = {relative for relative, _, unsupported in plan if unsupported}
            created_directories: set[Path] = {resolved_destination}
            for relative, member, unsupported in plan:
                denied = (
                    unsupported
                    or path_is_denied(relative)
                    or any(
                        relative == prefix or relative.startswith(f"{prefix}/")
                        for prefix in excluded_prefixes
                    )
                )
                target = _safe_destination_path(resolved_destination, relative)
                if resolved_destination != target and resolved_destination not in target.parents:
                    raise GitHubCollectionError("archive member escapes the destination root")
                if member.isdir():
                    if denied:
                        excluded.append(relative)
                        if any(
                            relative == prefix or relative.startswith(f"{prefix}/")
                            for prefix in coverage_excluded_prefixes
                        ):
                            coverage_excluded.append(relative)
                        continue
                    target.mkdir(parents=True, exist_ok=True)
                    directory = target
                    while directory != resolved_destination:
                        created_directories.add(directory)
                        directory = directory.parent
                    continue
                if denied:
                    excluded.append(relative)
                    if any(
                        relative == prefix or relative.startswith(f"{prefix}/")
                        for prefix in coverage_excluded_prefixes
                    ):
                        coverage_excluded.append(relative)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                parent = target.parent
                while parent != resolved_destination:
                    created_directories.add(parent)
                    parent = parent.parent
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise GitHubCollectionError("archive member could not be read")
                with extracted:
                    content = extracted.read()
                target.write_bytes(content)
                included.append(relative)
            for relative in included:
                (resolved_destination / relative).chmod(0o444)
            directories_by_depth = sorted(
                created_directories, key=lambda path: len(path.parts), reverse=True
            )
            for directory in directories_by_depth:
                directory.chmod(0o555)
    except tarfile.TarError:
        raise GitHubCollectionError("archive could not be parsed") from None
    return RepositorySnapshot(
        owner=owner,
        name=repo,
        default_branch=default_branch,
        snapshot_id=commit_sha,
        provenance="ghec_attested",
        included_paths=tuple(sorted(set(included))),
        excluded_paths=tuple(sorted(set(excluded))),
        coverage_excluded_paths=tuple(sorted(set(coverage_excluded))),
    )
