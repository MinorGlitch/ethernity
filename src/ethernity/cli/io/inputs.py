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

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from rich.progress import Progress, TaskID

from ...core.validation import normalize_path
from ..core.types import InputFile

# Progress reporting intervals
SCAN_UPDATE_INTERVAL = 1
READ_PROGRESS_UPDATE_INTERVAL = 10  # Update more frequently for better UX


@dataclass
class _ScanTracker:
    progress: Progress | None
    task_id: TaskID | None
    update_interval: int
    scanned: int = 0

    def tick(self) -> None:
        self.scanned += 1
        if self.progress is None or self.task_id is None:
            return
        if self.scanned == 1 or self.scanned % self.update_interval == 0:
            self.progress.update(
                self.task_id,
                description=f"Scanning input files... ({self.scanned} found)",
            )
            self.progress.refresh()


def _load_input_files(
    input_paths: list[str],
    input_dirs: list[str],
    base_dir: str | None,
    *,
    allow_stdin: bool,
    progress: Progress | None = None,
) -> tuple[list[InputFile], Path | None, Literal["file", "directory", "mixed"], list[str]]:
    paths: list[Path] = []
    stdin_requested = False
    has_directory_source = False
    has_file_source = False
    input_roots: list[str] = []
    has_scan_inputs = any(raw != "-" for raw in input_paths) or bool(input_dirs)
    scan_task_id = (
        progress.add_task("Scanning input files...", total=None)
        if progress and has_scan_inputs
        else None
    )
    if progress is not None and scan_task_id is not None:
        progress.refresh()
    tracker = _ScanTracker(progress, scan_task_id, SCAN_UPDATE_INTERVAL)

    for raw in input_paths:
        if raw == "-":
            stdin_requested = True
            has_file_source = True
            continue
        path = Path(raw).expanduser()
        if path.is_dir():
            has_directory_source = True
            input_roots.append(_directory_root_label(path))
            paths.extend(_walk_directory(path, on_file=tracker.tick))
        else:
            has_file_source = True
            paths.append(path)
            tracker.tick()

    for raw in input_dirs:
        path = Path(raw).expanduser()
        if not path.exists():
            raise ValueError(f"input dir not found: {path}")
        if not path.is_dir():
            raise ValueError(f"input dir is not a directory: {path}")
        has_directory_source = True
        input_roots.append(_directory_root_label(path))
        paths.extend(_walk_directory(path, on_file=tracker.tick))

    if stdin_requested and not allow_stdin:
        raise ValueError("stdin input is not supported here")

    if not paths and not stdin_requested:
        raise ValueError("no input files found")

    scanned = tracker.scanned
    if progress is not None and scan_task_id is not None:
        progress.update(
            scan_task_id,
            total=scanned,
            completed=scanned,
            description=f"Scanning input files... ({scanned} found)",
        )
        progress.refresh()

    base = _resolve_base_dir(paths, base_dir)
    entries: list[InputFile] = []
    seen: dict[str, Path] = {}
    total = len(paths)
    read_task_id = progress.add_task("Reading input files...", total=total) if progress else None
    if progress is not None and read_task_id is not None:
        progress.refresh()
    read = 0
    for path in paths:
        if not path.exists():
            raise ValueError(f"input file not found: {path}")
        if not path.is_file():
            raise ValueError(f"input path is not a file: {path}")
        abs_path = path.resolve()
        rel = _relative_path(abs_path, base)
        if rel in seen:
            raise ValueError(f"duplicate relative path '{rel}' from {seen[rel]} and {abs_path}")
        data = abs_path.read_bytes()
        mtime = int(abs_path.stat().st_mtime)
        entries.append(
            InputFile(
                source_path=abs_path,
                relative_path=rel,
                data=data,
                mtime=mtime,
            )
        )
        seen[rel] = abs_path
        read += 1
        if progress is not None and read_task_id is not None:
            progress.advance(read_task_id)
            if read == 1 or read % READ_PROGRESS_UPDATE_INTERVAL == 0 or read == total:
                progress.update(
                    read_task_id,
                    description=f"Reading input files... ({read}/{total})",
                )
                progress.refresh()

    if stdin_requested:
        rel = normalize_path("data.txt", label="relative path")
        if rel in seen:
            raise ValueError(f"duplicate relative path '{rel}' from stdin")
        data = sys.stdin.read().encode("utf-8")
        if not data:
            raise ValueError(
                "stdin input is empty; provide data with --input - or use --input/--input-dir"
            )
        entries.append(
            InputFile(
                source_path=None,
                relative_path=rel,
                data=data,
                mtime=None,
            )
        )

    entries.sort(key=lambda item: item.relative_path)
    if has_directory_source and has_file_source:
        input_origin: Literal["file", "directory", "mixed"] = "mixed"
    elif has_directory_source:
        input_origin = "directory"
    else:
        input_origin = "file"
    return entries, base, input_origin, input_roots


def _walk_directory(path: Path, *, on_file: Callable[[], None] | None = None) -> list[Path]:
    if not path.exists():
        raise ValueError(f"input dir not found: {path}")
    if not path.is_dir():
        raise ValueError(f"input dir is not a directory: {path}")
    files: list[Path] = []
    for root, _dirs, filenames in os.walk(path):
        for filename in filenames:
            files.append(Path(root) / filename)
            if on_file is not None:
                on_file()
    return files


def _resolve_base_dir(paths: list[Path], base_dir: str | None) -> Path | None:
    if base_dir:
        resolved = Path(base_dir).expanduser().resolve()
        if not resolved.exists():
            raise ValueError(f"base dir not found: {resolved}")
        if not resolved.is_dir():
            raise ValueError(f"base dir is not a directory: {resolved}")
        return resolved
    if not paths:
        return None
    parents = [str(path.resolve().parent) for path in paths]
    try:
        common = os.path.commonpath(parents)
    except ValueError as exc:
        raise ValueError("input paths are on different roots; provide --base-dir") from exc
    return Path(common)


def _relative_path(path: Path, base_dir: Path | None) -> str:
    if base_dir is None:
        rel = path.name
    else:
        try:
            rel_path = path.relative_to(base_dir)
        except ValueError as exc:
            raise ValueError(f"input file {path} is outside base dir {base_dir}") from exc
        rel = rel_path.as_posix()
    try:
        return normalize_path(rel, label="relative path")
    except ValueError as exc:
        raise ValueError(f"input file path is not valid UTF-8: {path!r}") from exc


def _directory_root_label(path: Path) -> str:
    resolved = path.expanduser().resolve()
    label = resolved.name.strip()
    if label:
        return label

    anchor = resolved.anchor.rstrip("/\\").strip()
    if anchor.endswith(":"):
        drive = anchor[:-1].strip().lower()
        if drive:
            return f"drive-{drive}"
    if anchor:
        compact_anchor = anchor.replace("\\", "-").replace("/", "-").replace(":", "")
        compact_anchor = compact_anchor.strip("-").lower()
        if compact_anchor:
            return f"root-{compact_anchor}"
    return "root"
