#!/usr/bin/env python3
from __future__ import annotations

import base64
import math
from pathlib import Path
from typing import Any, cast

from fpdf import FPDF
from playwright.sync_api import sync_playwright

from ..encoding.framing import encode_frame
from ..encoding.chunking import frame_to_fallback_lines
from ..qr.codec import QrConfig, qr_bytes
from .layout import (
    FallbackSection,
    RenderInputs,
    _compute_layout,
    _expand_gap_to_fill,
    _page_format,
)
from .templating import render_template


def render_frames_to_pdf(inputs: RenderInputs) -> None:
    if not inputs.frames:
        raise ValueError("frames cannot be empty")

    base_context = dict(inputs.context)
    doc_id = base_context.get("doc_id")
    if not isinstance(doc_id, str):
        doc_id = inputs.frames[0].doc_id.hex()
        base_context["doc_id"] = doc_id

    paper_size = str(base_context.get("paper_size") or "A4")
    doc_type = _doc_type_from_template(inputs.template_path)
    spec = _document_spec(doc_type, paper_size, base_context)

    key_lines = list(inputs.key_lines) if inputs.key_lines is not None else []
    if key_lines:
        spec["keys"]["lines"] = list(key_lines)

    initial_cfg = _layout_cfg(spec, doc_id=str(doc_id), page_label="Page 1 / 1")
    paper_format = _page_format(initial_cfg.get("page", {}))

    pdf = FPDF(unit="mm", format=cast(Any, paper_format))
    pdf.set_auto_page_break(False)

    layout, fallback_lines = _compute_layout(inputs, initial_cfg, pdf, key_lines)
    key_lines = list(layout.key_lines)
    spec["keys"]["lines"] = list(key_lines)

    keys_first_page_only = bool(spec["keys"].get("first_page_only", False))
    instructions_first_page_only = bool(
        spec["instructions"].get("first_page_only", False)
    )
    layout_rest = None
    if instructions_first_page_only or keys_first_page_only:
        layout_rest, _ = _compute_layout(
            inputs,
            initial_cfg,
            pdf,
            key_lines,
            include_keys=not keys_first_page_only,
            include_instructions=not instructions_first_page_only,
        )

    fallback_first = layout.fallback_lines_per_page
    fallback_rest = (
        layout_rest.fallback_lines_per_page if layout_rest else fallback_first
    )

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

    qr_config = inputs.qr_config or QrConfig()
    qr_payloads = list(inputs.qr_payloads) if inputs.qr_payloads is not None else [
        encode_frame(frame) for frame in inputs.frames
    ]
    if len(qr_payloads) != len(inputs.frames):
        raise ValueError("qr_payloads length must match frames")

    fallback_sections_data: list[dict[str, object]] | None = None
    fallback_state: dict[str, int] | None = None
    if inputs.render_fallback and inputs.fallback_sections:
        group_size = int(spec["fallback"].get("group_size", 4))
        line_length = int(layout.line_length)
        fallback_sections_data = []
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

    pages: list[dict[str, object]] = []
    for page_idx in range(total_pages):
        page_num = page_idx + 1
        page_label = f"Page {page_num} / {total_pages}"
        page_layout = layout_rest if layout_rest and page_idx > 0 else layout
        divider_y = (
            page_layout.margin
            + page_layout.header_height
            - spec["header"]["divider_thickness_mm"]
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
            for row in range(page_layout.rows):
                remaining = frames_in_page - row * page_layout.cols
                if remaining <= 0:
                    break
                cols_in_row = min(page_layout.cols, remaining)
                if cols_in_row == 1:
                    gap_x = page_layout.gap
                    x_start = page_layout.margin + (
                        page_layout.usable_w - page_layout.qr_size
                    ) / 2
                else:
                    gap_x = _expand_gap_to_fill(
                        page_layout.usable_w,
                        page_layout.qr_size,
                        page_layout.gap,
                        cols_in_row,
                    )
                    x_start = page_layout.margin

                for col in range(cols_in_row):
                    frame_idx = page_start + row * page_layout.cols + col
                    x = x_start + col * (page_layout.qr_size + gap_x)
                    y = page_layout.content_start_y + row * (page_layout.qr_size + gap_y)

                    qr_image = qr_bytes(qr_payloads[frame_idx], **_qr_kwargs(qr_config))
                    qr_slots.append(
                        {
                            "index": frame_idx + 1,
                            "x_mm": x,
                            "y_mm": y,
                            "size_mm": page_layout.qr_size,
                            "data_uri": _data_uri(qr_image),
                        }
                    )
                    slots_raw.append((frame_idx, x, y))

            if spec["qr_sequence"].get("enabled"):
                qr_sequence = _sequence_geometry(
                    slots_raw,
                    page_layout.qr_size,
                    float(spec["qr_sequence"]["label_offset_mm"]),
                )
            if slots_raw:
                outline_padding = max(
                    0.0, float(spec["qr_grid"].get("outline_padding_mm", 1.0))
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
                has_fallback = _fallback_sections_remaining(
                    fallback_sections_data, fallback_state
                )
            if has_fallback:
                if inputs.render_qr:
                    grid_height = (
                        page_layout.rows * page_layout.qr_size
                        + (page_layout.rows - 1) * page_layout.gap
                    )
                    fallback_y = page_layout.content_start_y + grid_height + page_layout.text_gap
                else:
                    fallback_y = page_layout.content_start_y

                available_height = (
                    page_layout.page_h - page_layout.margin - fallback_y
                )
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

    def _page_has_content(page: dict[str, object]) -> bool:
        if page.get("qr_slots"):
            return True
        if page.get("fallback_blocks"):
            return True
        if page.get("show_keys") and key_lines:
            return True
        return False

    while pages and not _page_has_content(pages[-1]):
        pages.pop()

    if pages:
        final_total = len(pages)
        for idx, page in enumerate(pages):
            page["page_num"] = idx + 1
            page["page_label"] = f"Page {idx + 1} / {final_total}"

    context = _template_context(spec, layout, pages, doc_id=str(doc_id))
    context["shard_index"] = base_context.get("shard_index", 1)
    context["shard_total"] = base_context.get("shard_total", 1)
    html = render_template(inputs.template_path, context)
    _render_html_to_pdf(html, inputs.output_path)


def _render_html_to_pdf(html: str, output_path: str | Path) -> None:
    output_path = Path(output_path)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.set_content(html, wait_until="networkidle")
        page.emulate_media(media="print")
        page.pdf(
            path=str(output_path),
            print_background=True,
            prefer_css_page_size=True,
            margin={"top": "0mm", "right": "0mm", "bottom": "0mm", "left": "0mm"},
        )
        browser.close()


def _doc_type_from_template(path: str | Path) -> str:
    name = Path(path).name.lower()
    if "signing_key_shard" in name:
        return "signing_key_shard"
    if "recovery" in name:
        return "recovery"
    if "kit" in name:
        return "kit"
    if "shard" in name:
        return "shard"
    return "main"


def _document_spec(
    doc_type: str,
    paper_size: str,
    context: dict[str, object],
) -> dict[str, dict[str, object]]:
    header = {
        "font_family": "Helvetica",
        "title_size": 20,
        "subtitle_size": 10,
        "meta_size": 8,
        "layout": "split",
        "split_left_ratio": 0.7,
        "title_style": "B",
        "subtitle_style": "I",
        "meta_style": "I",
        "title_color": [15, 30, 45],
        "subtitle_color": [70, 80, 90],
        "meta_color": [120, 130, 140],
        "divider_enabled": True,
        "divider_gap_mm": 2.5,
        "divider_thickness_mm": 0.5,
        "divider_color": [15, 30, 45],
        "doc_id_label": "Document ID:",
    }
    instructions = {
        "font_family": "Helvetica",
        "font_size": 9,
        "line_height_mm": 4.5,
        "label": "Instructions",
        "first_page_only": True,
        "label_layout": "column",
        "label_font_family": "Helvetica",
        "label_size": 7,
        "label_style": "B",
        "label_color": [90, 100, 110],
        "label_column_mm": 24,
        "label_gap_mm": 2,
        "indent_mm": 0,
        "text_color": [30, 40, 50],
        "lines": [],
    }
    keys = {
        "font_family": "Courier",
        "font_size": 8,
        "line_height_mm": 4.0,
        "label": "Keys",
        "label_layout": "column",
        "label_font_family": "Helvetica",
        "label_size": 7,
        "label_style": "B",
        "label_color": [90, 100, 110],
        "label_column_mm": 24,
        "label_gap_mm": 2,
        "indent_mm": 0,
        "text_color": [30, 40, 50],
        "lines": [],
        "first_page_only": False,
    }
    fallback = {
        "font_family": "Courier",
        "font_size": 10,
        "line_height_mm": 4.2,
        "padding_mm": 2.0,
        "label_font_family": "Helvetica",
        "label_size": 10,
        "label_style": "B",
        "label_color": [15, 30, 45],
        "label_align": "C",
        "group_size": 4,
        "line_length": 0,
        "line_count": 10,
        "text_color": [15, 30, 45],
    }
    page = {
        "size": paper_size,
        "margin_mm": 14,
        "header_height_mm": 16,
        "instructions_gap_mm": 4,
        "keys_gap_mm": 3,
    }

    qr_grid: dict[str, object] = {}
    qr_sequence: dict[str, object] = {"enabled": False}

    shard_index = int(context.get("shard_index") or 1)
    shard_total = int(context.get("shard_total") or 1)

    if doc_type == "main":
        header["title"] = "Main Document"
        header["subtitle"] = "Mode: passphrase"
        instructions["lines"] = [
            "Scan all QR codes in any order.",
            "Use the Recovery Document for text fallback if needed.",
        ]
        qr_grid = {
            "qr_size_mm": 58,
            "gap_mm": 3,
            "max_cols": 3,
            "max_rows": 4,
            "text_gap_mm": 2.5,
        }
    elif doc_type == "recovery":
        header["title"] = "Recovery Document"
        header["subtitle"] = "Keys + Text Fallback"
        instructions["lines"] = [
            "This document contains recovery keys and full text fallback.",
            "Keep it separate from the QR document.",
            "Fallback includes AUTH + MAIN sections; keep the labels when transcribing.",
        ]
        keys["first_page_only"] = True
    elif doc_type == "kit":
        header["title"] = "Recovery Kit"
        header["subtitle"] = "Offline HTML bundle"
        instructions["lines"] = [
            "Scan QR codes in order and concatenate the payloads.",
            "Write the output to recovery_kit.bundle.html.",
        ]
        if paper_size.strip().lower() == "letter":
            qr_size = 52
            max_rows = 4
        else:
            qr_size = 59
            max_rows = 3
        qr_grid = {
            "qr_size_mm": qr_size,
            "gap_mm": 2,
            "max_cols": 3,
            "max_rows": max_rows,
            "text_gap_mm": 3,
        }
        qr_sequence = {
            "enabled": True,
            "font_family": "Helvetica",
            "font_size": 12,
            "font_style": "B",
            "text_color": [15, 30, 45],
            "line_color": [110, 120, 130],
            "line_thickness_mm": 0.7,
            "label_offset_mm": 2.0,
        }
    elif doc_type == "signing_key_shard":
        header["title"] = "Signing Key Shard"
        header["subtitle"] = f"Signing key shard {shard_index} of {shard_total}"
        instructions["lines"] = [
            "This document is one shard of the signing key.",
            "Keep signing-key shards separate and secure.",
        ]
        qr_grid = {
            "qr_size_mm": 58,
            "gap_mm": 3,
            "max_cols": 3,
            "max_rows": 4,
            "text_gap_mm": 2.5,
        }
    else:
        header["title"] = "Shard Document"
        header["subtitle"] = f"Shard {shard_index} of {shard_total}"
        instructions["lines"] = [
            "This document is one shard of the passphrase.",
            "Keep shards separate and secure.",
        ]
        qr_grid = {
            "qr_size_mm": 58,
            "gap_mm": 3,
            "max_cols": 3,
            "max_rows": 4,
            "text_gap_mm": 2.5,
        }

    qr_grid.setdefault("outline_padding_mm", 1.0)

    return {
        "page": page,
        "header": header,
        "instructions": instructions,
        "keys": keys,
        "qr_grid": qr_grid,
        "qr_sequence": qr_sequence,
        "fallback": fallback,
    }


def _layout_cfg(spec: dict[str, dict[str, object]], doc_id: str, page_label: str) -> dict:
    header = dict(spec["header"])
    header["doc_id"] = doc_id
    header["page_label"] = page_label
    return {
        "page": dict(spec["page"]),
        "header": header,
        "instructions": dict(spec["instructions"]),
        "keys": dict(spec["keys"]),
        "qr_grid": dict(spec["qr_grid"]),
        "qr_sequence": dict(spec["qr_sequence"]),
        "fallback": dict(spec["fallback"]),
    }


def _template_context(
    spec: dict[str, dict[str, object]],
    layout,
    pages: list[dict[str, object]],
    *,
    doc_id: str,
) -> dict[str, object]:
    keys = dict(spec["keys"])
    keys_context = {
        "lines": list(keys.get("lines", [])),
    }

    return {
        "page_size_css": spec["page"].get("size", "A4"),
        "page_width_mm": layout.page_w,
        "page_height_mm": layout.page_h,
        "margin_mm": layout.margin,
        "usable_width_mm": layout.usable_w,
        "doc_id": doc_id,
        "keys": keys_context,
        "fallback": {"width_mm": layout.fallback_width},
        "pages": pages,
    }


def _sequence_geometry(
    slots: list[tuple[int, float, float]],
    qr_size: float,
    label_offset: float,
) -> dict[str, list[dict[str, float | str]]]:
    lines: list[dict[str, float]] = []
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
                labels.append({"text": number, "x": (line_start + line_end) / 2, "y": line_y - label_offset})
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
                    lines.append({"x1": center_x, "y1": mid_y, "x2": next_center_x, "y2": mid_y})
                    lines.append({"x1": next_center_x, "y1": mid_y, "x2": next_center_x, "y2": end_y})
                    labels.append(
                        {"text": number, "x": (center_x + next_center_x) / 2, "y": mid_y - label_offset}
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
        gap_lines = int(block.get("gap_lines") or 0)
        if gap_lines > 0:
            gap_mm = gap_lines * line_height
            cursor_y += gap_mm
            remaining -= gap_mm

        lines = block.get("lines", [])
        line_count = len(lines) if isinstance(lines, list) else 0
        block_height = (1 + line_count) * line_height
        block["y_mm"] = cursor_y
        block["height_mm"] = block_height
        cursor_y += block_height
        remaining -= block_height

    if blocks and remaining > 0:
        blocks[-1]["height_mm"] = float(blocks[-1]["height_mm"]) + remaining


def _data_uri(png_bytes: bytes) -> str:
    encoded = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _css_color(value: object, *, default: str | None = None) -> str:
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return f"rgb({int(value[0])}, {int(value[1])}, {int(value[2])})"
    if isinstance(value, str):
        return value
    return default or "rgb(0, 0, 0)"


def _qr_kwargs(config: QrConfig) -> dict[str, Any]:
    return cast(dict[str, Any], vars(config))


__all__ = [
    "FallbackSection",
    "RenderInputs",
    "_compute_layout",
    "render_frames_to_pdf",
]
