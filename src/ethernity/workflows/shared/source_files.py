"""Detect changed recovery carriers before reusing in-memory preparation."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable
from pathlib import Path


def source_files_version(paths: Iterable[str | Path | None]) -> str:
    """Include replacements, edits, and directory membership in a source revision.

    This is a cache invalidator, not a document fingerprint or authentication check.
    Prepared documents retain their immutable bytes and cryptographic identities.
    """
    digest = hashlib.sha256()
    for value in paths:
        if value is None:
            continue
        path = Path(value).expanduser()
        _add_path_version(digest, path)
        if path.is_dir():
            for root, directories, files in os.walk(path, followlinks=False):
                directories.sort()
                for name in sorted((*directories, *files)):
                    _add_path_version(digest, Path(root) / name)
    return digest.hexdigest()


def _add_path_version(digest, path: Path) -> None:
    try:
        stat = path.stat()
        version = (
            str(path.absolute()),
            stat.st_dev,
            stat.st_ino,
            stat.st_mode,
            stat.st_size,
            stat.st_mtime_ns,
            stat.st_ctime_ns,
        )
    except OSError as exc:
        version = (str(path.absolute()), type(exc).__name__, exc.errno)
    digest.update(repr(version).encode("utf-8"))
    digest.update(b"\0")
