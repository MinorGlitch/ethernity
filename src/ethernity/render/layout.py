#!/usr/bin/env python3
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from fpdf import FPDF

from ..encoding.chunking import (
    frame_to_fallback_lines,
    payload_to_fallback_lines,
    reassemble_payload,
)
from ..encoding.framing import Frame
from ..qr.codec import QrConfig
from .spec import DocumentSpec, FallbackSpec, HeaderSpec, PageSpec, TextBlockSpec


@dataclass(frozen=True)
class FallbackSection:
    label: str | None
    frame: Frame


@dataclass(frozen=True)
class RenderInputs:
    frames: Sequence[Frame]
    template_path: str | Path
    output_path: str | Path
    context: dict[str, object]
    doc_type: str | None = None
    qr_config: QrConfig | None = None
    qr_payloads: Sequence[bytes | str] | None = None
    fallback_payload: bytes | None = None
    fallback_sections: Sequence[FallbackSection] | None = None
    render_qr: bool = True
    render_fallback: bool = True
    key_lines: Sequence[str] | None = None


@dataclass(frozen=True)
class Layout:
    page_w: float
    page_h: float
    margin: float
    header_height: float
    instructions_y: float
    keys_y: float
    content_start_y: float
    usable_w: float
    usable_h: float
    usable_h_grid: float
    qr_size: float
    gap: float
    cols: int
    rows: int
    per_page: int
    gap_y_override: float | None
    fallback_width: float
    line_length: int
    line_height: float
    fallback_lines_per_page: int
    fallback_font: str
    fallback_size: float
    text_gap: float
    min_lines: int
    key_lines: tuple[str, ...]
    total_pages: int


FALLBACK_VERTICAL_PADDING_MM = 0.0
FALLBACK_HORIZONTAL_PADDING_MM = 2.0


