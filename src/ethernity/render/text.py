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

from fpdf import FPDF

from .spec import HeaderSpec, PageSpec, TextBlockSpec


def page_format(page_cfg: PageSpec) -> str | tuple[float, float]:
    if page_cfg.width_mm and page_cfg.height_mm:
        return (float(page_cfg.width_mm), float(page_cfg.height_mm))
    return page_cfg.size


def wrap_lines_to_width(pdf: FPDF, lines: Sequence[str], max_width: float) -> list[str]:
    wrapped: list[str] = []
    for line in lines:
        if not line:
            wrapped.append("")
            continue
        words = line.split(" ")
        current = ""
        for word in words:
            candidate = word if not current else f"{current} {word}"
            if pdf.get_string_width(candidate) <= max_width:
                current = candidate
                continue
            if current:
                wrapped.append(current)
                current = ""
            if pdf.get_string_width(word) <= max_width:
                current = word
                continue
            parts: list[str] = []
            chunk = ""
            for ch in word:
                next_chunk = f"{chunk}{ch}"
                if chunk and pdf.get_string_width(next_chunk) > max_width:
                    parts.append(chunk)
                    chunk = ch
                else:
                    chunk = next_chunk
            if chunk:
                parts.append(chunk)
            wrapped.extend(parts[:-1])
            current = parts[-1] if parts else ""
        if current:
            wrapped.append(current)
    return wrapped


def text_block_width(cfg: TextBlockSpec, usable_w: float) -> float:
    width = usable_w - float(cfg.indent_mm)
    label = cfg.label
    label_layout = str(cfg.label_layout).lower()
    if label and label_layout == "column":
        width -= float(cfg.label_column_mm)
        width -= float(cfg.label_gap_mm)
    return max(1.0, width)


def is_fallback_label_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("===") and stripped.endswith("===") and len(stripped) > 6


def font_line_height(size_pt: float, multiplier: float = 1.2) -> float:
    pt_to_mm = 0.3527777778
    return float(size_pt) * pt_to_mm * multiplier


def body_line_height(cfg: TextBlockSpec) -> float:
    if cfg.line_height_mm is not None:
        return float(cfg.line_height_mm)
    return font_line_height(cfg.font_size)


def label_line_height_text(cfg: TextBlockSpec) -> float:
    if cfg.label_line_height_mm is not None:
        return float(cfg.label_line_height_mm)
    return font_line_height(cfg.label_size or cfg.font_size)


def header_height(cfg: HeaderSpec, minimum: float) -> float:
    height = 0.0
    title = cfg.title
    subtitle = cfg.subtitle
    doc_id_label = cfg.doc_id_label
    doc_id = cfg.doc_id or ""
    page_label = cfg.page_label or ""
    divider_enabled = bool(cfg.divider_enabled)
    meta_row_gap_mm = float(getattr(cfg, "meta_row_gap_mm", 0.0) or 0.0)
    stack_gap_mm = float(getattr(cfg, "stack_gap_mm", 0.0) or 0.0)

    title_height = font_line_height(cfg.title_size) if title else 0.0
    subtitle_height = font_line_height(cfg.subtitle_size) if subtitle else 0.0
    meta_lines = 0
    if doc_id_label or doc_id:
        meta_lines += 1
    if page_label:
        meta_lines += 1
    meta_lines += int(getattr(cfg, "meta_lines_extra", 0))
    meta_height = meta_lines * font_line_height(cfg.meta_size)
    meta_gaps = max(0, meta_lines - 1) * meta_row_gap_mm
    meta_total_height = meta_height + meta_gaps

    left_sections = int(title_height > 0) + int(subtitle_height > 0)
    left_gaps = max(0, left_sections - 1) * stack_gap_mm
    left_height = title_height + subtitle_height + left_gaps
    height += max(left_height, meta_total_height)

    if divider_enabled:
        height += float(cfg.divider_gap_mm)
        height += float(cfg.divider_thickness_mm)

    return max(height, minimum)


def instructions_height(cfg: TextBlockSpec) -> float:
    return lines_height(cfg, cfg.lines)


def lines_height(cfg: TextBlockSpec, lines: Sequence[str]) -> float:
    label = cfg.label
    if not lines and not label:
        return 0.0

    body_h = len(lines) * body_line_height(cfg) if lines else 0.0
    if not label:
        return body_h

    label_layout = str(cfg.label_layout).lower()
    label_h = label_line_height_text(cfg)
    if label_layout == "column":
        return max(body_h, label_h)

    gap = float(cfg.label_gap_mm)
    if body_h <= 0:
        return label_h
    return label_h + gap + body_h
