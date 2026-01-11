#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from rich.progress import Progress, TaskID

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
) -> tuple[list[InputFile], Path | None]:
    paths: list[Path] = []
    stdin_requested = False
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
            continue
        path = Path(raw).expanduser()
        if path.is_dir():
            paths.extend(_walk_directory(path, on_file=tracker.tick))
        else:
            paths.append(path)
            tracker.tick()

    for raw in input_dirs:
        path = Path(raw).expanduser()
        if not path.exists():
            raise ValueError(f"input dir not found: {path}")
        if not path.is_dir():
            raise ValueError(f"input dir is not a directory: {path}")
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
        rel = "data.txt"
        if rel in seen:
            raise ValueError(f"duplicate relative path '{rel}' from stdin")
        data = sys.stdin.read().encode("utf-8")
        entries.append(
            InputFile(
                source_path=None,
                relative_path=rel,
                data=data,
                mtime=None,
            )
        )

    entries.sort(key=lambda item: item.relative_path)
    return entries, base


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
        return path.name
    try:
        rel = path.relative_to(base_dir)
    except ValueError as exc:
        raise ValueError(f"input file {path} is outside base dir {base_dir}") from exc
    return rel.as_posix()
