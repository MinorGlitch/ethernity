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

import math
from typing import Sequence

from fpdf import FPDF

from ..encoding.chunking import reassemble_payload
from ..encoding.framing import VERSION, Frame, encode_frame
from ..encoding.zbase32 import encode_zbase32
from .doc_types import DOC_TYPE_RECOVERY
from .fallback import (
    fallback_lines_from_sections,
    label_line_height_fallback,
)
from .fallback_text import format_zbase32_lines
from .geometry import (
    adjust_rows_for_fallback,
    calc_cells,
    fallback_lines_per_page,
    fallback_lines_per_page_text_only,
    groups_from_line_length,
    line_length_from_groups,
    max_groups_for_width,
)
from .layout_policy import (
    adjust_layout_fallback_capacity,
    fallback_text_width_override_mm,
    max_rows_override_for_template,
    resolve_layout_capabilities,
    should_force_max_rows,
)
from .spec import DocumentSpec
from .template_style import TemplateCapabilities
from .text import (
    header_height,
    instructions_height,
    is_fallback_label_line,
    lines_height,
    text_block_width,
    wrap_lines_to_width,
)
from .types import Layout, RenderInputs

__all__ = ["compute_layout"]


def _calculate_content_positions(
    pdf: FPDF,
    spec: DocumentSpec,
    key_lines: Sequence[str],
    *,
    include_keys: bool,
    include_instructions: bool,
) -> tuple[float, float, float, float, float, list[str]]:
    """Calculate content positions and wrap key lines.

    Returns:
        (margin, header_h, instructions_y, content_start_y, usable_w, wrapped_key_lines)
    """
    page_cfg = spec.page
    keys_cfg = spec.keys
    header_cfg = spec.header
    instructions_cfg = spec.instructions

    margin = float(page_cfg.margin_mm)
    header_min_height = float(page_cfg.header_height_mm)
    instructions_gap = float(page_cfg.instructions_gap_mm)
    keys_gap = float(page_cfg.keys_gap_mm)

    page_w = pdf.w
    usable_w = page_w - 2 * margin
    instructions_h = instructions_height(instructions_cfg) if include_instructions else 0.0

    wrapped_key_lines = list(key_lines)
    if include_keys and key_lines:
        keys_font = keys_cfg.font_family
        keys_size = float(keys_cfg.font_size)
        pdf.set_font(keys_font, size=keys_size)
        max_text_width = text_block_width(keys_cfg, usable_w)
        wrapped_key_lines = wrap_lines_to_width(pdf, key_lines, max_text_width)
    if include_keys:
        keys_height = lines_height(keys_cfg, wrapped_key_lines)
    else:
        wrapped_key_lines = list(key_lines)
        keys_height = 0.0

    header_h = header_height(header_cfg, header_min_height)
    content_start_y = margin + header_h
    instructions_y = content_start_y
    if instructions_h > 0:
        content_start_y += instructions_h + instructions_gap
    if include_keys and keys_height > 0:
        content_start_y += keys_height + keys_gap

    return margin, header_h, instructions_y, content_start_y, usable_w, wrapped_key_lines


def _calculate_fallback_line_length(
    pdf: FPDF,
    spec: DocumentSpec,
    page_w: float,
    margin: float,
    *,
    text_width_override_mm: float | None = None,
) -> tuple[int, int, float, str, float]:
    """Calculate fallback text parameters.

    Returns: (line_length, group_size, line_height, fallback_font, fallback_size)
    """
    fallback_cfg = spec.fallback
    group_size = int(fallback_cfg.group_size)
    line_length_cfg = int(fallback_cfg.line_length)
    line_height = float(fallback_cfg.line_height_mm)
    fallback_font = fallback_cfg.font_family
    fallback_size = float(fallback_cfg.font_size)

    pdf.set_font(fallback_font, size=fallback_size)
    original_cell_margin = pdf.c_margin
    pdf.c_margin = 0
    fallback_width = page_w - 2 * margin
    if text_width_override_mm is None:
        padding_mm = float(fallback_cfg.padding_mm)
        fallback_width_safe = max(1.0, fallback_width - (2 * float(padding_mm)))
    else:
        fallback_width_safe = max(1.0, float(text_width_override_mm))
    max_groups = max_groups_for_width(pdf, group_size, fallback_width_safe)
    if line_length_cfg > 0:
        max_groups = min(max_groups, groups_from_line_length(line_length_cfg, group_size))
    line_length = line_length_from_groups(max_groups, group_size)
    pdf.c_margin = original_cell_margin

    return line_length, group_size, line_height, fallback_font, fallback_size


