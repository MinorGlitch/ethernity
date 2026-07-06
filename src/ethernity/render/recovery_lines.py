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

"""Shared recovery document key-line helpers."""

from __future__ import annotations


def format_grouped_lines(
    encoded: str,
    *,
    group_size: int,
    line_length: int,
) -> list[str]:
    if not encoded:
        return []
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
    return lines


def format_hex_lines(
    data: bytes,
    *,
    group_size: int = 4,
    line_length: int = 80,
) -> list[str]:
    encoded = data.hex()
    return format_grouped_lines(encoded, group_size=group_size, line_length=line_length)


def append_signing_key_lines(
    key_lines: list[str],
    *,
    sign_pub: bytes,
    sealed: bool,
    stored_in_main: bool,
    stored_as_shards: bool = False,
    not_stored_message: str = "Signing private key not stored.",
) -> None:
    key_lines.append("Signing public key (hex):")
    key_lines.extend(format_hex_lines(sign_pub))
    if sealed:
        key_lines.append("Signing private key not stored (sealed backup).")
        return

    if stored_in_main:
        key_lines.append("Signing private key stored in main document.")
    if stored_as_shards:
        key_lines.append("Signing private key stored in separate shard documents.")
    if not stored_in_main and not stored_as_shards:
        key_lines.append(not_stored_message)
