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

"""Selected-scope loading and diff helpers for extension planning."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from ethernity.cli.shared.input_scope import (
    InputScopeDiff,
    SelectedInputScope,
    empty_scope_inspection_payload,
    load_input_scope,
    summarize_input_scope_diff,
)
from ethernity.cli.shared.types import ExtendArgs
from ethernity.extensions.chain import LogicalFileState
from ethernity.extensions.discovery import EXTENSIONS_DIR_NAME

SelectedExtendScope = SelectedInputScope
ExtendScopeDiff = InputScopeDiff

_ROOT_ARTIFACT_FILENAMES = {
    "qr_document.pdf",
    "recovery_document.pdf",
    "recovery_kit_index.pdf",
}
_ROOT_ARTIFACT_PREFIXES = ("shard-", "signing-key-shard-")


def load_selected_scope(args: ExtendArgs) -> SelectedExtendScope | None:
    """Load validated selected-scope inputs from extend arguments."""

    root_dir = Path(args.root_dir).expanduser().resolve() if args.root_dir else None
    if root_dir is not None:
        _reject_selected_backup_root_artifact_paths(
            raw_files=args.input or (),
            raw_directories=args.input_dir or (),
            root_dir=root_dir,
        )
    scope = load_input_scope(
        raw_files=args.input or (),
        raw_directories=args.input_dir or (),
        base_dir_arg=args.base_dir,
        allow_stdin=True,
    )
    if scope is not None and root_dir is not None:
        _reject_backup_root_artifacts(scope, root_dir=root_dir)
    return scope


def _reject_selected_backup_root_artifact_paths(
    *,
    raw_files: Sequence[str],
    raw_directories: Sequence[str],
    root_dir: Path,
) -> None:
    artifact_paths: list[str] = []
    for raw_file in raw_files:
        if raw_file == "-":
            continue
        source_path = Path(raw_file).expanduser().resolve()
        if _is_backup_root_artifact_path(source_path, root_dir=root_dir):
            artifact_paths.append(_display_artifact_path(source_path, root_dir=root_dir))

    for raw_directory in raw_directories:
        directory_path = Path(raw_directory).expanduser().resolve()
        artifact_paths.extend(
            _selected_directory_backup_artifacts(directory_path, root_dir=root_dir)
        )

    _raise_if_backup_artifact_paths(artifact_paths)


def _reject_backup_root_artifacts(scope: SelectedExtendScope, *, root_dir: Path) -> None:
    artifact_paths: list[str] = []
    for item in scope.input_files:
        if item.source_path is None:
            continue
        source_path = item.source_path.resolve()
        if _is_backup_root_artifact_path(source_path, root_dir=root_dir):
            artifact_paths.append(_display_artifact_path(source_path, root_dir=root_dir))
    _raise_if_backup_artifact_paths(artifact_paths)


def _raise_if_backup_artifact_paths(artifact_paths: Sequence[str]) -> None:
    if artifact_paths:
        preview = ", ".join(artifact_paths[:5])
        suffix = "" if len(artifact_paths) <= 5 else f", and {len(artifact_paths) - 5} more"
        raise ValueError(
            f"extend input scope must not include backup root artifacts: {preview}{suffix}"
        )


def _selected_directory_backup_artifacts(path: Path, *, root_dir: Path) -> tuple[str, ...]:
    if not path.exists() or not path.is_dir():
        return ()
    if _path_contains_root(path, root_dir=root_dir):
        return _existing_root_backup_artifact_paths(root_dir)
    try:
        relative = path.relative_to(root_dir)
    except ValueError:
        return ()
    if relative.parts and relative.parts[0] == EXTENSIONS_DIR_NAME:
        return (_display_artifact_path(path, root_dir=root_dir),)
    return ()


def _path_contains_root(path: Path, *, root_dir: Path) -> bool:
    try:
        root_dir.relative_to(path)
    except ValueError:
        return False
    return True


def _existing_root_backup_artifact_paths(root_dir: Path) -> tuple[str, ...]:
    try:
        children = tuple(root_dir.iterdir())
    except OSError:
        return ()
    return tuple(
        _display_artifact_path(child, root_dir=root_dir)
        for child in children
        if _is_backup_root_artifact_path(child.resolve(), root_dir=root_dir)
    )


def _is_backup_root_artifact_path(path: Path, *, root_dir: Path) -> bool:
    try:
        relative = path.relative_to(root_dir)
    except ValueError:
        return False
    parts = relative.parts
    if not parts:
        return False
    if parts[0] == EXTENSIONS_DIR_NAME:
        return True
    if len(parts) != 1:
        return False
    name = parts[0]
    return name in _ROOT_ARTIFACT_FILENAMES or (
        name.endswith(".pdf") and name.startswith(_ROOT_ARTIFACT_PREFIXES)
    )


def _display_artifact_path(path: Path, *, root_dir: Path) -> str:
    try:
        return path.relative_to(root_dir).as_posix()
    except ValueError:
        return str(path)


def summarize_scope_diff(
    current_state: Sequence[LogicalFileState],
    scope: SelectedExtendScope,
) -> ExtendScopeDiff:
    """Compare the selected local scope against the current logical chain state."""

    return summarize_input_scope_diff(
        current_files={item.path: (item.data, item.mtime) for item in current_state},
        scope=scope,
    )


__all__ = [
    "ExtendScopeDiff",
    "SelectedExtendScope",
    "empty_scope_inspection_payload",
    "load_selected_scope",
    "summarize_scope_diff",
]