def _build_fallback_lines(
    inputs: RenderInputs,
    group_size: int,
    line_length: int,
) -> list[str]:
    """Build fallback text lines from inputs."""
    if not inputs.render_fallback:
        return []

    if inputs.fallback_sections:
        return fallback_lines_from_sections(
            inputs.fallback_sections,
            group_size=group_size,
            line_length=line_length,
        )

    fallback_payload = inputs.fallback_payload
    if fallback_payload is None:
        fallback_payload = reassemble_payload(inputs.frames)
    frame = Frame(
        version=VERSION,
        frame_type=inputs.frames[0].frame_type,
        doc_id=inputs.frames[0].doc_id,
        index=0,
        total=1,
        data=fallback_payload,
    )
    return format_zbase32_lines(
        encode_zbase32(encode_frame(frame)),
        group_size=group_size,
        line_length=line_length,
        line_count=None,
    )


def _recovery_has_shard_quorum(key_lines: Sequence[str]) -> bool:
    prefix = "Recover with "
    suffix = " shard documents."
    for line in key_lines:
        if line.startswith(prefix) and line.endswith(suffix):
            return True
    return False


def _calculate_qr_grid(
    inputs: RenderInputs,
    spec: DocumentSpec,
    usable_w: float,
    usable_h: float,
    content_start_y: float,
    page_h: float,
    margin: float,
    line_height: float,
    min_lines: int,
    include_instructions: bool,
    capabilities: TemplateCapabilities,
) -> tuple[int, int, int, float | None, float, int]:
    """Calculate QR grid dimensions.

    Returns: (cols, rows, per_page, gap_y_override, usable_h_grid, fallback_lines_per_page_val)
    """
    qr_cfg = spec.qr_grid
    qr_size = float(qr_cfg.qr_size_mm)
    gap = float(qr_cfg.gap_mm)
    max_cols = qr_cfg.max_cols
    max_rows = max_rows_override_for_template(
        capabilities=capabilities,
        doc_type=inputs.doc_type,
        max_rows=qr_cfg.max_rows,
        include_instructions=include_instructions,
        content_start_y=content_start_y,
    )

    cols = rows = per_page = 0
    gap_y_override = None
    usable_h_grid = usable_h
    fallback_lines_per_page_val = 0

    if inputs.render_qr:
        if inputs.render_fallback:
            reserved_fallback_height = min_lines * line_height
            usable_h_grid = usable_h - reserved_fallback_height
        else:
            usable_h_grid = usable_h

        cols = calc_cells(usable_w, qr_size, gap, max_cols)
        rows = calc_cells(usable_h_grid, qr_size, gap, max_rows)
        if cols <= 0 or rows <= 0:
            raise ValueError("page too small for configured grid")

        if (
            not inputs.render_fallback
            and max_rows
            and should_force_max_rows(capabilities=capabilities)
        ):
            desired_rows = int(max_rows)
            if desired_rows > rows and desired_rows > 1:
                required_gap = (usable_h_grid - desired_rows * qr_size) / (desired_rows - 1)
                if required_gap >= 0:
                    rows = desired_rows
                    gap_y_override = required_gap

        if inputs.render_fallback:
            rows = adjust_rows_for_fallback(
                rows, content_start_y, page_h, margin, qr_size, gap, line_height, min_lines
            )
            fallback_lines_per_page_val = fallback_lines_per_page(
                rows, content_start_y, page_h, margin, qr_size, gap, line_height
            )
        per_page = cols * rows
    elif inputs.render_fallback:
        fallback_lines_per_page_val = fallback_lines_per_page_text_only(
            content_start_y, page_h, margin, line_height
        )

    return cols, rows, per_page, gap_y_override, usable_h_grid, fallback_lines_per_page_val


