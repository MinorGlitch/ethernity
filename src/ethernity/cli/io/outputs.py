#!/usr/bin/env python3
# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program.
# If not, see <https://www.gnu.org/licenses/>.

"""Write backup and recovery outputs to disk or stdout safely."""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from ...core.validation import normalize_path
from ..core.paths import expanduser_cli_path


def _harden_dir_permissions(path: Path) -> None:
    """Apply restrictive directory permissions on POSIX systems."""

    if os.name != "posix":
        return
    try:
        path.chmod(0o700)
    except OSError:
        return


def _harden_file_permissions(path: Path) -> None:
    """Apply restrictive file permissions on POSIX systems."""

    if os.name != "posix":
        return
    try:
        path.chmod(0o600)
    except OSError:
        return


def _ensure_directory(path: str | Path, *, exist_ok: bool) -> Path:
    """Create an output directory and harden its permissions."""

    directory = Path(expanduser_cli_path(path, preserve_stdin=False) or "")
    directory.mkdir(parents=True, exist_ok=exist_ok, mode=0o700)
    _harden_dir_permissions(directory)
    return directory


def _ensure_output_dir(output_dir: str | None, doc_id_hex: str) -> str:
    """Create a fresh backup output directory or raise if it already exists."""

    directory = expanduser_cli_path(output_dir, preserve_stdin=False) or f"backup-{doc_id_hex}"
    try:
        _ensure_directory(directory, exist_ok=False)
    except FileExistsError as exc:
        raise ValueError(
            f"output directory already exists: {directory}; "
            "use a different --output-dir path or remove the existing directory"
        ) from exc
    return directory


def _safe_join(base: Path, relative: str) -> Path:
    """Join a manifest path under a base directory after path normalization checks."""

    relative = normalize_path(relative, label="output path")
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"unsafe output path: {relative}")
    path = base / rel
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _harden_dir_permissions(path.parent)
    return path


def _write_output(path: str | None, data: bytes, *, quiet: bool) -> None:
    """Write bytes to a file path or stdout when no path is provided."""

    import sys

    if path:
        normalized = Path(expanduser_cli_path(path, preserve_stdin=False) or "")
        with normalized.open("wb") as handle:
            handle.write(data)
        _harden_file_permissions(normalized)
    else:
        sys.stdout.buffer.write(data)


def _write_recovered_outputs(
    output_path: str | None,
    entries: Sequence[tuple[object, bytes]],
    *,
    quiet: bool,
    single_entry_output_is_directory: bool = False,
) -> None:
    """Write recovered manifest entries to a file, directory, or stdout."""

    if not entries:
        raise ValueError("no payloads to write")
    if output_path:
        if len(entries) == 1 and not single_entry_output_is_directory:
            _write_output(output_path, entries[0][1], quiet=quiet)
            return
        base_dir = _ensure_directory(output_path, exist_ok=True)
        for entry, data in entries:
            path = _safe_join(base_dir, getattr(entry, "path", "payload.bin"))
            _write_output(str(path), data, quiet=quiet)
        return

    if len(entries) == 1:
        _write_output(None, entries[0][1], quiet=quiet)
        return

    raise ValueError("multiple files require --output to specify a directory")
