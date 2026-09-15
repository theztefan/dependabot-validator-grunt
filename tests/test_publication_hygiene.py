from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]
LEGACY_CODENAME = "She" + "ll"
LEGACY_INTERNAL_PROJECTS = ("ghas-" + "report-grunt", "thez" + "tefan")
FORBIDDEN_PATTERNS = {
    "internal codename": re.compile(
        rf"\b(?:{LEGACY_CODENAME} Dependabot|{LEGACY_CODENAME} project|for {LEGACY_CODENAME})\b"
    ),
    "private GitHub repository": re.compile(
        r"github\.com/github/(?!gitignore(?:/|$))", re.IGNORECASE
    ),
    "private GitHub host": re.compile(
        r"\b(?:github\.local|stafftools|internal-only|employee-only)\b", re.IGNORECASE
    ),
    "historical internal project": re.compile(
        rf"\b(?:{'|'.join(re.escape(value) for value in LEGACY_INTERNAL_PROJECTS)})\b",
        re.IGNORECASE,
    ),
    "removed reference": re.compile(
        r"(?:artifacts-and-evaluation|decision-policy|reachability-tools)\.md"
    ),
}
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def _publishable_files() -> tuple[Path, ...]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(ROOT / line for line in result.stdout.splitlines() if line)


def _publishable_text_files() -> tuple[Path, ...]:
    text_files: list[Path] = []
    for path in _publishable_files():
        if not path.is_file() or path == Path(__file__):
            continue
        content = path.read_bytes()
        if b"\0" in content:
            continue
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            continue
        text_files.append(path)
    return tuple(text_files)


def test_publishable_text_has_no_internal_references() -> None:
    violations: list[str] = []
    for path in _publishable_text_files():
        text = path.read_text(encoding="utf-8")
        for label, pattern in FORBIDDEN_PATTERNS.items():
            if pattern.search(text):
                violations.append(f"{path.relative_to(ROOT)}: {label}")
    assert violations == []


def test_publishable_markdown_links_resolve() -> None:
    missing: list[str] = []
    for path in _publishable_text_files():
        if path.suffix != ".md":
            continue
        text = path.read_text(encoding="utf-8")
        for target in MARKDOWN_LINK.findall(text):
            if "://" in target or target.startswith(("#", "mailto:")):
                continue
            relative_target = target.split("#", 1)[0]
            if relative_target and not (path.parent / relative_target).resolve().exists():
                missing.append(f"{path.relative_to(ROOT)}: {target}")
    assert missing == []
