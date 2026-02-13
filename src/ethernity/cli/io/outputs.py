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

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from ...core.validation import normalize_path
from ..api import console_err


def _ensure_directory(path: str | Path, *, exist_ok: bool) -> Path:
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=exist_ok)
    return directory


def _ensure_output_dir(output_dir: str | None, doc_id_hex: str) -> str:
    directory = output_dir or f"backup-{doc_id_hex}"
    try:
        _ensure_directory(directory, exist_ok=False)
    except FileExistsError as exc:
        raise ValueError(
            f"output directory already exists: {directory}; "
            "use a different --output path or remove the existing directory"
        ) from exc
    return directory


def _safe_join(base: Path, relative: str) -> Path:
    relative = normalize_path(relative, label="output path")
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"unsafe output path: {relative}")
    path = base / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _write_output(path: str | None, data: bytes, *, quiet: bool) -> None:
    import sys

    if path:
        with open(path, "wb") as handle:
            handle.write(data)
        if not quiet:
            console_err.print(f"[dim]- wrote {path}[/dim]")
    else:
        sys.stdout.buffer.write(data)


def _write_recovered_outputs(
    output_path: str | None,
    entries: Sequence[tuple[object, bytes]],
    *,
    quiet: bool,
    single_entry_output_is_directory: bool = False,
) -> None:
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
