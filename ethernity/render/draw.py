#!/usr/bin/env python3
from __future__ import annotations

from typing import Sequence

from fpdf import FPDF, XPos, YPos

from .layout import _body_line_height, _cfg_float, _label_line_height


def _draw_header(pdf: FPDF, cfg: dict, margin: float, header_height: float) -> None:
    font = cfg.get("font_family", "Helvetica")
    title = cfg.get("title", "")
    subtitle = cfg.get("subtitle", "")
    doc_id_label = cfg.get("doc_id_label", "")
    doc_id = cfg.get("doc_id", "")
    page_label = cfg.get("page_label", "")
    layout = str(cfg.get("layout", "stacked")).lower()
    split_ratio = cfg.get("split_left_ratio", 0.65)
    title_style = cfg.get("title_style", "")
    subtitle_style = cfg.get("subtitle_style", "")
    meta_style = cfg.get("meta_style", "")
    title_color = _parse_color(cfg.get("title_color"))
    subtitle_color = _parse_color(cfg.get("subtitle_color"))
    meta_color = _parse_color(cfg.get("meta_color"))

    pdf.set_xy(margin, margin)

    if layout == "split":
        try:
            ratio = float(split_ratio)
        except (TypeError, ValueError):
            ratio = 0.65
        ratio = max(0.5, min(ratio, 0.8))
        usable_w = pdf.w - 2 * margin
        left_w = usable_w * ratio
        right_w = usable_w - left_w
        x_left = margin
        x_right = margin + left_w

        y_left = margin
        if title:
            pdf.set_font(font, style=title_style, size=cfg.get("title_size", 14))
            _apply_text_color(pdf, title_color)
            pdf.set_xy(x_left, y_left)
            pdf.cell(left_w, _line_height(pdf), title, align="L")
            y_left += _line_height(pdf)
        if subtitle:
            pdf.set_font(font, style=subtitle_style, size=cfg.get("subtitle_size", 10))
            _apply_text_color(pdf, subtitle_color)
            pdf.set_xy(x_left, y_left)
            pdf.cell(left_w, _line_height(pdf), subtitle, align="L")
            y_left += _line_height(pdf)

        right_lines: list[str] = []
        if page_label:
            right_lines.append(page_label)
        if doc_id_label or doc_id:
            right_lines.append(f"{doc_id_label} {doc_id}".strip())

        y_right = margin
        if right_lines:
            pdf.set_font(font, style=meta_style, size=cfg.get("meta_size", 8))
            _apply_text_color(pdf, meta_color)
            for line in right_lines:
                pdf.set_xy(x_right, y_right)
                pdf.cell(right_w, _line_height(pdf), line, align="R")
                y_right += _line_height(pdf)

        content_bottom = max(y_left, y_right)
        divider_enabled = bool(cfg.get("divider_enabled", False))
        if divider_enabled:
            gap = float(cfg.get("divider_gap_mm", 2))
            thickness = float(cfg.get("divider_thickness_mm", 0.4))
            divider_color = _parse_color(cfg.get("divider_color")) or (80, 80, 80)
            y = content_bottom + gap
            pdf.set_draw_color(*divider_color)
            pdf.set_line_width(thickness)
            pdf.line(margin, y, pdf.w - margin, y)
        _apply_text_color(pdf, (0, 0, 0))
        return

    if title:
        pdf.set_font(font, style=title_style, size=cfg.get("title_size", 14))
        _apply_text_color(pdf, title_color)
        pdf.cell(0, _line_height(pdf), title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    if subtitle:
        pdf.set_font(font, style=subtitle_style, size=cfg.get("subtitle_size", 10))
        _apply_text_color(pdf, subtitle_color)
        pdf.cell(0, _line_height(pdf), subtitle, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    if doc_id_label or doc_id or page_label:
        pdf.set_font(font, style=meta_style, size=cfg.get("meta_size", 8))
        _apply_text_color(pdf, meta_color)
        if doc_id_label or doc_id:
            pdf.cell(
                0,
                _line_height(pdf),
                f"{doc_id_label} {doc_id}".strip(),
                new_x=XPos.LMARGIN,
                new_y=YPos.NEXT,
            )
        if page_label:
            pdf.cell(0, _line_height(pdf), page_label, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    divider_enabled = bool(cfg.get("divider_enabled", False))
    if divider_enabled:
        gap = float(cfg.get("divider_gap_mm", 2))
        thickness = float(cfg.get("divider_thickness_mm", 0.4))
        divider_color = _parse_color(cfg.get("divider_color")) or (80, 80, 80)
        y = pdf.get_y() + gap
        pdf.set_draw_color(*divider_color)
        pdf.set_line_width(thickness)
        pdf.line(margin, y, pdf.w - margin, y)

    _apply_text_color(pdf, (0, 0, 0))


def _draw_instructions(pdf: FPDF, cfg: dict, x: float, y: float) -> None:
    lines = cfg.get("lines", [])
    _draw_lines(pdf, cfg, lines, x, y)


def _draw_keys(pdf: FPDF, cfg: dict, lines: Sequence[str], x: float, y: float) -> None:
    _draw_lines(pdf, cfg, lines, x, y)


def _draw_lines(pdf: FPDF, cfg: dict, lines: Sequence[str], x: float, y: float) -> None:
    label = cfg.get("label")
    if not lines and not label:
        return

    font = cfg.get("font_family", "Helvetica")
    font_size = cfg.get("font_size", 8)
    line_height = _body_line_height(cfg)
    indent = _cfg_float(cfg, "indent_mm", 0.0)
    text_color = _parse_color(cfg.get("text_color"))

    label_layout = str(cfg.get("label_layout", "stacked")).lower()
    label_text = str(label) if label else ""
    body_x = x + indent
    body_y = y

    if label_text:
        label_font = cfg.get("label_font_family", font)
        label_size = cfg.get("label_size", font_size)
        label_style = cfg.get("label_style", "")
        label_color = _parse_color(cfg.get("label_color"))
        label_height = _label_line_height(cfg)

        if label_layout == "column":
            label_column = _cfg_float(cfg, "label_column_mm", 0.0)
            if label_column <= 0:
                label_layout = "stacked"
            else:
                label_gap = _cfg_float(cfg, "label_gap_mm", 0.0)
                pdf.set_font(label_font, style=label_style, size=label_size)
                _apply_text_color(pdf, label_color)
                pdf.set_xy(x, y)
                pdf.cell(label_column, label_height, label_text, align="L")
                body_x = x + label_column + label_gap + indent

        if label_layout != "column":
            label_gap = _cfg_float(cfg, "label_gap_mm", 0.0)
            pdf.set_font(label_font, style=label_style, size=label_size)
            _apply_text_color(pdf, label_color)
            pdf.set_xy(x, y)
            pdf.cell(0, label_height, label_text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            body_x = x + indent
            body_y = y + label_height + label_gap

    if not lines:
        _apply_text_color(pdf, (0, 0, 0))
        return

    pdf.set_font(font, size=font_size)
    _apply_text_color(pdf, text_color)
    pdf.set_xy(body_x, body_y)
    for line in lines:
        pdf.cell(0, line_height, line, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    _apply_text_color(pdf, (0, 0, 0))


def _line_height(pdf: FPDF, multiplier: float = 1.2) -> float:
    return pdf.font_size * multiplier


def _parse_color(value: object) -> tuple[int, int, int] | None:
    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            return (int(value[0]), int(value[1]), int(value[2]))
        except (TypeError, ValueError):
            return None
    return None


def _apply_text_color(pdf: FPDF, color: tuple[int, int, int] | None) -> None:
    if color is None:
        pdf.set_text_color(0, 0, 0)
        return
    pdf.set_text_color(*color)
