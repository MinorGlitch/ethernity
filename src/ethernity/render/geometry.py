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

from fpdf import FPDF

# Layout constants
FALLBACK_VERTICAL_PADDING_MM = 0.0

# Tolerance for coordinate comparisons (same row/column detection)
COORDINATE_EPSILON = 0.01


def calc_cells(usable: float, cell: float, gap: float, max_cells: int | None) -> int:
    count = int((usable + gap) // (cell + gap))
    if max_cells is not None:
        return min(count, int(max_cells))
    return count


def adjust_rows_for_fallback(
    rows: int,
    grid_start_y: float,
    page_h: float,
    margin: float,
    qr_size: float,
    gap: float,
    line_height: float,
    min_lines: int,
) -> int:
    while rows > 0:
        grid_height = rows * qr_size + (rows - 1) * gap
        leftover = page_h - grid_start_y - grid_height - margin
        safe_leftover = max(0.0, leftover - FALLBACK_VERTICAL_PADDING_MM)
        lines = int(safe_leftover // line_height)
        if lines >= min_lines:
            return rows
        rows -= 1
    raise ValueError("page too small for fallback text")


def fallback_lines_per_page(
    rows: int,
    grid_start_y: float,
    page_h: float,
    margin: float,
    qr_size: float,
    gap: float,
    line_height: float,
) -> int:
    grid_height = rows * qr_size + (rows - 1) * gap
    leftover = page_h - grid_start_y - grid_height - margin
    safe_leftover = max(0.0, leftover - FALLBACK_VERTICAL_PADDING_MM)
    return max(1, int(safe_leftover // line_height))


def fallback_lines_per_page_text_only(
    content_start_y: float,
    page_h: float,
    margin: float,
    line_height: float,
) -> int:
    leftover = page_h - content_start_y - margin
    safe_leftover = max(0.0, leftover - FALLBACK_VERTICAL_PADDING_MM)
    return max(1, int(safe_leftover // line_height))


def max_groups_for_width(pdf: FPDF, group_size: int, width_mm: float) -> int:
    group_width = pdf.get_string_width("M" * group_size)
    space_width = pdf.get_string_width(" ")
    if group_width <= 0:
        return 1
    if width_mm <= group_width:
        return 1
    return max(1, int((width_mm + space_width) // (group_width + space_width)))


def groups_from_line_length(line_length: int, group_size: int) -> int:
    if line_length <= group_size:
        return 1
    return max(1, (line_length + 1) // (group_size + 1))


def line_length_from_groups(groups: int, group_size: int) -> int:
    return max(group_size, groups * (group_size + 1) - 1)
