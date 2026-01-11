#!/usr/bin/env python3
from __future__ import annotations

import math
from typing import Callable, Sequence

from .fallback import (
    consume_fallback_blocks,
    fallback_sections_remaining,
    position_fallback_blocks,
)
from .geometry import COORDINATE_EPSILON, expand_gap_to_fill
from .spec import DocumentSpec
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
    page_idx: int,
    qr_payloads: Sequence[bytes | str],
    qr_image_builder: Callable[[bytes | str], str],
) -> tuple[list[dict[str, object]], list[tuple[int, float, float]]]:
    """Build QR slot positions for a page.

    Returns: (qr_slots, slots_raw)
    """
    qr_slots: list[dict[str, object]] = []
    slots_raw: list[tuple[int, float, float]] = []

    page_start = page_idx * page_layout.per_page
    frames_in_page = min(page_layout.per_page, len(inputs.frames) - page_start)
    rows_for_page = page_layout.rows
    if frames_in_page > 0:
        rows_for_page = math.ceil(frames_in_page / page_layout.cols)

    gap_y = page_layout.gap
    if not inputs.render_fallback:
        if page_layout.gap_y_override is not None and rows_for_page == page_layout.rows:
            gap_y = page_layout.gap_y_override
        else:
            gap_y = expand_gap_to_fill(
                page_layout.usable_h_grid,
                page_layout.qr_size,
                page_layout.gap,
                rows_for_page,
            )

    gap_x_full = expand_gap_to_fill(
        page_layout.usable_w,
        page_layout.qr_size,
        page_layout.gap,
        page_layout.cols,
    )

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

            qr_slots.append(
                {
                    "index": frame_idx + 1,
                    "x_mm": x,
                    "y_mm": y,
                    "size_mm": page_layout.qr_size,
                    "data_uri": qr_image_builder(qr_payloads[frame_idx]),
                }
            )
            slots_raw.append((frame_idx, x, y))

    return qr_slots, slots_raw


def _build_qr_outline(
    slots_raw: list[tuple[int, float, float]],
    qr_size: float,
    outline_padding: float,
) -> dict[str, float] | None:
    """Build QR grid outline from slot positions."""
    if not slots_raw:
        return None

    padding = max(0.0, outline_padding)
    min_x = min(x for _idx, x, _y in slots_raw)
    min_y = min(y for _idx, _x, y in slots_raw)
    max_x = max(x for _idx, x, _y in slots_raw) + qr_size
    max_y = max(y for _idx, _x, y in slots_raw) + qr_size

    return {
        "x_mm": min_x - padding,
        "y_mm": min_y - padding,
        "width_mm": (max_x - min_x) + 2 * padding,
        "height_mm": (max_y - min_y) + 2 * padding,
    }


def _build_fallback_blocks(
    inputs: RenderInputs,
    page_layout: Layout,
    layout: Layout,
    layout_rest: Layout | None,
    page_idx: int,
    fallback_lines: list[str],
    fallback_sections_data: list[dict[str, object]] | None,
    fallback_state: dict[str, int] | None,
    fallback_first: int,
    fallback_rest: int,
) -> list[dict[str, object]]:
    """Build fallback blocks for a page."""
    if not inputs.render_fallback:
        return []

    has_fallback = bool(fallback_lines)
    if fallback_sections_data and fallback_state:
        has_fallback = fallback_sections_remaining(fallback_sections_data, fallback_state)

    if not has_fallback:
        return []

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

    page_fallback_blocks: list[dict[str, object]] = []
    if fallback_sections_data and fallback_state:
        page_fallback_blocks = consume_fallback_blocks(
            fallback_sections_data,
            fallback_state,
            lines_capacity,
        )
    else:
        if layout_rest and page_idx > 0 and not inputs.render_qr:
            start = fallback_first + (page_idx - 1) * fallback_rest
            end = start + fallback_rest
        else:
            start = page_idx * layout.fallback_lines_per_page
            end = start + layout.fallback_lines_per_page
        page_fallback_lines = fallback_lines[start:end]
        if page_fallback_lines:
            page_fallback_blocks = [{"title": None, "lines": page_fallback_lines, "gap_lines": 0}]

    if page_fallback_blocks:
        position_fallback_blocks(page_fallback_blocks, fallback_y, available_height, line_height)

    return page_fallback_blocks


