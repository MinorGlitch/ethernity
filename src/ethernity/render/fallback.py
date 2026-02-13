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

from dataclasses import dataclass, field
from typing import Sequence

from ..encoding.framing import encode_frame
from ..encoding.zbase32 import encode_zbase32
from .fallback_text import format_zbase32_lines
from .spec import DocumentSpec, FallbackSpec
from .text import font_line_height
from .types import FallbackSection, Layout, RenderInputs


@dataclass
class FallbackConsumerState:
    """Mutable state for consuming fallback blocks across pages."""

    section_idx: int = 0
    token_idx: int = 0
    line_numbers: list[int] = field(default_factory=list)

    def current_line_number(self, section_idx: int) -> int:
        """Get line number for a section, initializing if needed."""
        while len(self.line_numbers) <= section_idx:
            self.line_numbers.append(0)
        return self.line_numbers[section_idx]

    def advance_line_number(self, section_idx: int, count: int) -> None:
        """Advance line number for a section."""
        while len(self.line_numbers) <= section_idx:
            self.line_numbers.append(0)
        self.line_numbers[section_idx] += count


@dataclass(frozen=True)
class FallbackSectionData:
    """Data for a fallback section."""

    title: str
    tokens: tuple[str, ...]
    group_size: int


@dataclass
class FallbackBlock:
    """A block of fallback lines for rendering."""

    title: str | None
    section_title: str
    lines: list[str]
    gap_lines: int
    line_offset: int
    y_mm: float = 0.0
    height_mm: float = 0.0


def label_line_height_fallback(cfg: FallbackSpec) -> float:
    if cfg.label_line_height_mm is not None:
        return float(cfg.label_line_height_mm)
    label_size = cfg.label_size if cfg.label_size > 0 else cfg.font_size
    return font_line_height(label_size)


def fallback_lines_from_sections(
    sections: Sequence[FallbackSection],
    *,
    group_size: int,
    line_length: int,
) -> list[str]:
    lines: list[str] = []
    for idx, section in enumerate(sections):
        if section.label:
            lines.append(section.label)
        section_lines = format_zbase32_lines(
            encode_zbase32(encode_frame(section.frame)),
            group_size=group_size,
            line_length=line_length,
            line_count=None,
        )
        lines.extend(section_lines)
        if idx < len(sections) - 1:
            lines.append("")
    return lines


def build_fallback_sections_data(
    inputs: RenderInputs,
    spec: DocumentSpec,
    layout: Layout,
) -> tuple[list[FallbackSectionData], FallbackConsumerState] | None:
    if not (inputs.render_fallback and inputs.fallback_sections):
        return None
    group_size = int(spec.fallback.group_size)
    sections: list[FallbackSectionData] = []
    for section in inputs.fallback_sections:
        title = fallback_section_title(section.label)
        tokens = _tokenize_encoded_payload(
            encode_zbase32(encode_frame(section.frame)),
            group_size=group_size,
        )
        sections.append(FallbackSectionData(title=title, tokens=tokens, group_size=group_size))
    state = FallbackConsumerState()
    return sections, state


def fallback_section_title(label: str | None) -> str:
    if isinstance(label, str) and label.strip():
        return label.strip()
    return "Fallback Frame"


def fallback_sections_remaining(
    sections: list[FallbackSectionData],
    state: FallbackConsumerState,
) -> bool:
    if state.section_idx >= len(sections):
        return False
    current_section = sections[state.section_idx]
    if state.token_idx < len(current_section.tokens):
        return True
    for section in sections[state.section_idx + 1 :]:
        if section.tokens:
            return True
    return False


def consume_fallback_blocks(
    sections: list[FallbackSectionData],
    state: FallbackConsumerState,
    lines_capacity: int,
    line_length: int,
) -> list[FallbackBlock]:
    blocks: list[FallbackBlock] = []
    lines_left = lines_capacity
    first_block = True

    while lines_left > 0 and state.section_idx < len(sections):
        # Add gap between sections (not before first)
        if not first_block:
            if lines_left <= 1:
                break
            lines_left -= 1
            gap_lines = 1
        else:
            gap_lines = 0

        section = sections[state.section_idx]

        # Skip empty sections
        if not section.tokens:
            state.section_idx += 1
            state.token_idx = 0
            first_block = False
            continue

        remaining = len(section.tokens) - state.token_idx
        if remaining <= 0:
            state.section_idx += 1
            state.token_idx = 0
            first_block = False
            continue

        # Check if we need to show title (only at start of section)
        show_title = state.token_idx == 0
        title_lines = 1 if show_title else 0

        # Need room for at least title + 1 line
        if lines_left <= title_lines:
            break

        lines_left -= title_lines
        chunk, next_token_idx = _consume_section_lines(
            section,
            start_token_idx=state.token_idx,
            line_length=line_length,
            max_lines=lines_left,
        )
        if not chunk:
            break

        line_offset = state.current_line_number(state.section_idx)
        blocks.append(
            FallbackBlock(
                title=section.title if show_title else None,
                section_title=section.title,
                lines=chunk,
                gap_lines=gap_lines,
                line_offset=line_offset,
            )
        )

        state.advance_line_number(state.section_idx, len(chunk))
        state.token_idx = next_token_idx
        lines_left -= len(chunk)
        first_block = False

        # Move to next section if current is exhausted
        if state.token_idx >= len(section.tokens):
            state.section_idx += 1
            state.token_idx = 0

    return blocks


def _tokenize_encoded_payload(encoded: str, *, group_size: int) -> tuple[str, ...]:
    if group_size <= 0:
        raise ValueError("group_size must be positive")
    if not encoded:
        return ()
    return tuple(encoded[idx : idx + group_size] for idx in range(0, len(encoded), group_size))


def _consume_section_lines(
    section: FallbackSectionData,
    *,
    start_token_idx: int,
    line_length: int,
    max_lines: int,
) -> tuple[list[str], int]:
    if line_length <= 0 or max_lines <= 0 or start_token_idx >= len(section.tokens):
        return [], start_token_idx

    lines: list[str] = []
    token_idx = start_token_idx
    while token_idx < len(section.tokens) and len(lines) < max_lines:
        parts: list[str] = []
        line_chars = 0
        while token_idx < len(section.tokens):
            token = section.tokens[token_idx]
            candidate_chars = line_chars + (len(token) if not parts else len(token) + 1)
            if parts and candidate_chars > line_length:
                break
            if not parts and len(token) > line_length:
                break
            parts.append(token)
            line_chars = candidate_chars
            token_idx += 1

        if not parts:
            # Defensive fallback; should never happen with valid group_size/line_length.
            parts.append(section.tokens[token_idx])
            token_idx += 1
        lines.append(" ".join(parts))
    return lines, token_idx


def position_fallback_blocks(
    blocks: list[FallbackBlock],
    start_y: float,
    available_height: float,
    line_height: float,
) -> None:
    cursor_y = start_y
    remaining = max(0.0, available_height)

    for block in blocks:
        if block.gap_lines > 0:
            gap_mm = block.gap_lines * line_height
            cursor_y += gap_mm
            remaining -= gap_mm

        title_lines = 1 if block.title else 0
        block_height = (title_lines + len(block.lines)) * line_height
        block.y_mm = cursor_y
        block.height_mm = block_height
        cursor_y += block_height
        remaining -= block_height

    if blocks and remaining > 0:
        blocks[-1].height_mm += remaining
