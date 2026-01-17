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

from ..encoding.zbase32 import ZBASE32_ALPHABET


def format_zbase32_lines(
    text: str,
    *,
    group_size: int,
    line_length: int,
    line_count: int | None,
) -> list[str]:
    if group_size <= 0:
        raise ValueError("group_size must be positive")
    if line_length <= 0:
        raise ValueError("line_length must be positive")
    if group_size > line_length:
        raise ValueError("group_size must be <= line_length")
    if line_count is not None and line_count <= 0:
        raise ValueError("line_count must be positive")

    encoded_chars: list[str] = []
    for char in text:
        if char.isspace() or char == "-":
            continue
        lower = char.lower()
        if lower not in ZBASE32_ALPHABET:
            raise ValueError(f"invalid z-base-32 character: {char!r}")
        encoded_chars.append(lower)

    encoded = "".join(encoded_chars)
    groups = [encoded[i : i + group_size] for i in range(0, len(encoded), group_size)]

    lines: list[str] = []
    current = ""
    for group in groups:
        candidate = group if not current else f"{current} {group}"
        if len(candidate) > line_length:
            lines.append(current)
            current = group
        else:
            current = candidate

    if current:
        lines.append(current)

    if line_count is not None and len(lines) > line_count:
        raise ValueError("fallback text exceeds line_count")
    return lines