def build_pages(
    *,
    inputs: RenderInputs,
    spec: DocumentSpec,
    layout: Layout,
    layout_rest: Layout | None,
    fallback_lines: list[str],
    qr_payloads: Sequence[bytes | str],
    qr_image_builder: Callable[[bytes | str], str],
    fallback_sections_data: list[dict[str, object]] | None,
    fallback_state: dict[str, int] | None,
    key_lines: Sequence[str],
    keys_first_page_only: bool,
) -> list[dict[str, object]]:
    """Build page data for document rendering."""
    total_pages, fallback_first, fallback_rest = _calculate_total_pages(
        inputs, layout, layout_rest, fallback_lines
    )

    pages: list[dict[str, object]] = []
    for page_idx in range(total_pages):
        page_num = page_idx + 1
        page_label = f"Page {page_num} / {total_pages}"
        page_layout = layout_rest if layout_rest and page_idx > 0 else layout
        divider_y = (
            page_layout.margin + page_layout.header_height - float(spec.header.divider_thickness_mm)
        )

        qr_slots: list[dict[str, object]] = []
        qr_sequence = None
        qr_outline = None

        if inputs.render_qr:
            qr_slots, slots_raw = _build_qr_slots(
                inputs, page_layout, page_idx, qr_payloads, qr_image_builder
            )
            if spec.qr_sequence.enabled:
                qr_sequence = _sequence_geometry(
                    slots_raw, page_layout.qr_size, float(spec.qr_sequence.label_offset_mm)
                )
            qr_outline = _build_qr_outline(
                slots_raw, page_layout.qr_size, float(spec.qr_grid.outline_padding_mm)
            )

        page_fallback_blocks = _build_fallback_blocks(
            inputs,
            page_layout,
            layout,
            layout_rest,
            page_idx,
            fallback_lines,
            fallback_sections_data,
            fallback_state,
            fallback_first,
            fallback_rest,
        )

        pages.append(
            {
                "page_num": page_num,
                "page_label": page_label,
                "divider_y_mm": divider_y,
                "instructions_y_mm": page_layout.instructions_y,
                "keys_y_mm": page_layout.keys_y,
                "show_keys": not (keys_first_page_only and page_idx > 0),
                "qr_slots": qr_slots,
                "qr_outline": qr_outline,
                "sequence": qr_sequence,
                "fallback_blocks": page_fallback_blocks,
            }
        )

    # Remove empty trailing pages
    while pages and not _page_has_content(pages[-1], key_lines):
        pages.pop()

    # Update page labels with final count
    if pages:
        final_total = len(pages)
        for idx, page in enumerate(pages):
            page["page_num"] = idx + 1
            page["page_label"] = f"Page {idx + 1} / {final_total}"

    return pages


def _page_has_content(page: dict[str, object], key_lines: Sequence[str]) -> bool:
    if page.get("qr_slots"):
        return True
    if page.get("fallback_blocks"):
        return True
    if page.get("show_keys") and key_lines:
        return True
    return False


def _sequence_geometry(
    slots: list[tuple[int, float, float]],
    qr_size: float,
    label_offset: float,
) -> dict[str, list[dict[str, float | str]]]:
    lines: list[dict[str, float | str]] = []
    labels: list[dict[str, float | str]] = []

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
                lines.append({"x1": line_start, "y1": line_y, "x2": line_end, "y2": line_y})
                labels.append(
                    {
                        "text": number,
                        "x": (line_start + line_end) / 2,
                        "y": line_y - label_offset,
                    }
                )
            else:
                start_y = y + qr_size
                end_y = next_y
                mid_y = start_y + (end_y - start_y) / 2
                next_center_x = next_x + qr_size / 2
                if abs(next_x - x) < COORDINATE_EPSILON:
                    lines.append({"x1": center_x, "y1": start_y, "x2": center_x, "y2": end_y})
                    labels.append({"text": number, "x": center_x, "y": mid_y - label_offset})
                else:
                    lines.append({"x1": center_x, "y1": start_y, "x2": center_x, "y2": mid_y})
                    lines.append(
                        {
                            "x1": center_x,
                            "y1": mid_y,
                            "x2": next_center_x,
                            "y2": mid_y,
                        }
                    )
                    lines.append(
                        {
                            "x1": next_center_x,
                            "y1": mid_y,
                            "x2": next_center_x,
                            "y2": end_y,
                        }
                    )
                    labels.append(
                        {
                            "text": number,
                            "x": (center_x + next_center_x) / 2,
                            "y": mid_y - label_offset,
                        }
                    )

    return {"lines": lines, "labels": labels}
