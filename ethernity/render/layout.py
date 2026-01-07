#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Sequence

from fpdf import FPDF

from ..encoding.chunking import frame_to_fallback_lines, payload_to_fallback_lines, reassemble_payload
from ..encoding.framing import Frame
from ..qr.codec import QrConfig


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
    fallback_size: int
    text_gap: float
    min_lines: int
    key_lines: tuple[str, ...]
    total_pages: int


FALLBACK_VERTICAL_PADDING_MM = 0.0
FALLBACK_HORIZONTAL_PADDING_MM = 2.0


def _compute_layout(
    inputs: RenderInputs,
    initial_cfg: dict,
    pdf: FPDF,
    key_lines: Sequence[str],
    *,
    include_keys: bool = True,
    include_instructions: bool = True,
) -> tuple[Layout, list[str]]:
    page_cfg = initial_cfg.get("page", {})
    qr_cfg = initial_cfg.get("qr_grid", {})
    fallback_cfg = initial_cfg.get("fallback", {})
    keys_cfg = initial_cfg.get("keys", {})
    header_cfg = initial_cfg.get("header", {})
    instructions_cfg = initial_cfg.get("instructions", {})

    margin = page_cfg.get("margin_mm", 12)
    header_min_height = page_cfg.get("header_height_mm", 10)
    instructions_gap = page_cfg.get("instructions_gap_mm", 2)
    keys_gap = page_cfg.get("keys_gap_mm", 2)

    qr_size = qr_cfg.get("qr_size_mm", 35)
    gap = qr_cfg.get("gap_mm", 6)
    max_cols = qr_cfg.get("max_cols")
    max_rows = qr_cfg.get("max_rows")
    text_gap = qr_cfg.get("text_gap_mm", 2)

    group_size = fallback_cfg.get("group_size", 4)
    line_length_cfg = fallback_cfg.get("line_length", 80)
    min_lines_cfg = fallback_cfg.get("line_count", 6)
    line_height = fallback_cfg.get("line_height_mm", 3.5)
    fallback_font = fallback_cfg.get("font_family", "Courier")
    fallback_size = fallback_cfg.get("font_size", 8)

    if min_lines_cfg is not None and min_lines_cfg <= 0:
        raise ValueError("fallback line_count must be positive")

    page_w, page_h = pdf.w, pdf.h
    usable_w = page_w - 2 * margin
    instructions = instructions_cfg.get("lines", [])
    instructions_height = _instructions_height(instructions_cfg) if include_instructions else 0.0

    wrapped_key_lines = list(key_lines)
    if include_keys and key_lines:
        keys_font = keys_cfg.get("font_family", "Helvetica")
        keys_size = keys_cfg.get("font_size", 8)
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
    padding_mm = fallback_cfg.get("padding_mm", FALLBACK_HORIZONTAL_PADDING_MM)
    fallback_width_safe = max(
        1.0, fallback_width - (2 * float(padding_mm))
    )
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
        label_height = _label_line_height(fallback_cfg)
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


def _page_format(page_cfg: dict) -> str | tuple[float, float]:
    width = page_cfg.get("width_mm")
    height = page_cfg.get("height_mm")
    if width and height:
        return (float(width), float(height))
    return page_cfg.get("size", "A4")


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


def _text_block_width(cfg: dict, usable_w: float) -> float:
    width = usable_w - _cfg_float(cfg, "indent_mm", 0.0)
    label = cfg.get("label")
    label_layout = str(cfg.get("label_layout", "stacked")).lower()
    if label and label_layout == "column":
        width -= _cfg_float(cfg, "label_column_mm", 0.0)
        width -= _cfg_float(cfg, "label_gap_mm", 0.0)
    return max(1.0, width)


def _is_fallback_label_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("===") and stripped.endswith("===") and len(stripped) > 6


def _cfg_float(cfg: dict, key: str, default: float = 0.0) -> float:
    value = cfg.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _body_line_height(cfg: dict) -> float:
    line_height = cfg.get("line_height_mm")
    if line_height:
        return _cfg_float(cfg, "line_height_mm", default=0.0)
    return _font_line_height(cfg.get("font_size", 8))


def _label_line_height(cfg: dict) -> float:
    line_height = cfg.get("label_line_height_mm")
    if line_height:
        return _cfg_float(cfg, "label_line_height_mm", default=0.0)
    label_size = cfg.get("label_size", cfg.get("font_size", 8))
    return _font_line_height(label_size)


def _header_height(cfg: dict, minimum: float) -> float:
    height = 0.0
    title = cfg.get("title", "")
    subtitle = cfg.get("subtitle", "")
    doc_id_label = cfg.get("doc_id_label", "")
    doc_id = cfg.get("doc_id", "")
    page_label = cfg.get("page_label", "")
    divider_enabled = bool(cfg.get("divider_enabled", False))
    layout = str(cfg.get("layout", "stacked")).lower()

    title_height = _font_line_height(cfg.get("title_size", 14)) if title else 0.0
    subtitle_height = _font_line_height(cfg.get("subtitle_size", 10)) if subtitle else 0.0
    meta_lines = 0
    if doc_id_label or doc_id:
        meta_lines += 1
    if page_label:
        meta_lines += 1
    meta_height = meta_lines * _font_line_height(cfg.get("meta_size", 8))

    if layout == "split":
        height += max(title_height + subtitle_height, meta_height)
    else:
        height += title_height + subtitle_height + meta_height

    if divider_enabled:
        height += float(cfg.get("divider_gap_mm", 2))
        height += float(cfg.get("divider_thickness_mm", 0.4))

    return max(height, minimum)


def _instructions_height(cfg: dict) -> float:
    return _lines_height(cfg, cfg.get("lines", []))


def _lines_height(cfg: dict, lines: Sequence[str]) -> float:
    label = cfg.get("label")
    if not lines and not label:
        return 0.0

    body_height = len(lines) * _body_line_height(cfg) if lines else 0.0
    if not label:
        return body_height

    label_layout = str(cfg.get("label_layout", "stacked")).lower()
    label_height = _label_line_height(cfg)
    if label_layout == "column":
        return max(body_height, label_height)

    gap = _cfg_float(cfg, "label_gap_mm", 0.0)
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
        leftover = page_h - margin - grid_start_y - grid_height - margin
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
    leftover = page_h - margin - grid_start_y - grid_height - margin
    safe_leftover = max(0.0, leftover - FALLBACK_VERTICAL_PADDING_MM)
    return max(1, int(safe_leftover // line_height))


def _fallback_lines_per_page_text_only(
    content_start_y: float,
    page_h: float,
    margin: float,
    line_height: float,
) -> int:
    leftover = page_h - margin - content_start_y - margin
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
