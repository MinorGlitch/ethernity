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

"""Shared CLI path normalization helpers."""

from __future__ import annotations

from pathlib import Path


def expanduser_cli_path(path: str | Path | None, *, preserve_stdin: bool = True) -> str | None:
    """Normalize a user-provided CLI path while preserving stdin sentinels when requested."""

    if path is None:
        return None
    text = str(path)
    if preserve_stdin and text == "-":
        return text
    return str(Path(text).expanduser())


def expanduser_cli_paths(paths: list[str] | tuple[str, ...] | None) -> list[str]:
    """Normalize a sequence of user-provided CLI paths."""

    if not paths:
        return []
    return [expanduser_cli_path(path) or str(path) for path in paths]
