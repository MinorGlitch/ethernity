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

from typing import Sequence

from ..encoding.framing import encode_frame
from ..encoding.zbase32 import encode_zbase32
from .fallback_text import format_zbase32_lines
from .spec import DocumentSpec, FallbackSpec
from .text import font_line_height
from .types import FallbackSection, Layout, RenderInputs
from .utils import float_value as _float_value, int_value as _int_value


def label_line_height_fallback(cfg: FallbackSpec) -> float:
    if cfg.label_line_height_mm is not None:
        return float(cfg.label_line_height_mm)
    return font_line_height(cfg.label_size or cfg.font_size)


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
) -> tuple[list[dict[str, object]] | None, dict[str, int] | None]:
    if not (inputs.render_fallback and inputs.fallback_sections):
        return None, None
    group_size = int(spec.fallback.group_size)
    line_length = int(layout.line_length)
    fallback_sections_data: list[dict[str, object]] = []
    for section in inputs.fallback_sections:
        title = fallback_section_title(section.label)
        lines = format_zbase32_lines(
            encode_zbase32(encode_frame(section.frame)),
            group_size=group_size,
            line_length=line_length,
            line_count=None,
        )
        fallback_sections_data.append({"title": title, "lines": lines})
    fallback_state = {"section_idx": 0, "line_idx": 0}
    for idx in range(len(fallback_sections_data)):
        fallback_state[f"line_number_{idx}"] = 0
    return fallback_sections_data, fallback_state


def fallback_section_title(label: str | None) -> str:
    if isinstance(label, str) and label.strip():
        return label.strip()
    return "Fallback Frame"


def fallback_sections_remaining(
    sections: list[dict[str, object]],
    state: dict[str, int],
) -> bool:
    idx = state.get("section_idx", 0)
    line_idx = state.get("line_idx", 0)
    if idx >= len(sections):
        return False
    current_lines = sections[idx].get("lines", [])
    if isinstance(current_lines, list) and line_idx < len(current_lines):
        return True
    for section in sections[idx + 1 :]:
        lines = section.get("lines", [])
        if isinstance(lines, list) and lines:
            return True
    return False


def consume_fallback_blocks(
    sections: list[dict[str, object]],
    state: dict[str, int],
    lines_capacity: int,
) -> list[dict[str, object]]:
    blocks: list[dict[str, object]] = []
    lines_left = lines_capacity
    first_block = True

    while lines_left > 0 and state["section_idx"] < len(sections):
        if not first_block:
            if lines_left <= 1:
                break
            lines_left -= 1
            gap_lines = 1
        else:
            gap_lines = 0

        section = sections[state["section_idx"]]
        section_title = section.get("title")
        line_number_key = f"line_number_{state['section_idx']}"
        line_number = _int_value(state.get(line_number_key), default=0)
        lines = section.get("lines", [])
        if not isinstance(lines, list) or not lines:
            state["section_idx"] += 1
            state["line_idx"] = 0
            first_block = False
            continue

        remaining = len(lines) - state["line_idx"]
        if remaining <= 0:
            state["section_idx"] += 1
            state["line_idx"] = 0
            first_block = False
            continue

        show_title = state["line_idx"] == 0
        title_lines = 1 if show_title else 0
        if lines_left <= title_lines:
            break
        if title_lines:
            lines_left -= title_lines
        chunk_size = min(lines_left, remaining)
        if chunk_size <= 0:
            lines_left += title_lines + gap_lines
            break

        start = state["line_idx"]
        end = start + chunk_size
        chunk = lines[start:end]
        state["line_idx"] = end

        blocks.append(
            {
                "title": section.get("title") if show_title else None,
                "section_title": section_title,
                "lines": chunk,
                "gap_lines": gap_lines,
                "line_offset": line_number,
            }
        )

        line_number += chunk_size
        state[line_number_key] = line_number
        lines_left -= chunk_size
        first_block = False

        if state["line_idx"] >= len(lines):
            state["section_idx"] += 1
            state["line_idx"] = 0

    return blocks


def position_fallback_blocks(
    blocks: list[dict[str, object]],
    start_y: float,
    available_height: float,
    line_height: float,
) -> None:
    cursor_y = start_y
    remaining = max(0.0, available_height)

    for block in blocks:
        gap_lines = _int_value(block.get("gap_lines"), default=0)
        if gap_lines > 0:
            gap_mm = gap_lines * line_height
            cursor_y += gap_mm
            remaining -= gap_mm

        lines = block.get("lines", [])
        line_count = len(lines) if isinstance(lines, list) else 0
        title_lines = 1 if block.get("title") else 0
        block_height = (title_lines + line_count) * line_height
        block["y_mm"] = cursor_y
        block["height_mm"] = block_height
        cursor_y += block_height
        remaining -= block_height

    if blocks and remaining > 0:
        blocks[-1]["height_mm"] = _float_value(blocks[-1].get("height_mm"), default=0.0) + remaining