def _compute_layout(
    inputs: RenderInputs,
    spec: DocumentSpec,
    pdf: FPDF,
    key_lines: Sequence[str],
    *,
    include_keys: bool = True,
    include_instructions: bool = True,
) -> tuple[Layout, list[str]]:
    page_cfg = spec.page
    qr_cfg = spec.qr_grid
    fallback_cfg = spec.fallback
    keys_cfg = spec.keys
    header_cfg = spec.header
    instructions_cfg = spec.instructions

    margin = float(page_cfg.margin_mm)
    header_min_height = float(page_cfg.header_height_mm)
    instructions_gap = float(page_cfg.instructions_gap_mm)
    keys_gap = float(page_cfg.keys_gap_mm)

    qr_size = float(qr_cfg.qr_size_mm)
    gap = float(qr_cfg.gap_mm)
    max_cols = qr_cfg.max_cols
    max_rows = qr_cfg.max_rows
    text_gap = float(qr_cfg.text_gap_mm)

    group_size = int(fallback_cfg.group_size)
    line_length_cfg = int(fallback_cfg.line_length)
    min_lines_cfg = int(fallback_cfg.line_count)
    line_height = float(fallback_cfg.line_height_mm)
    fallback_font = fallback_cfg.font_family
    fallback_size = float(fallback_cfg.font_size)

    if min_lines_cfg is not None and min_lines_cfg <= 0:
        raise ValueError("fallback line_count must be positive")

    page_w, page_h = pdf.w, pdf.h
    usable_w = page_w - 2 * margin
    instructions_height = _instructions_height(instructions_cfg) if include_instructions else 0.0

    wrapped_key_lines = list(key_lines)
    if include_keys and key_lines:
        keys_font = keys_cfg.font_family
        keys_size = float(keys_cfg.font_size)
        pdf.set_font(keys_font, size=keys_size)
        max_text_width = _text_block_width(keys_cfg, usable_w)
        wrapped_key_lines = _wrap_lines_to_width(pdf, key_lines, max_text_width)
    if include_keys:
        keys_height = _lines_height(keys_cfg, wrapped_key_lines)
    else:
        wrapped_key_lines = []
        keys_height = 0.0

    header_height = _header_height(header_cfg, header_min_height)
    content_start_y = margin + header_height
    instructions_y = content_start_y
    if instructions_height > 0:
        content_start_y += instructions_height + instructions_gap
    keys_y = content_start_y
    if include_keys and keys_height > 0:
        content_start_y += keys_height + keys_gap
    usable_h = page_h - margin - content_start_y

    pdf.set_font(fallback_font, size=fallback_size)
    original_cell_margin = pdf.c_margin
    pdf.c_margin = 0
    fallback_width = page_w - 2 * margin
    padding_mm = float(fallback_cfg.padding_mm)
    fallback_width_safe = max(1.0, fallback_width - (2 * float(padding_mm)))
    max_groups = _max_groups_for_width(pdf, group_size, fallback_width_safe)
    if line_length_cfg > 0:
        max_groups = min(max_groups, _groups_from_line_length(line_length_cfg, group_size))
    line_length = _line_length_from_groups(max_groups, group_size)
    pdf.c_margin = original_cell_margin

    fallback_lines: list[str] = []
    if inputs.render_fallback:
        if inputs.fallback_sections:
            fallback_lines = _fallback_lines_from_sections(
                inputs.fallback_sections,
                group_size=group_size,
                line_length=line_length,
            )
        else:
            fallback_payload = inputs.fallback_payload
            if fallback_payload is None:
                fallback_payload = reassemble_payload(inputs.frames)
            fallback_lines = payload_to_fallback_lines(
                fallback_payload,
                doc_id=inputs.frames[0].doc_id,
                frame_type=inputs.frames[0].frame_type,
                group_size=group_size,
                line_length=line_length,
            )
    if fallback_lines and any(_is_fallback_label_line(line) for line in fallback_lines):
        label_height = _label_line_height_fallback(fallback_cfg)
        line_height = max(float(line_height), label_height)

    min_lines = int(min_lines_cfg) if min_lines_cfg is not None else 1
    cols = rows = per_page = 0
    gap_y_override = None
    usable_h_grid = usable_h
    fallback_lines_per_page = 0

    if inputs.render_qr:
        if inputs.render_fallback:
            reserved_fallback_height = min_lines * line_height
            usable_h_grid = usable_h - reserved_fallback_height
        else:
            usable_h_grid = usable_h

        cols = _calc_cells(usable_w, qr_size, gap, max_cols)
        rows = _calc_cells(usable_h_grid, qr_size, gap, max_rows)
        if cols <= 0 or rows <= 0:
            raise ValueError("page too small for configured grid")

        if not inputs.render_fallback and max_rows:
            desired_rows = int(max_rows)
            if desired_rows > rows and desired_rows > 1:
                required_gap = (usable_h_grid - desired_rows * qr_size) / (desired_rows - 1)
                if required_gap >= 0:
                    rows = desired_rows
                    gap_y_override = required_gap

        if inputs.render_fallback:
            rows = _adjust_rows_for_fallback(
                rows,
                content_start_y,
                page_h,
                margin,
                qr_size,
                gap,
                line_height,
                min_lines,
            )
            fallback_lines_per_page = _fallback_lines_per_page(
                rows,
                content_start_y,
                page_h,
                margin,
                qr_size,
                gap,
                line_height,
            )
        per_page = cols * rows
    elif inputs.render_fallback:
        fallback_lines_per_page = _fallback_lines_per_page_text_only(
            content_start_y,
            page_h,
            margin,
            line_height,
        )

    frames_pages = math.ceil(len(inputs.frames) / per_page) if inputs.render_qr else 0
    fallback_pages = (
        math.ceil(len(fallback_lines) / fallback_lines_per_page) if inputs.render_fallback else 0
    )
    total_pages = max(1, frames_pages, fallback_pages)

    layout = Layout(
        page_w=page_w,
        page_h=page_h,
        margin=margin,
        header_height=header_height,
        instructions_y=instructions_y,
        keys_y=keys_y,
        content_start_y=content_start_y,
        usable_w=usable_w,
        usable_h=usable_h,
        usable_h_grid=usable_h_grid,
        qr_size=qr_size,
        gap=gap,
        cols=cols,
        rows=rows,
        per_page=per_page,
        gap_y_override=gap_y_override,
        fallback_width=fallback_width,
        line_length=line_length,
        line_height=line_height,
        fallback_lines_per_page=fallback_lines_per_page,
        fallback_font=fallback_font,
        fallback_size=fallback_size,
        text_gap=text_gap,
        min_lines=min_lines,
        key_lines=tuple(wrapped_key_lines),
        total_pages=total_pages,
    )
    return layout, fallback_lines


def _fallback_lines_from_sections(
    sections: Sequence[FallbackSection],
    *,
    group_size: int,
    line_length: int,
) -> list[str]:
    lines: list[str] = []
    for idx, section in enumerate(sections):
        if section.label:
            lines.append(section.label)
        section_lines = frame_to_fallback_lines(
            section.frame,
            group_size=group_size,
            line_length=line_length,
            line_count=None,
        )
        lines.extend(section_lines)
        if idx < len(sections) - 1:
            lines.append("")
    return lines