def compute_layout(
    inputs: RenderInputs,
    spec: DocumentSpec,
    pdf: FPDF,
    key_lines: Sequence[str],
    *,
    include_keys: bool = True,
    include_instructions: bool = True,
) -> tuple[Layout, list[str]]:
    """Compute the page layout for rendering documents."""
    fallback_cfg = spec.fallback
    qr_cfg = spec.qr_grid
    min_lines_cfg = int(fallback_cfg.line_count)

    if min_lines_cfg is not None and min_lines_cfg <= 0:
        raise ValueError("fallback line_count must be positive")

    # Calculate content positions
    (
        margin,
        header_h,
        instructions_y,
        content_start_y,
        usable_w,
        wrapped_key_lines,
    ) = _calculate_content_positions(
        pdf,
        spec,
        key_lines,
        include_keys=include_keys,
        include_instructions=include_instructions,
    )

    page_w, page_h = pdf.w, pdf.h
    usable_h = page_h - margin - content_start_y
    fallback_width = page_w - 2 * margin
    capabilities = resolve_layout_capabilities(inputs)

    # Calculate fallback line parameters
    text_width_override_mm = fallback_text_width_override_mm(
        capabilities=capabilities,
        doc_type=inputs.doc_type,
        spec=spec,
        page_w=page_w,
        margin=margin,
    )
    line_length, group_size, line_height, fallback_font, fallback_size = (
        _calculate_fallback_line_length(
            pdf,
            spec,
            page_w,
            margin,
            text_width_override_mm=text_width_override_mm,
        )
    )

    # Build fallback lines
    fallback_lines = _build_fallback_lines(inputs, group_size, line_length)
    if fallback_lines and any(is_fallback_label_line(line) for line in fallback_lines):
        label_height = label_line_height_fallback(fallback_cfg)
        line_height = max(float(line_height), label_height)

    min_lines = int(min_lines_cfg) if min_lines_cfg is not None else 1

    # Calculate QR grid dimensions
    (
        cols,
        rows,
        per_page,
        gap_y_override,
        usable_h_grid,
        fallback_lines_per_page_val,
    ) = _calculate_qr_grid(
        inputs,
        spec,
        usable_w,
        usable_h,
        content_start_y,
        page_h,
        margin,
        line_height,
        min_lines,
        include_instructions,
        capabilities,
    )

    line_height, fallback_lines_per_page_val = adjust_layout_fallback_capacity(
        capabilities=capabilities,
        doc_type=inputs.doc_type,
        content_start_y=content_start_y,
        page_h=page_h,
        margin=margin,
        line_height=line_height,
        fallback_lines_per_page_val=fallback_lines_per_page_val,
        include_recovery_metadata_footer=(
            inputs.doc_type.strip().lower() == DOC_TYPE_RECOVERY and include_instructions
        ),
        recovery_meta_lines_extra=int(spec.header.meta_lines_extra),
        include_instructions=include_instructions,
        recovery_has_quorum=(
            _recovery_has_shard_quorum(key_lines)
            if inputs.doc_type.strip().lower() == DOC_TYPE_RECOVERY
            else None
        ),
    )

    # Calculate total pages
    frames_pages = (
        math.ceil(len(inputs.frames) / per_page) if inputs.render_qr and per_page > 0 else 0
    )
    fallback_pages = (
        math.ceil(len(fallback_lines) / fallback_lines_per_page_val)
        if inputs.render_fallback and fallback_lines_per_page_val > 0
        else 0
    )
    total_pages = max(1, frames_pages, fallback_pages)

    # Build layout
    layout = Layout(
        page_w=page_w,
        page_h=page_h,
        margin=margin,
        header_height=header_h,
        instructions_y=instructions_y,
        content_start_y=content_start_y,
        usable_w=usable_w,
        usable_h=usable_h,
        usable_h_grid=usable_h_grid,
        qr_size=float(qr_cfg.qr_size_mm),
        gap=float(qr_cfg.gap_mm),
        cols=cols,
        rows=rows,
        per_page=per_page,
        gap_y_override=gap_y_override,
        fallback_width=fallback_width,
        line_length=line_length,
        line_height=line_height,
        fallback_lines_per_page=fallback_lines_per_page_val,
        fallback_font=fallback_font,
        fallback_size=fallback_size,
        text_gap=float(qr_cfg.text_gap_mm),
        min_lines=min_lines,
        key_lines=tuple(wrapped_key_lines),
        total_pages=total_pages,
    )
    return layout, fallback_lines
