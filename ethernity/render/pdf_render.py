#!/usr/bin/env python3
from __future__ import annotations

import math
from pathlib import Path
import tempfile
from typing import Any, cast

from fpdf import FPDF

from ..encoding.framing import encode_frame
from ..qr.codec import QrConfig, qr_bytes
from .draw import _draw_header, _draw_instructions, _draw_keys
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

    pdf = FPDF(unit="mm", format=cast(Any, paper_format))
    pdf.set_auto_page_break(False)

    key_lines = list(inputs.key_lines) if inputs.key_lines is not None else keys_cfg.get("lines", [])
    layout, fallback_lines = _compute_layout(inputs, initial_cfg, pdf, key_lines)
    key_lines = list(layout.key_lines)
    base_context["key_lines"] = list(key_lines)

    qr_config = inputs.qr_config or QrConfig()

    for page_idx in range(layout.total_pages):
        page_num = page_idx + 1
        cfg = render_template(
            inputs.template_path,
            {**base_context, "page_num": page_num, "page_total": layout.total_pages},
        )
        pdf.add_page()
        _draw_header(pdf, cfg.get("header", {}), layout.margin, layout.header_height)
        _draw_instructions(pdf, cfg.get("instructions", {}), layout.margin, layout.instructions_y)
        _draw_keys(pdf, cfg.get("keys", {}), key_lines, layout.margin, layout.keys_y)

        if inputs.render_qr:
            page_start = page_idx * layout.per_page
            frames_in_page = min(layout.per_page, len(inputs.frames) - page_start)
            rows_for_page = layout.rows
            if frames_in_page > 0:
                rows_for_page = math.ceil(frames_in_page / layout.cols)
            gap_y = layout.gap
            if not inputs.render_fallback:
                if layout.gap_y_override is not None and rows_for_page == layout.rows:
                    gap_y = layout.gap_y_override
                else:
                    gap_y = _expand_gap_to_fill(
                        layout.usable_h_grid, layout.qr_size, layout.gap, rows_for_page
                    )

            qr_payloads = list(inputs.qr_payloads) if inputs.qr_payloads is not None else [
                encode_frame(frame) for frame in inputs.frames
            ]
            if len(qr_payloads) != len(inputs.frames):
                raise ValueError("qr_payloads length must match frames")

            for row in range(layout.rows):
                remaining = frames_in_page - row * layout.cols
                if remaining <= 0:
                    break
                cols_in_row = min(layout.cols, remaining)
                if cols_in_row == 1:
                    gap_x = layout.gap
                    x_start = layout.margin + (layout.usable_w - layout.qr_size) / 2
                else:
                    gap_x = _expand_gap_to_fill(
                        layout.usable_w, layout.qr_size, layout.gap, cols_in_row
                    )
                    x_start = layout.margin

                for col in range(cols_in_row):
                    frame_idx = page_start + row * layout.cols + col
                    x = x_start + col * (layout.qr_size + gap_x)
                    y = layout.content_start_y + row * (layout.qr_size + gap_y)

                    qr_image = qr_bytes(qr_payloads[frame_idx], **_qr_kwargs(qr_config))
                    _place_qr(pdf, qr_image, x, y, layout.qr_size)

        if inputs.render_fallback and fallback_lines:
            start = page_idx * layout.fallback_lines_per_page
            end = start + layout.fallback_lines_per_page
            lines = fallback_lines[start:end]
            if lines:
                if inputs.render_qr:
                    grid_height = layout.rows * layout.qr_size + (layout.rows - 1) * layout.gap
                    fallback_y = layout.content_start_y + grid_height + layout.text_gap
                else:
                    fallback_y = layout.content_start_y
                cell_margin = pdf.c_margin
                pdf.c_margin = 0
                _draw_fallback_lines(
                    pdf,
                    cfg.get("fallback", {}),
                    layout.margin,
                    fallback_y,
                    layout.fallback_width,
                    lines,
                    layout.line_height,
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
