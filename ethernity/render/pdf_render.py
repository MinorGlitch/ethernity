#!/usr/bin/env python3
from __future__ import annotations

import math
from pathlib import Path
import tempfile
from typing import Any, cast

from fpdf import FPDF

from ..encoding.framing import encode_frame
from ..qr.codec import QrConfig, qr_bytes
from .draw import _draw_header, _draw_instructions, _draw_keys, _draw_qr_sequence
from .fallback import _draw_fallback_lines
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
    base_context.setdefault("doc_id", inputs.frames[0].doc_id.hex())
    if inputs.key_lines is not None:
        base_context.setdefault("key_lines", list(inputs.key_lines))
    else:
        base_context.setdefault("key_lines", [])

    initial_cfg = render_template(
        inputs.template_path,
        {**base_context, "page_num": 1, "page_total": 1},
    )
    page_cfg = initial_cfg.get("page", {})
    keys_cfg = initial_cfg.get("keys", {})
    paper_format = _page_format(page_cfg)
    keys_first_page_only = bool(keys_cfg.get("first_page_only", False))

    pdf = FPDF(unit="mm", format=cast(Any, paper_format))
    pdf.set_auto_page_break(False)

    key_lines = list(inputs.key_lines) if inputs.key_lines is not None else keys_cfg.get("lines", [])
    layout, fallback_lines = _compute_layout(inputs, initial_cfg, pdf, key_lines)
    key_lines = list(layout.key_lines)
    base_context["key_lines"] = list(key_lines)

    qr_config = inputs.qr_config or QrConfig()
    layout_rest = None
    fallback_first = layout.fallback_lines_per_page
    fallback_rest = fallback_first
    total_pages = layout.total_pages
    if keys_first_page_only and inputs.render_fallback and not inputs.render_qr:
        layout_rest, _ = _compute_layout(
            inputs, initial_cfg, pdf, key_lines, include_keys=False
        )
        fallback_rest = layout_rest.fallback_lines_per_page or fallback_first
        if fallback_lines and fallback_first > 0 and fallback_rest > 0:
            if len(fallback_lines) <= fallback_first:
                total_pages = 1
            else:
                remaining = len(fallback_lines) - fallback_first
                total_pages = 1 + math.ceil(remaining / fallback_rest)

    for page_idx in range(total_pages):
        page_num = page_idx + 1
        cfg = render_template(
            inputs.template_path,
            {**base_context, "page_num": page_num, "page_total": total_pages},
        )
        page_layout = layout_rest if layout_rest and page_idx > 0 else layout
        pdf.add_page()
        _draw_header(pdf, cfg.get("header", {}), page_layout.margin, page_layout.header_height)
        _draw_instructions(
            pdf,
            cfg.get("instructions", {}),
            page_layout.margin,
            page_layout.instructions_y,
        )
        if not (keys_first_page_only and page_idx > 0):
            _draw_keys(pdf, cfg.get("keys", {}), key_lines, page_layout.margin, page_layout.keys_y)

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

            qr_payloads = list(inputs.qr_payloads) if inputs.qr_payloads is not None else [
                encode_frame(frame) for frame in inputs.frames
            ]
            if len(qr_payloads) != len(inputs.frames):
                raise ValueError("qr_payloads length must match frames")

            qr_slots: list[tuple[int, float, float]] = []
            for row in range(page_layout.rows):
                remaining = frames_in_page - row * page_layout.cols
                if remaining <= 0:
                    break
                cols_in_row = min(page_layout.cols, remaining)
                if cols_in_row == 1:
                    gap_x = page_layout.gap
                    x_start = page_layout.margin + (page_layout.usable_w - page_layout.qr_size) / 2
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
                    _place_qr(pdf, qr_image, x, y, page_layout.qr_size)
                    qr_slots.append((frame_idx, x, y))

            _draw_qr_sequence(pdf, cfg.get("qr_sequence", {}), qr_slots, page_layout.qr_size)

        if inputs.render_fallback and fallback_lines:
            if layout_rest and page_idx > 0 and not inputs.render_qr:
                start = fallback_first + (page_idx - 1) * fallback_rest
                end = start + fallback_rest
            else:
                start = page_idx * layout.fallback_lines_per_page
                end = start + layout.fallback_lines_per_page
            lines = fallback_lines[start:end]
            if lines:
                if inputs.render_qr:
                    grid_height = (
                        page_layout.rows * page_layout.qr_size
                        + (page_layout.rows - 1) * page_layout.gap
                    )
                    fallback_y = page_layout.content_start_y + grid_height + page_layout.text_gap
                else:
                    fallback_y = page_layout.content_start_y
                cell_margin = pdf.c_margin
                pdf.c_margin = 0
                _draw_fallback_lines(
                    pdf,
                    cfg.get("fallback", {}),
                    page_layout.margin,
                    fallback_y,
                    page_layout.fallback_width,
                    lines,
                    page_layout.line_height,
                )
                pdf.c_margin = cell_margin

    pdf.output(str(inputs.output_path))


def _place_qr(pdf: FPDF, png_bytes: bytes, x: float, y: float, size: float) -> None:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as handle:
        handle.write(png_bytes)
        temp_path = handle.name
    try:
        pdf.image(temp_path, x=x, y=y, w=size, h=size)
    finally:
        Path(temp_path).unlink(missing_ok=True)


def _qr_kwargs(config: QrConfig) -> dict[str, Any]:
    return cast(dict[str, Any], vars(config))


__all__ = [
    "FallbackSection",
    "RenderInputs",
    "_compute_layout",
    "render_frames_to_pdf",
]
