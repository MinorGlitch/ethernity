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
from collections.abc import Callable

from .doc_types import DOC_TYPE_KIT
from .fallback import (
    FallbackBlock,
    FallbackConsumerState,
    FallbackSectionData,
    consume_fallback_blocks,
    fallback_sections_remaining,
    position_fallback_blocks,
)
from .geometry import COORDINATE_EPSILON
from .spec import DocumentSpec
from .template_model import (
    FallbackBlockModel,
    PageModel,
    QrGridModel,
    QrItemModel,
    QrOutlineModel,
    QrSequenceLabelModel,
    QrSequenceLineModel,
    QrSequenceModel,
)
from .types import Layout, RenderInputs


def _calculate_total_pages(
    inputs: RenderInputs,
    layout: Layout,
    layout_rest: Layout | None,
    fallback_lines: list[str],
) -> tuple[int, int, int]:
    """Calculate total pages needed for frames and fallback.

    Returns: (total_pages, fallback_first, fallback_rest)
    """
    fallback_first = layout.fallback_lines_per_page
    fallback_rest = layout_rest.fallback_lines_per_page if layout_rest else fallback_first

    frames_pages = 0
    if inputs.render_qr:
        frames_first = layout.per_page
        frames_rest = layout_rest.per_page if layout_rest else frames_first
        if len(inputs.frames) <= frames_first:
            frames_pages = 1
        else:
            remaining = len(inputs.frames) - frames_first
            frames_pages = 1 + math.ceil(remaining / frames_rest) if frames_rest > 0 else 1

    fallback_pages = 0
    if inputs.render_fallback and fallback_lines:
        if len(fallback_lines) <= fallback_first:
            fallback_pages = 1
        else:
            remaining = len(fallback_lines) - fallback_first
            fallback_pages = 1 + math.ceil(remaining / fallback_rest) if fallback_rest > 0 else 1

    total_pages = max(1, frames_pages, fallback_pages)
    return total_pages, fallback_first, fallback_rest


def _build_qr_slots(
    inputs: RenderInputs,
    page_layout: Layout,
    frame_start: int,
    qr_image_builder: Callable[[int], str],
) -> tuple[tuple[QrItemModel, ...], list[tuple[int, float, float]], QrGridModel | None]:
    """Build QR grid items and geometry for a page.

    Returns: (qr_items, slots_raw, qr_grid)
    """
    if not inputs.render_qr:
        return (), [], None

    qr_items: list[QrItemModel] = []
    slots_raw: list[tuple[int, float, float]] = []

    page_start = max(0, frame_start)
    frames_remaining = max(0, len(inputs.frames) - page_start)
    frames_in_page = min(page_layout.per_page, frames_remaining)
    rows_for_page = page_layout.rows
    if frames_in_page > 0:
        rows_for_page = math.ceil(frames_in_page / page_layout.cols)

    gap_y = (
        page_layout.gap_y_override
        if page_layout.gap_y_override is not None and not inputs.render_fallback
        else page_layout.gap
    )
    gap_x_full = page_layout.gap

    for row in range(page_layout.rows):
        remaining = frames_in_page - row * page_layout.cols
        if remaining <= 0:
            break
        cols_in_row = min(page_layout.cols, remaining)
        x_start = page_layout.margin

        for col in range(cols_in_row):
            frame_idx = page_start + row * page_layout.cols + col
            x = x_start + col * (page_layout.qr_size + gap_x_full)
            y = page_layout.content_start_y + row * (page_layout.qr_size + gap_y)

            qr_items.append(QrItemModel(index=frame_idx + 1, data_uri=qr_image_builder(frame_idx)))
            slots_raw.append((frame_idx, x, y))

    qr_grid = QrGridModel(
        x_mm=page_layout.margin,
        y_mm=page_layout.content_start_y,
        size_mm=page_layout.qr_size,
        gap_x_mm=gap_x_full,
        gap_y_mm=gap_y,
        cols=page_layout.cols,
        rows=rows_for_page,
        count=frames_in_page,
    )
    return tuple(qr_items), slots_raw, qr_grid


def _build_qr_outline(
    slots_raw: list[tuple[int, float, float]],
    qr_size: float,
    outline_padding: float,
) -> QrOutlineModel | None:
    """Build QR grid outline from slot positions."""
    if not slots_raw:
        return None

    padding = max(0.0, outline_padding)
    min_x = min(x for _idx, x, _y in slots_raw)
    min_y = min(y for _idx, _x, y in slots_raw)
    max_x = max(x for _idx, x, _y in slots_raw) + qr_size
    max_y = max(y for _idx, _x, y in slots_raw) + qr_size

    return QrOutlineModel(
        x_mm=min_x - padding,
        y_mm=min_y - padding,
        width_mm=(max_x - min_x) + 2 * padding,
        height_mm=(max_y - min_y) + 2 * padding,
    )


