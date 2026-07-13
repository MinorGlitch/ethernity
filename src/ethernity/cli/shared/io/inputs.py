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

import errno
import os
import stat as stat_module
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Literal

from rich.progress import Progress, TaskID

from ethernity.cli.shared.paths import expanduser_cli_path
from ethernity.cli.shared.types import InputFile
from ethernity.core.bounds import MAX_DECOMPRESSED_PAYLOAD_BYTES, MAX_MANIFEST_FILES
from ethernity.core.validation import normalize_path

__all__ = ["load_input_files"]

# Progress reporting intervals
SCAN_UPDATE_INTERVAL = 1
READ_PROGRESS_UPDATE_INTERVAL = 10  # Update more frequently for better UX


def _missing_path_error(path: Path, message: str) -> FileNotFoundError:
    return FileNotFoundError(errno.ENOENT, message, str(path))


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


@dataclass(frozen=True)
class _PlannedInputFile:
    source_path: Path
    absolute_path: Path
    relative_path: str
    file_stat: os.stat_result


def load_input_files(
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
        path = Path(expanduser_cli_path(raw, preserve_stdin=False) or "")
        _reject_symlink(path, "input path")
        if path.is_dir():
            has_directory_source = True
            input_roots.append(_directory_root_label(path))
            paths.extend(_walk_directory(path, on_file=tracker.tick))
        else:
            has_file_source = True
            paths.append(path)
            tracker.tick()

    for raw in input_dirs:
        path = Path(expanduser_cli_path(raw, preserve_stdin=False) or "")
        _reject_symlink(path, "input dir")
        if not path.exists():
            raise _missing_path_error(path, "input dir not found")
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
    planned_files = _plan_input_files(paths, base)
    entries: list[InputFile] = []
    total = len(paths)
    read_task_id = progress.add_task("Reading input files...", total=total) if progress else None
    if progress is not None and read_task_id is not None:
        progress.refresh()
    read = 0
    seen = {plan.relative_path: plan.absolute_path for plan in planned_files}
    total_input_bytes = sum(plan.file_stat.st_size for plan in planned_files)
    for plan in planned_files:
        data = _read_planned_input_file(plan)
        mtime = int(plan.file_stat.st_mtime)
        entries.append(
            InputFile(
                source_path=plan.absolute_path,
                relative_path=plan.relative_path,
                data=data,
                mtime=mtime,
            )
        )
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
        if len(planned_files) + 1 > MAX_MANIFEST_FILES:
            raise ValueError(
                f"input files exceed MAX_MANIFEST_FILES ({MAX_MANIFEST_FILES}): "
                f"{len(planned_files) + 1}"
            )
        data = _read_stdin_input_with_limit(total_input_bytes)
        if not data:
            raise ValueError(
                "stdin input is empty; provide data with --input - or use --input/--input-dir"
            )
        total_input_bytes += len(data)
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


def _plan_input_files(paths: list[Path], base_dir: Path | None) -> list[_PlannedInputFile]:
    planned: list[_PlannedInputFile] = []
    seen: dict[str, Path] = {}
    total_bytes = 0
    for path in paths:
        file_stat = _input_file_lstat(path)
        abs_path = path.resolve()
        rel = _relative_path(abs_path, base_dir)
        if rel in seen:
            raise ValueError(f"duplicate relative path '{rel}' from {seen[rel]} and {abs_path}")
        seen[rel] = abs_path
        planned.append(
            _PlannedInputFile(
                source_path=path,
                absolute_path=abs_path,
                relative_path=rel,
                file_stat=file_stat,
            )
        )
        if len(planned) > MAX_MANIFEST_FILES:
            raise ValueError(
                f"input files exceed MAX_MANIFEST_FILES ({MAX_MANIFEST_FILES}): {len(planned)}"
            )
        total_bytes += file_stat.st_size
        if total_bytes > MAX_DECOMPRESSED_PAYLOAD_BYTES:
            raise ValueError(
                "input files exceed MAX_DECOMPRESSED_PAYLOAD_BYTES "
                f"({MAX_DECOMPRESSED_PAYLOAD_BYTES}): {total_bytes} bytes"
            )
    return planned


def _input_file_lstat(path: Path) -> os.stat_result:
    try:
        file_stat = path.lstat()
    except FileNotFoundError:
        raise _missing_path_error(path, "input file not found") from None
    except PermissionError as exc:
        raise PermissionError(f"unable to read input file: {path}") from exc
    except OSError as exc:
        raise OSError(f"unable to read input file: {path}") from exc
    _validate_input_file_stat(path, file_stat)
    return file_stat


def _validate_input_file_stat(path: Path, file_stat: os.stat_result) -> None:
    if stat_module.S_ISLNK(file_stat.st_mode):
        raise ValueError(f"input file must not be a symlink: {path}")
    if not stat_module.S_ISREG(file_stat.st_mode):
        raise ValueError(f"input path is not a file: {path}")
    if file_stat.st_size > MAX_DECOMPRESSED_PAYLOAD_BYTES:
        raise ValueError(
            "input file exceeds MAX_DECOMPRESSED_PAYLOAD_BYTES "
            f"({MAX_DECOMPRESSED_PAYLOAD_BYTES}): {file_stat.st_size} bytes"
        )


def _read_planned_input_file(plan: _PlannedInputFile) -> bytes:
    fd = -1
    try:
        fd = os.open(plan.absolute_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        opened_stat = os.fstat(fd)
        _validate_input_file_stat(plan.source_path, opened_stat)
        if (
            opened_stat.st_dev,
            opened_stat.st_ino,
            opened_stat.st_size,
        ) != (
            plan.file_stat.st_dev,
            plan.file_stat.st_ino,
            plan.file_stat.st_size,
        ):
            raise ValueError(f"input file changed while opening: {plan.source_path}")
        with os.fdopen(fd, "rb") as handle:
            fd = -1
            data = _read_file_bytes_with_limit(handle, max_bytes=plan.file_stat.st_size)
    except FileNotFoundError:
        raise _missing_path_error(plan.source_path, "input file not found") from None
    except PermissionError as exc:
        raise PermissionError(f"unable to read input file: {plan.source_path}") from exc
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise ValueError(f"input file must not be a symlink: {plan.source_path}") from exc
        raise OSError(f"unable to read input file: {plan.source_path}") from exc
    finally:
        if fd >= 0:
            os.close(fd)
    if len(data) != plan.file_stat.st_size:
        raise ValueError(f"input file changed while reading: {plan.source_path}")
    return data


def _read_file_bytes_with_limit(handle: BinaryIO, *, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total_bytes = 0
    while True:
        remaining = max_bytes + 1 - total_bytes
        chunk = handle.read(min(64 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        total_bytes += len(chunk)
        if total_bytes > max_bytes:
            raise ValueError("input file changed while reading")
    return b"".join(chunks)


def _read_stdin_input_with_limit(existing_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total_bytes = existing_bytes
    while True:
        chunk = sys.stdin.read(64 * 1024)
        if not chunk:
            break
        data = chunk.encode("utf-8")
        chunks.append(data)
        total_bytes += len(data)
        if total_bytes > MAX_DECOMPRESSED_PAYLOAD_BYTES:
            raise ValueError(
                "input files exceed MAX_DECOMPRESSED_PAYLOAD_BYTES "
                f"({MAX_DECOMPRESSED_PAYLOAD_BYTES}): {total_bytes} bytes"
            )
    return b"".join(chunks)


def _walk_directory(path: Path, *, on_file: Callable[[], None] | None = None) -> list[Path]:
    _reject_symlink(path, "input dir")
    if not path.exists():
        raise _missing_path_error(path, "input dir not found")
    if not path.is_dir():
        raise ValueError(f"input dir is not a directory: {path}")
    files: list[Path] = []
    for root, dirs, filenames in os.walk(path):
        root_path = Path(root)
        for dirname in dirs:
            child = root_path / dirname
            _reject_symlink(child, "input directory entry")
        for filename in filenames:
            child = root_path / filename
            _reject_symlink(child, "input file")
            files.append(child)
            if on_file is not None:
                on_file()
    return files


def _resolve_base_dir(paths: list[Path], base_dir: str | None) -> Path | None:
    if base_dir:
        raw_base = Path(expanduser_cli_path(base_dir, preserve_stdin=False) or "")
        _reject_symlink(raw_base, "base dir")
        resolved = raw_base.resolve()
        if not resolved.exists():
            raise _missing_path_error(resolved, "base dir not found")
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


def _reject_symlink(path: Path, label: str) -> None:
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink: {path}")


def _directory_root_label(path: Path) -> str:
    resolved = path.expanduser().resolve()
    label = resolved.name
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
