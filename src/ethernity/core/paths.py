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

"""Adapter-neutral user-path normalization helpers."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path


def expand_user_path(path: str | Path | None, *, preserve_stdin: bool = True) -> str | None:
    """Expand a user path while optionally preserving the stdin sentinel."""

    if path is None:
        return None
    text = str(path)
    if preserve_stdin and text == "-":
        return text
    return str(Path(text).expanduser())


def expand_user_paths(paths: Sequence[str] | None) -> list[str]:
    """Expand a sequence of user paths."""

    if not paths:
        return []
    return [expand_user_path(path) or str(path) for path in paths]


__all__ = ["expand_user_path", "expand_user_paths"]
