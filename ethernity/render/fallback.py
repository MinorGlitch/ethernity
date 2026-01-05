#!/usr/bin/env python3
from __future__ import annotations

from typing import Sequence

from fpdf import FPDF

from .draw import _apply_text_color, _parse_color
from .layout import _is_fallback_label_line


def _draw_fallback_lines(
    pdf: FPDF,
    cfg: dict,
    x: float,
    y: float,
    width: float,
    lines: Sequence[str],
    line_height: float,
) -> None:
    if not lines:
        return

    font = cfg.get("font_family", "Courier")
    font_size = cfg.get("font_size", 8)
    text_color = _parse_color(cfg.get("text_color"))
    label_font = cfg.get("label_font_family", font)
    label_size = cfg.get("label_size", font_size)
    label_style = cfg.get("label_style", "B")
    label_color = _parse_color(cfg.get("label_color"))
    label_align = str(cfg.get("label_align", "C")).strip().upper()
    if label_align not in {"L", "C", "R"}:
        label_align = "C"

    for line in lines:
        if _is_fallback_label_line(line):
            pdf.set_font(label_font, style=label_style, size=label_size)
            _apply_text_color(pdf, label_color)
            pdf.set_xy(x, y)
            pdf.cell(width, line_height, line.strip(), align=label_align)
        else:
            pdf.set_font(font, size=font_size)
            _apply_text_color(pdf, text_color)
            pdf.set_xy(x, y)
            pdf.cell(width, line_height, line, align="L")
        y += line_height

    _apply_text_color(pdf, (0, 0, 0))
