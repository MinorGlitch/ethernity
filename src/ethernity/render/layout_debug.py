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

from collections.abc import Mapping
from pathlib import Path


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


def layout_debug_json_path(layout_debug_dir: str | Path | None, stem: str) -> str | None:
    """Return the JSON sidecar path for one layout-debug artifact."""

    if layout_debug_dir is None or not str(layout_debug_dir).strip():
        return None
    return str(Path(layout_debug_dir) / f"{stem}.layout.json")


__all__ = [
    "ensure_layout_debug_dir_allowed",
    "layout_debug_json_path",
    "resolve_layout_debug_dir",
]
