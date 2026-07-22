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

"""Shared layout-debug path helpers."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path, PurePosixPath, PureWindowsPath

from ethernity.core.validation import has_windows_drive_prefix


def resolve_layout_debug_dir(
    path: str | Path | None,
    *,
    forbidden_dirs: Mapping[str, str | Path] | None = None,
) -> str | None:
    """Resolve and create a layout-debug directory after managed-inventory checks."""

    if path is None or not str(path).strip():
        return None
    resolved = Path(path).expanduser().resolve()
    ensure_layout_debug_dir_allowed(resolved, forbidden_dirs=forbidden_dirs)
    ensure_layout_debug_dir_ready(resolved)
    resolved.mkdir(parents=True, exist_ok=True)
    return str(resolved)


def ensure_layout_debug_dir_allowed(
    path: str | Path,
    *,
    forbidden_dirs: Mapping[str, str | Path] | None = None,
) -> None:
    """Reject debug directories inside managed artifact inventories."""

    debug_dir = Path(path).expanduser().resolve()
    for label, raw_dir in (forbidden_dirs or {}).items():
        managed_dir = Path(raw_dir).expanduser().resolve()
        if debug_dir == managed_dir or debug_dir.is_relative_to(managed_dir):
            raise ValueError(
                "layout debug directory must not be inside managed artifact inventory "
                f"{label}: {managed_dir}"
            )


def ensure_layout_debug_dir_ready(path: str | Path) -> None:
    """Validate that a layout-debug directory can be used without creating it."""

    debug_dir = Path(path).expanduser().resolve()
    if debug_dir.exists():
        if not debug_dir.is_dir():
            raise ValueError(f"layout debug directory must be a directory: {debug_dir}")
        if not os.access(debug_dir, os.W_OK | os.X_OK):
            raise ValueError(f"layout debug directory is not writable: {debug_dir}")
        return

    parent = debug_dir.parent
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    if not parent.exists() or not parent.is_dir():
        raise ValueError(f"layout debug directory parent must be a directory: {debug_dir.parent}")
    if not os.access(parent, os.W_OK | os.X_OK):
        raise ValueError(f"layout debug directory parent is not writable: {parent}")


def layout_debug_json_path(layout_debug_dir: str | Path | None, stem: str) -> str | None:
    """Return the JSON sidecar path for one layout-debug artifact."""

    if layout_debug_dir is None or not str(layout_debug_dir).strip():
        return None
    filename = f"{stem}.layout.json"
    if isinstance(layout_debug_dir, Path):
        return str(layout_debug_dir / filename)
    text = str(layout_debug_dir)
    if "\\" in text or has_windows_drive_prefix(text):
        return str(PureWindowsPath(text) / filename)
    if "/" in text:
        return str(PurePosixPath(text) / filename)
    return str(Path(text) / filename)


__all__ = [
    "ensure_layout_debug_dir_allowed",
    "layout_debug_json_path",
    "resolve_layout_debug_dir",
]
