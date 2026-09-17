# Public GitHub API boundary

Read this page only when changing live collection. Current workflow behavior
and permissions remain authoritative in
[`../workflow-contract.md`](../workflow-contract.md).

The live adapter uses the publicly documented GitHub Enterprise Cloud REST API at
<https://docs.github.com/en/enterprise-cloud@latest/rest>. It sends
`X-GitHub-Api-Version: 2026-03-10` and performs only these GET operations:

```text
GET /repos/{owner}/{repo}/dismissal-requests/dependabot/{alert_number}
GET /repos/{owner}/{repo}/dependabot/alerts/{alert_number}
GET /repos/{owner}/{repo}
GET /repos/{owner}/{repo}/branches/{default_branch}
GET /repos/{owner}/{repo}/tarball/{commit_sha}
```

The dismissal-request endpoint is publicly documented under
[Dependabot alert dismissal requests](https://docs.github.com/en/enterprise-cloud@latest/rest/dependabot/alert-dismissal-requests).
The adapter reads one request by alert number and normalizes its reason,
comment, status, expiry, and response statuses. GitHub values take precedence;
operator reason and justification options only fill missing values.

## Authentication and redirects

`DEPENDABOT_GITHUB_TOKEN` is passed only to the GitHub client. The token must
read Dependabot alerts and dismissal requests, repository metadata, branches,
and contents. The client reports HTTP 401 and 403 as authentication or
authorization failures and does not inspect token grants.

Automatic redirects are disabled. The client follows only HTTPS redirects to
an allowlisted GitHub host, removes authorization when the host changes, and
lets the HTTP library rebuild transport-managed headers.

## Immutable snapshots

The adapter resolves the default branch to a 40-character commit SHA and
downloads the tarball for that exact commit. Extraction:

- rejects absolute paths, traversal, selected-dependency path collisions, and
  root escapes;
- accepts only directories and regular files;
- excludes links, special files, credentials, repository-provided agent
  controls, ordinary oversized files, and every member of a normalized
  case-insensitive path collision;
- applies member-count, per-file, dependency-file, downloaded-byte, and
  expanded-byte limits;
- does not apply archive ownership, modes, timestamps, or link metadata;
- makes the completed snapshot read-only.

The temporary source tree is removed after report or failure publication.

The larger dependency-file allowance applies only to contracted dependency
paths: npm lockfiles and manifests, `pyproject.toml`, `poetry.lock`, `uv.lock`,
and the exact alert-selected pip requirements input. Unrelated `.txt` files
retain the ordinary per-file limit. If an excluded path prevents complete
repository coverage, negative reference evidence remains insufficient.
