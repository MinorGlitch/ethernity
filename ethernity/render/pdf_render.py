#!/usr/bin/env python3
from __future__ import annotations

import base64
import functools
from pathlib import Path
from typing import Any, cast

from fpdf import FPDF
from playwright.sync_api import sync_playwright

from ..encoding.framing import encode_frame
from ..qr.codec import QrConfig, qr_bytes
from .layout import (
    FallbackSection,
    RenderInputs,
    build_fallback_sections_data,
    build_pages,
    _compute_layout,
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

    qr_config = inputs.qr_config or QrConfig()
    qr_payloads = list(inputs.qr_payloads) if inputs.qr_payloads is not None else [
        encode_frame(frame) for frame in inputs.frames
    ]
    if len(qr_payloads) != len(inputs.frames):
        raise ValueError("qr_payloads length must match frames")

    fallback_sections_data, fallback_state = build_fallback_sections_data(
        inputs,
        spec,
        layout,
    )
    qr_image_builder = functools.partial(_qr_payload_to_data_uri, config=qr_config)

    pages = build_pages(
        inputs=inputs,
        spec=spec,
        layout=layout,
        layout_rest=layout_rest,
        fallback_lines=fallback_lines,
        qr_payloads=qr_payloads,
        qr_image_builder=qr_image_builder,
        fallback_sections_data=fallback_sections_data,
        fallback_state=fallback_state,
        key_lines=key_lines,
        keys_first_page_only=keys_first_page_only,
    )

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

    shard_index = _int_value(context.get("shard_index"), default=1)
    shard_total = _int_value(context.get("shard_total"), default=1)

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
    raw_lines = keys.get("lines")
    keys_context = {
        "lines": list(raw_lines) if isinstance(raw_lines, list) else [],
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




def _data_uri(png_bytes: bytes) -> str:
    encoded = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _qr_payload_to_data_uri(payload: bytes | str, *, config: QrConfig) -> str:
    qr_image = qr_bytes(payload, **_qr_kwargs(config))
    return _data_uri(qr_image)


def _int_value(value: object, *, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


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
