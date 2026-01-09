#!/usr/bin/env python3
from __future__ import annotations

from collections.abc import Sequence

from ...encoding.chunking import fallback_lines_to_frame
from ...encoding.fallback import ZBASE32_ALPHABET
from ...encoding.framing import Frame


def filter_fallback_lines(lines: Sequence[str]) -> tuple[list[str], int]:
    allowed = set(ZBASE32_ALPHABET + " -")
    filtered: list[str] = []
    skipped = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if all(ch.lower() in allowed for ch in stripped):
            filtered.append(stripped)
        else:
            skipped += 1
    return filtered, skipped


def parse_fallback_frame(lines: Sequence[str], *, label: str) -> tuple[Frame, int]:
    filtered, skipped = filter_fallback_lines(lines)
    if not filtered:
        raise ValueError(f"no fallback lines found ({label}); check the z-base-32 fallback text")
    return fallback_lines_to_frame(filtered), skipped


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
