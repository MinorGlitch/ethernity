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

import re
from collections.abc import Sequence

from ethernity.core.bounds import MAX_FALLBACK_LINES, MAX_FALLBACK_NORMALIZED_CHARS
from ethernity.encoding.chunking import fallback_lines_to_frame
from ethernity.encoding.framing import Frame
from ethernity.encoding.zbase32 import ZBASE32_ALPHABET

_FALLBACK_SECTION_PATTERNS = {
    "auth": re.compile(r"^[=\-:\s]*auth frame[=\-:\s]*$", re.IGNORECASE),
    "key": re.compile(r"^[=\-:\s]*(?:key|shard) frame[=\-:\s]*$", re.IGNORECASE),
    "main": re.compile(r"^[=\-:\s]*main frame[=\-:\s]*$", re.IGNORECASE),
}


def _is_valid_zbase32_line(line: str) -> bool:
    """Check if line contains only allowed z-base-32 characters."""
    stripped = line.strip()
    if not stripped:
        return False
    has_payload_char = False
    for ch in stripped:
        if ch.isspace() or ch == "-":
            continue
        if ch.lower() not in ZBASE32_ALPHABET:
            return False
        has_payload_char = True
    return has_payload_char


def filter_fallback_lines(lines: Sequence[str]) -> list[str]:
    """Filter lines to valid z-base-32 fallback content."""
    filtered: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if not _is_valid_zbase32_line(stripped):
            raise ValueError(
                "fallback text contains non-empty lines with characters "
                "outside the z-base-32 alphabet"
            )

        filtered.append(stripped)

    return filtered


def _normalized_zbase_chars(lines: Sequence[str]) -> int:
    return sum(1 for line in lines for ch in line if not ch.isspace() and ch != "-")


def parse_fallback_frame(lines: Sequence[str], *, label: str) -> Frame:
    filtered = filter_fallback_lines(lines)
    if not filtered:
        raise ValueError(f"no recovery lines found ({label}); check the z-base-32 recovery text")
    if len(filtered) > MAX_FALLBACK_LINES:
        raise ValueError(
            f"{label} fallback exceeds MAX_FALLBACK_LINES ({MAX_FALLBACK_LINES}): "
            f"{len(filtered)} lines"
        )
    normalized_chars = _normalized_zbase_chars(filtered)
    if normalized_chars > MAX_FALLBACK_NORMALIZED_CHARS:
        raise ValueError(
            f"{label} fallback exceeds MAX_FALLBACK_NORMALIZED_CHARS "
            f"({MAX_FALLBACK_NORMALIZED_CHARS}): {normalized_chars} chars"
        )
    return fallback_lines_to_frame(filtered)


def format_fallback_error(exc: Exception, *, context: str) -> str:
    message = str(exc)
    if message in {"bad magic", "frame length mismatch"}:
        return (
            f"{context} is incomplete or invalid for this document. "
            "If you have not pasted the full text yet, this is normal - keep adding lines."
        )
    return message


def detect_fallback_section(line: str) -> str | None:
    normalized = line.strip()
    for section, pattern in _FALLBACK_SECTION_PATTERNS.items():
        if pattern.fullmatch(normalized):
            return section
    return None


def contains_fallback_markers(lines: Sequence[str]) -> bool:
    return any(detect_fallback_section(line) for line in lines)


def split_fallback_sections(lines: Sequence[str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {"auth": [], "key": [], "main": []}
    current: str | None = None
    for line in lines:
        section = detect_fallback_section(line)
        if section:
            current = section
            continue
        if current is None:
            if line.strip():
                raise ValueError("unexpected content before the first marked fallback section")
            continue
        if current:
            sections[current].append(line)
    return sections