def _frame_start_index(page_idx: int, layout: Layout, layout_rest: Layout | None) -> int:
    if page_idx <= 0:
        return 0
    if layout_rest is None:
        return page_idx * layout.per_page
    return layout.per_page + (page_idx - 1) * layout_rest.per_page


def _build_fallback_blocks(
    inputs: RenderInputs,
    page_layout: Layout,
    page_idx: int,
    fallback_lines: list[str],
    fallback_sections_data: list[FallbackSectionData] | None,
    fallback_state: FallbackConsumerState | None,
    fallback_first: int,
    fallback_rest: int,
) -> tuple[FallbackBlockModel, ...]:
    """Build fallback blocks for a page."""
    if not inputs.render_fallback:
        return ()

    has_fallback = bool(fallback_lines)
    if fallback_sections_data and fallback_state:
        has_fallback = fallback_sections_remaining(fallback_sections_data, fallback_state)

    if not has_fallback:
        return ()

    if inputs.render_qr:
        grid_height = (
            page_layout.rows * page_layout.qr_size + (page_layout.rows - 1) * page_layout.gap
        )
        fallback_y = page_layout.content_start_y + grid_height + page_layout.text_gap
    else:
        fallback_y = page_layout.content_start_y

    available_height = page_layout.page_h - page_layout.margin - fallback_y
    line_height = page_layout.line_height
    lines_capacity = max(0, int(available_height // line_height))

    page_fallback_blocks: list[FallbackBlock] = []
    if fallback_sections_data and fallback_state:
        page_fallback_blocks = consume_fallback_blocks(
            fallback_sections_data,
            fallback_state,
            lines_capacity,
        )
    else:
        if page_idx <= 0:
            start = 0
            end = fallback_first
        else:
            start = fallback_first + (page_idx - 1) * fallback_rest
            end = start + fallback_rest
        page_fallback_lines = fallback_lines[start:end]
        if page_fallback_lines:
            page_fallback_blocks = [
                FallbackBlock(
                    title=None,
                    section_title="",
                    lines=list(page_fallback_lines),
                    gap_lines=0,
                    line_offset=start,
                )
            ]

    if page_fallback_blocks:
        position_fallback_blocks(page_fallback_blocks, fallback_y, available_height, line_height)

    return tuple(
        FallbackBlockModel(
            title=block.title,
            lines=tuple(block.lines),
            line_offset=block.line_offset,
            y_mm=block.y_mm,
            height_mm=block.height_mm,
        )
        for block in page_fallback_blocks
    )


def build_pages(
    *,
    inputs: RenderInputs,
    spec: DocumentSpec,
    layout: Layout,
    layout_rest: Layout | None,
    fallback_lines: list[str],
    qr_image_builder: Callable[[int], str],
    fallback_sections_data: list[FallbackSectionData] | None,
    fallback_state: FallbackConsumerState | None,
) -> list[PageModel]:
    """Build page data models for document rendering."""
    total_pages, fallback_first, fallback_rest = _calculate_total_pages(
        inputs, layout, layout_rest, fallback_lines
    )

    kit_instructions_page = inputs.doc_type == DOC_TYPE_KIT
    pages: list[PageModel] = []
    for page_idx in range(total_pages):
        page_num = page_idx + 1
        page_label = f"Page {page_num} / {total_pages}"
        page_layout = layout_rest if layout_rest and page_idx > 0 else layout
        divider_y = (
            page_layout.margin + page_layout.header_height - float(spec.header.divider_thickness_mm)
        )

        qr_items: tuple[QrItemModel, ...] = ()
        qr_sequence: QrSequenceModel | None = None
        qr_outline: QrOutlineModel | None = None
        qr_grid: QrGridModel | None = None

        if inputs.render_qr:
            frame_start = _frame_start_index(page_idx, layout, layout_rest)
            qr_items, slots_raw, qr_grid = _build_qr_slots(
                inputs,
                page_layout,
                frame_start,
                qr_image_builder,
            )
            if spec.qr_sequence.enabled:
                qr_sequence = _sequence_geometry(
                    slots_raw,
                    page_layout.qr_size,
                    float(spec.qr_sequence.label_offset_mm),
                )
            qr_outline = _build_qr_outline(
                slots_raw,
                page_layout.qr_size,
                float(spec.qr_grid.outline_padding_mm),
            )

        page_fallback_blocks = _build_fallback_blocks(
            inputs,
            page_layout,
            page_idx,
            fallback_lines,
            fallback_sections_data,
            fallback_state,
            fallback_first,
            fallback_rest,
        )

        pages.append(
            PageModel(
                page_num=page_num,
                page_label=page_label,
                divider_y_mm=divider_y,
                instructions_y_mm=page_layout.instructions_y,
                show_instructions=(
                    not kit_instructions_page
                    and (not spec.instructions.first_page_only or page_idx == 0)
                ),
                instructions_full_page=False,
                qr_items=qr_items,
                qr_grid=qr_grid,
                qr_outline=qr_outline,
                sequence=qr_sequence,
                fallback_blocks=page_fallback_blocks,
            )
        )

    if kit_instructions_page:
        instruction_layout = layout_rest or layout
        divider_y = (
            instruction_layout.margin
            + instruction_layout.header_height
            - float(spec.header.divider_thickness_mm)
        )
        pages.append(
            PageModel(
                page_num=len(pages) + 1,
                page_label="",
                divider_y_mm=divider_y,
                instructions_y_mm=instruction_layout.instructions_y,
                show_instructions=True,
                instructions_full_page=True,
                qr_items=(),
                qr_grid=None,
                qr_outline=None,
                sequence=None,
                fallback_blocks=(),
            )
        )

    while pages and not _page_has_content(pages[-1]):
        pages.pop()

    if pages:
        final_total = len(pages)
        pages = [
            PageModel(
                page_num=idx + 1,
                page_label=f"Page {idx + 1} / {final_total}",
                divider_y_mm=page.divider_y_mm,
                instructions_y_mm=page.instructions_y_mm,
                show_instructions=page.show_instructions,
                instructions_full_page=page.instructions_full_page,
                qr_items=page.qr_items,
                qr_grid=page.qr_grid,
                qr_outline=page.qr_outline,
                sequence=page.sequence,
                fallback_blocks=page.fallback_blocks,
            )
            for idx, page in enumerate(pages)
        ]

    return pages


def _page_has_content(page: PageModel) -> bool:
    if page.qr_items:
        return True
    if page.fallback_blocks:
        return True
    if page.show_instructions:
        return True
    return False


def _sequence_geometry(
    slots: list[tuple[int, float, float]],
    qr_size: float,
    label_offset: float,
) -> QrSequenceModel | None:
    if not slots:
        return None

    lines: list[QrSequenceLineModel] = []
    labels: list[QrSequenceLabelModel] = []

    for idx, (frame_idx, x, y) in enumerate(slots):
        number = str(frame_idx + 1)
        center_x = x + qr_size / 2
        center_y = y + qr_size / 2
        if idx + 1 < len(slots):
            _next_idx, next_x, next_y = slots[idx + 1]
            if abs(next_y - y) < COORDINATE_EPSILON:
                line_y = center_y
                line_start = x + qr_size
                line_end = next_x
                lines.append(QrSequenceLineModel(x1=line_start, y1=line_y, x2=line_end, y2=line_y))
                labels.append(
                    QrSequenceLabelModel(
                        text=number,
                        x=(line_start + line_end) / 2,
                        y=line_y - label_offset,
                    )
                )
            else:
                start_y = y + qr_size
                end_y = next_y
                mid_y = start_y + (end_y - start_y) / 2
                next_center_x = next_x + qr_size / 2
                if abs(next_x - x) < COORDINATE_EPSILON:
                    lines.append(
                        QrSequenceLineModel(x1=center_x, y1=start_y, x2=center_x, y2=end_y)
                    )
                    labels.append(
                        QrSequenceLabelModel(
                            text=number,
                            x=center_x,
                            y=mid_y - label_offset,
                        )
                    )
                else:
                    lines.append(
                        QrSequenceLineModel(x1=center_x, y1=start_y, x2=center_x, y2=mid_y)
                    )
                    lines.append(
                        QrSequenceLineModel(
                            x1=center_x,
                            y1=mid_y,
                            x2=next_center_x,
                            y2=mid_y,
                        )
                    )
                    lines.append(
                        QrSequenceLineModel(
                            x1=next_center_x,
                            y1=mid_y,
                            x2=next_center_x,
                            y2=end_y,
                        )
                    )
                    labels.append(
                        QrSequenceLabelModel(
                            text=number,
                            x=(center_x + next_center_x) / 2,
                            y=mid_y - label_offset,
                        )
                    )

    return QrSequenceModel(lines=tuple(lines), labels=tuple(labels))
