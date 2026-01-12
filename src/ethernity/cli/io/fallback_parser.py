#!/usr/bin/env python3
from __future__ import annotations

from collections.abc import Sequence

from ...encoding.chunking import fallback_lines_to_frame
from ...encoding.fallback import ZBASE32_ALPHABET
from ...encoding.framing import Frame


def filter_fallback_lines(lines: Sequence[str]) -> tuple[list[str], int]:
    allowed = set(ZBASE32_ALPHABET + " -")
    min_groups = 3
    filtered: list[str] = []
    candidates: list[tuple[str, int]] = []
    skipped = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if not all(ch.lower() in allowed or ch.isspace() for ch in stripped):
            skipped += 1
            continue
        parts = stripped.replace("-", " ").split()
        if not parts or any(len(part) > 4 for part in parts):
            skipped += 1
            continue
        short_parts = [idx for idx, part in enumerate(parts) if len(part) < 4]
        if len(short_parts) > 1 or (short_parts and short_parts[0] != len(parts) - 1):
            skipped += 1
            continue
        candidates.append((stripped, len(parts)))
    for idx, (line, group_count) in enumerate(candidates):
        if group_count >= min_groups:
            filtered.append(line)
            continue
        if idx == len(candidates) - 1 and filtered:
            filtered.append(line)
            continue
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
