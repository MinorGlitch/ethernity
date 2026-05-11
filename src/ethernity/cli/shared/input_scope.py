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

"""Shared selected input scope and diff helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ethernity.cli.shared.io.inputs import _load_input_files
from ethernity.cli.shared.paths import expanduser_cli_path
from ethernity.cli.shared.types import InputFile
from ethernity.core.validation import normalize_path


@dataclass(frozen=True)
class SelectedInputScope:
    """Validated local input scope for backup-like file selection."""

    raw_files: tuple[str, ...]
    raw_directories: tuple[str, ...]
    base_dir_arg: str | None
    input_files: tuple[InputFile, ...]
    base_dir: Path | None
    input_origin: Literal["file", "directory", "mixed"]
    input_roots: tuple[str, ...]
    exact_paths: tuple[str, ...]
    directory_prefixes: tuple[str, ...]

    @property
    def total_bytes(self) -> int:
        return sum(len(item.data) for item in self.input_files)

    def contains_path(self, path: str) -> bool:
        if path in self.exact_paths:
            return True
        return any(
            _path_matches_directory_prefix(path, prefix) for prefix in self.directory_prefixes
        )

    def to_inspection_payload(self) -> dict[str, object]:
        return {
            "files": list(self.raw_files),
            "directories": list(self.raw_directories),
            "base_dir": self.base_dir_arg,
            "file_count": len(self.input_files),
            "total_bytes": self.total_bytes,
            "input_origin": self.input_origin,
            "input_roots": list(self.input_roots),
        }


@dataclass(frozen=True)
class InputScopeDiff:
    """Summary of desired local scope versus current logical file state."""

    new_paths: tuple[str, ...]
    changed_paths: tuple[str, ...]
    unchanged_paths: tuple[str, ...]
    missing_paths: tuple[str, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "new_paths": list(self.new_paths),
            "changed_paths": list(self.changed_paths),
            "unchanged_paths": list(self.unchanged_paths),
            "missing_paths": list(self.missing_paths),
            "new_count": len(self.new_paths),
            "changed_count": len(self.changed_paths),
            "unchanged_count": len(self.unchanged_paths),
            "missing_count": len(self.missing_paths),
        }


def empty_scope_inspection_payload(*, base_dir_arg: str | None) -> dict[str, object]:
    return {
        "files": [],
        "directories": [],
        "base_dir": base_dir_arg,
        "file_count": 0,
        "total_bytes": 0,
        "input_origin": None,
        "input_roots": [],
    }


def load_input_scope(
    *,
    raw_files: Sequence[str],
    raw_directories: Sequence[str],
    base_dir_arg: str | None,
    allow_stdin: bool,
) -> SelectedInputScope | None:
    """Load validated selected-scope inputs from raw CLI file and directory selections."""

    files = tuple(raw_files)
    directories = tuple(raw_directories)
    if not files and not directories:
        return None

    input_files, base_dir, input_origin, input_roots = _load_input_files(
        list(files),
        list(directories),
        base_dir_arg,
        allow_stdin=allow_stdin,
    )
    exact_paths, directory_prefixes = scope_path_selectors(
        raw_files=files,
        raw_directories=directories,
        base_dir=base_dir,
    )
    return SelectedInputScope(
        raw_files=files,
        raw_directories=directories,
        base_dir_arg=base_dir_arg,
        input_files=tuple(input_files),
        base_dir=base_dir,
        input_origin=input_origin,
        input_roots=tuple(input_roots),
        exact_paths=exact_paths,
        directory_prefixes=directory_prefixes,
    )


def summarize_input_scope_diff(
    *,
    current_files: Mapping[str, tuple[bytes, int | None]],
    scope: SelectedInputScope,
) -> InputScopeDiff:
    """Compare selected local scope against a path-indexed current file state."""

    desired_by_path = {item.relative_path: item for item in scope.input_files}

    new_paths: list[str] = []
    changed_paths: list[str] = []
    unchanged_paths: list[str] = []
    for path in sorted(desired_by_path):
        desired = desired_by_path[path]
        current = current_files.get(path)
        if current is None:
            new_paths.append(path)
            continue
        current_data, current_mtime = current
        if current_data == desired.data and current_mtime == desired.mtime:
            unchanged_paths.append(path)
            continue
        changed_paths.append(path)

    missing_paths = sorted(
        path for path in current_files if path not in desired_by_path and scope.contains_path(path)
    )

    return InputScopeDiff(
        new_paths=tuple(new_paths),
        changed_paths=tuple(changed_paths),
        unchanged_paths=tuple(unchanged_paths),
        missing_paths=tuple(missing_paths),
    )


def scope_path_selectors(
    *,
    raw_files: tuple[str, ...],
    raw_directories: tuple[str, ...],
    base_dir: Path | None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    exact_paths: list[str] = []
    directory_prefixes: list[str] = []

    for raw in raw_files:
        if raw == "-":
            continue
        path = _resolved_cli_path(raw)
        if path.is_dir():
            directory_prefixes.append(_relative_scope_selector(path, base_dir=base_dir))
            continue
        exact_paths.append(_relative_scope_selector(path, base_dir=base_dir))

    for raw in raw_directories:
        directory_prefixes.append(
            _relative_scope_selector(_resolved_cli_path(raw), base_dir=base_dir)
        )

    return tuple(sorted(set(exact_paths))), tuple(sorted(set(directory_prefixes)))


def _resolved_cli_path(raw: str) -> Path:
    expanded = expanduser_cli_path(raw, preserve_stdin=False)
    return Path(expanded or "").resolve()


def _relative_scope_selector(path: Path, *, base_dir: Path | None) -> str:
    if base_dir is None:
        return normalize_path(path.name, label="relative path")
    if path == base_dir:
        return ""
    try:
        return normalize_path(path.relative_to(base_dir).as_posix(), label="relative path")
    except ValueError as exc:
        raise ValueError(f"selected scope path {path} is outside base dir {base_dir}") from exc


def _path_matches_directory_prefix(path: str, prefix: str) -> bool:
    if prefix == "":
        return True
    return path == prefix or path.startswith(f"{prefix}/")


__all__ = [
    "InputScopeDiff",
    "SelectedInputScope",
    "empty_scope_inspection_payload",
    "load_input_scope",
    "scope_path_selectors",
    "summarize_input_scope_diff",
]
