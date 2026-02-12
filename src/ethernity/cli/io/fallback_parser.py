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

from collections.abc import Sequence
from dataclasses import dataclass

from ...encoding.chunking import fallback_lines_to_frame
from ...encoding.framing import Frame
from ...encoding.zbase32 import ZBASE32_ALPHABET


@dataclass(frozen=True)
class FilterConfig:
    """Configuration for fallback line filtering."""

    max_group_length: int = 4
    min_groups: int = 3


_ALLOWED_CHARS = frozenset(ZBASE32_ALPHABET + " -")


def _is_valid_zbase32_line(line: str) -> bool:
    """Check if line contains only allowed z-base-32 characters."""
    stripped = line.strip()
    if not stripped:
        return False
    return all(ch.lower() in _ALLOWED_CHARS or ch.isspace() for ch in stripped)


def _parse_groups(line: str) -> list[str]:
    """Parse a line into groups (space/dash separated)."""
    return line.strip().replace("-", " ").split()


def _is_valid_group_structure(parts: list[str], config: FilterConfig) -> bool:
    """Check if groups meet length/structure requirements.

    Rules:
    - All parts must be <= max_group_length
    - At most one short part (< max_group_length) is allowed
    - If a short part exists, it must be at the end of the line
    """
    if not parts:
        return False
    if any(len(part) > config.max_group_length for part in parts):
        return False

    short_parts = [idx for idx, part in enumerate(parts) if len(part) < config.max_group_length]
    if len(short_parts) > 1:
        return False
    if short_parts and short_parts[0] != len(parts) - 1:
        return False
    return True


def _should_include_candidate(
    group_count: int,
    idx: int,
    total_candidates: int,
    has_filtered: bool,
    min_groups: int,
) -> bool:
    """Determine if a candidate line should be included.

    Lines with >= min_groups are always included.
    The final line can have fewer groups if we already have prior content.
    """
    if group_count >= min_groups:
        return True
    if idx == total_candidates - 1 and has_filtered:
        return True
    return False


def filter_fallback_lines(
    lines: Sequence[str],
    config: FilterConfig | None = None,
) -> tuple[list[str], int]:
    """Filter lines to valid z-base-32 fallback content.

    Args:
        lines: Input lines to filter
        config: Optional configuration (uses defaults if None)

    Returns:
        Tuple of (filtered_lines, skipped_count)
    """
    config = config or FilterConfig()
    filtered: list[str] = []
    candidates: list[tuple[str, int]] = []
    skipped = 0

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if not _is_valid_zbase32_line(line):
            skipped += 1
            continue

        parts = _parse_groups(stripped)
        if not _is_valid_group_structure(parts, config):
            skipped += 1
            continue

        candidates.append((stripped, len(parts)))

    for idx, (line, group_count) in enumerate(candidates):
        if _should_include_candidate(
            group_count, idx, len(candidates), bool(filtered), config.min_groups
        ):
            filtered.append(line)
        else:
            skipped += 1

    return filtered, skipped


def parse_fallback_frame(lines: Sequence[str], *, label: str) -> tuple[Frame, int]:
    filtered, skipped = filter_fallback_lines(lines)
    if not filtered:
        raise ValueError(f"no recovery lines found ({label}); check the z-base-32 recovery text")
    return fallback_lines_to_frame(filtered), skipped


def format_fallback_error(exc: Exception, *, context: str) -> str:
    message = str(exc)
    if message in {"bad magic", "frame length mismatch"}:
        return (
            f"{context} is incomplete or invalid for this document. "
            "If you have not pasted the full text yet, this is normal - keep adding lines."
        )
    return message


def detect_fallback_section(line: str) -> str | None:
    normalized = line.strip().lower()
    if "auth frame" in normalized:
        return "auth"
    if "main frame" in normalized:
        return "main"
    return None


def contains_fallback_markers(lines: Sequence[str]) -> bool:
    return any(detect_fallback_section(line) for line in lines)


def split_fallback_sections(lines: Sequence[str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {"auth": [], "main": []}
    current: str | None = None
    for line in lines:
        section = detect_fallback_section(line)
        if section:
            current = section
            continue
        if current:
            sections[current].append(line)
    return sections
