"""Bounded deterministic readers for dependency metadata files."""

from __future__ import annotations

import json
import os
import stat
import tomllib
from errno import ELOOP
from pathlib import Path

from pydantic import TypeAdapter


def bounded_text(path: Path, max_bytes: int) -> str:
    """Read one stable UTF-8 dependency file within its byte limit."""
    before = path.lstat()
    if stat.S_ISLNK(before.st_mode):
        raise ValueError("dependency file symlinks are denied")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        if error.errno == ELOOP:
            raise ValueError("dependency file symlinks are denied") from error
        raise
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (before.st_dev, before.st_ino) != (
            opened.st_dev,
            opened.st_ino,
        ):
            raise ValueError("dependency file identity changed before it was read")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if len(data) > max_bytes:
        raise ValueError("dependency file exceeds the configured byte limit")
    final = path.lstat()
    if (
        (opened.st_dev, opened.st_ino) != (after.st_dev, after.st_ino)
        or (opened.st_dev, opened.st_ino) != (final.st_dev, final.st_ino)
        or opened.st_size != after.st_size
        or opened.st_mtime_ns != after.st_mtime_ns
    ):
        raise ValueError("dependency file changed while it was read")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("dependency file is not valid UTF-8") from error


def bounded_json_object(path: Path, max_bytes: int) -> dict[str, object]:
    """Read one bounded JSON object."""
    try:
        raw = json.loads(bounded_text(path, max_bytes))
    except json.JSONDecodeError as error:
        raise ValueError("dependency file contains malformed JSON") from error
    return TypeAdapter(dict[str, object]).validate_python(raw)


def bounded_toml_object(path: Path, max_bytes: int) -> dict[str, object]:
    """Read one bounded TOML document."""
    try:
        raw = tomllib.loads(bounded_text(path, max_bytes))
    except tomllib.TOMLDecodeError as error:
        raise ValueError("dependency file contains malformed TOML") from error
    return TypeAdapter(dict[str, object]).validate_python(raw)