def _page_format(page_cfg: PageSpec) -> str | tuple[float, float]:
    if page_cfg.width_mm and page_cfg.height_mm:
        return (float(page_cfg.width_mm), float(page_cfg.height_mm))
    return page_cfg.size


def _calc_cells(usable: float, cell: float, gap: float, max_cells: int | None) -> int:
    count = int((usable + gap) // (cell + gap))
    if max_cells is not None:
        return min(count, int(max_cells))
    return count


def _wrap_lines_to_width(pdf: FPDF, lines: Sequence[str], max_width: float) -> list[str]:
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


def _text_block_width(cfg: TextBlockSpec, usable_w: float) -> float:
    width = usable_w - float(cfg.indent_mm)
    label = cfg.label
    label_layout = str(cfg.label_layout).lower()
    if label and label_layout == "column":
        width -= float(cfg.label_column_mm)
        width -= float(cfg.label_gap_mm)
    return max(1.0, width)


def _is_fallback_label_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("===") and stripped.endswith("===") and len(stripped) > 6


def _body_line_height(cfg: TextBlockSpec) -> float:
    if cfg.line_height_mm is not None:
        return float(cfg.line_height_mm)
    return _font_line_height(cfg.font_size)


def _label_line_height_text(cfg: TextBlockSpec) -> float:
    if cfg.label_line_height_mm is not None:
        return float(cfg.label_line_height_mm)
    return _font_line_height(cfg.label_size or cfg.font_size)


def _label_line_height_fallback(cfg: FallbackSpec) -> float:
    if cfg.label_line_height_mm is not None:
        return float(cfg.label_line_height_mm)
    return _font_line_height(cfg.label_size or cfg.font_size)


def _header_height(cfg: HeaderSpec, minimum: float) -> float:
    height = 0.0
    title = cfg.title
    subtitle = cfg.subtitle
    doc_id_label = cfg.doc_id_label
    doc_id = cfg.doc_id or ""
    page_label = cfg.page_label or ""
    divider_enabled = bool(cfg.divider_enabled)
    layout = str(cfg.layout).lower()

    title_height = _font_line_height(cfg.title_size) if title else 0.0
    subtitle_height = _font_line_height(cfg.subtitle_size) if subtitle else 0.0
    meta_lines = 0
    if doc_id_label or doc_id:
        meta_lines += 1
    if page_label:
        meta_lines += 1
    meta_height = meta_lines * _font_line_height(cfg.meta_size)

    if layout == "split":
        height += max(title_height + subtitle_height, meta_height)
    else:
        height += title_height + subtitle_height + meta_height

    if divider_enabled:
        height += float(cfg.divider_gap_mm)
        height += float(cfg.divider_thickness_mm)

    return max(height, minimum)


def _instructions_height(cfg: TextBlockSpec) -> float:
    return _lines_height(cfg, cfg.lines)


def _lines_height(cfg: TextBlockSpec, lines: Sequence[str]) -> float:
    label = cfg.label
    if not lines and not label:
        return 0.0

    body_height = len(lines) * _body_line_height(cfg) if lines else 0.0
    if not label:
        return body_height

    label_layout = str(cfg.label_layout).lower()
    label_height = _label_line_height_text(cfg)
    if label_layout == "column":
        return max(body_height, label_height)

    gap = float(cfg.label_gap_mm)
    if body_height <= 0:
        return label_height
    return label_height + gap + body_height


def _font_line_height(size_pt: float, multiplier: float = 1.2) -> float:
    pt_to_mm = 0.3527777778
    return float(size_pt) * pt_to_mm * multiplier


def _expand_gap_to_fill(usable_w: float, cell_w: float, gap: float, cols: int) -> float:
    if cols <= 1:
        return gap
    base_width = cols * cell_w + (cols - 1) * gap
    extra = usable_w - base_width
    if extra <= 0:
        return gap
    return gap + extra / (cols - 1)


def _adjust_rows_for_fallback(
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


def _fallback_lines_per_page(
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


def _fallback_lines_per_page_text_only(
    content_start_y: float,
    page_h: float,
    margin: float,
    line_height: float,
) -> int:
    leftover = page_h - content_start_y - margin
    safe_leftover = max(0.0, leftover - FALLBACK_VERTICAL_PADDING_MM)
    return max(1, int(safe_leftover // line_height))


def _max_groups_for_width(pdf: FPDF, group_size: int, width_mm: float) -> int:
    group_width = pdf.get_string_width("M" * group_size)
    space_width = pdf.get_string_width(" ")
    if group_width <= 0:
        return 1
    if width_mm <= group_width:
        return 1
    return max(1, int((width_mm + space_width) // (group_width + space_width)))


def _groups_from_line_length(line_length: int, group_size: int) -> int:
    if line_length <= group_size:
        return 1
    return max(1, (line_length + 1) // (group_size + 1))


def _line_length_from_groups(groups: int, group_size: int) -> int:
    return max(group_size, groups * (group_size + 1) - 1)


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
        title = _fallback_section_title(section.label)
        lines = frame_to_fallback_lines(
            section.frame,
            group_size=group_size,
            line_length=line_length,
            line_count=None,
        )
        fallback_sections_data.append({"title": title, "lines": lines})
    fallback_state = {"section_idx": 0, "line_idx": 0}
    return fallback_sections_data, fallback_state


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
                    gap_y = _expand_gap_to_fill(
                        page_layout.usable_h_grid,
                        page_layout.qr_size,
                        page_layout.gap,
                        rows_for_page,
                    )

            slots_raw: list[tuple[int, float, float]] = []
            gap_x_full = _expand_gap_to_fill(
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
                gap_x = gap_x_full
                x_start = page_layout.margin

                for col in range(cols_in_row):
                    frame_idx = page_start + row * page_layout.cols + col
                    x = x_start + col * (page_layout.qr_size + gap_x)
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

            if spec.qr_sequence.enabled:
                qr_sequence = _sequence_geometry(
                    slots_raw,
                    page_layout.qr_size,
                    float(spec.qr_sequence.label_offset_mm),
                )
            if slots_raw:
                outline_padding = max(
                    0.0,
                    float(spec.qr_grid.outline_padding_mm),
                )
                min_x = min(x for _idx, x, _y in slots_raw)
                min_y = min(y for _idx, _x, y in slots_raw)
                max_x = max(x for _idx, x, _y in slots_raw) + page_layout.qr_size
                max_y = max(y for _idx, _x, y in slots_raw) + page_layout.qr_size
                qr_outline = {
                    "x_mm": min_x - outline_padding,
                    "y_mm": min_y - outline_padding,
                    "width_mm": (max_x - min_x) + 2 * outline_padding,
                    "height_mm": (max_y - min_y) + 2 * outline_padding,
                }

        page_fallback_blocks: list[dict[str, object]] = []
        if inputs.render_fallback:
            has_fallback = bool(fallback_lines)
            if fallback_sections_data and fallback_state:
                has_fallback = _fallback_sections_remaining(fallback_sections_data, fallback_state)
            if has_fallback:
                if inputs.render_qr:
                    grid_height = (
                        page_layout.rows * page_layout.qr_size
                        + (page_layout.rows - 1) * page_layout.gap
                    )
                    fallback_y = page_layout.content_start_y + grid_height + page_layout.text_gap
                else:
                    fallback_y = page_layout.content_start_y

                available_height = page_layout.page_h - page_layout.margin - fallback_y
                line_height = page_layout.line_height
                lines_capacity = max(0, int(available_height // line_height))

                if fallback_sections_data and fallback_state:
                    page_fallback_blocks = _consume_fallback_blocks(
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
                        page_fallback_blocks = [
                            {
                                "title": None,
                                "lines": page_fallback_lines,
                                "gap_lines": 0,
                            }
                        ]
                if page_fallback_blocks:
                    _position_fallback_blocks(
                        page_fallback_blocks,
                        fallback_y,
                        available_height,
                        line_height,
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

    while pages and not _page_has_content(pages[-1], key_lines):
        pages.pop()

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
            if abs(next_y - y) < 0.01:
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
                if abs(next_x - x) < 0.01:
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


def _fallback_section_title(label: str | None) -> str:
    if isinstance(label, str) and label.strip():
        return label.strip()
    return "Fallback Frame"


def _fallback_sections_remaining(
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


def _consume_fallback_blocks(
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
                "lines": chunk,
                "gap_lines": gap_lines,
            }
        )

        lines_left -= chunk_size
        first_block = False

        if state["line_idx"] >= len(lines):
            state["section_idx"] += 1
            state["line_idx"] = 0

    return blocks


def _position_fallback_blocks(
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


def _int_value(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _float_value(value: object, *, default: float) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default
