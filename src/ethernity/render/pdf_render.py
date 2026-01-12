#!/usr/bin/env python3
from __future__ import annotations

import base64
import functools
from typing import Any, cast

from fpdf import FPDF

from ..encoding.framing import encode_frame
from ..qr.codec import QrConfig, qr_bytes
from .doc_types import DOC_TYPE_KIT
from .html_to_pdf import render_html_to_pdf
from .layout import (
    FallbackSection,
    RenderInputs,
    _compute_layout,
    _page_format,
    build_fallback_sections_data,
    build_pages,
)
from .spec import DocumentSpec, document_spec
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
    doc_type = inputs.doc_type
    if not doc_type:
        raise ValueError("doc_type is required for rendering")
    spec = document_spec(doc_type, paper_size, base_context)

    key_lines = list(inputs.key_lines) if inputs.key_lines is not None else []
    layout_spec = _layout_spec(spec, doc_id=str(doc_id), page_label="Page 1 / 1")
    paper_format = _page_format(layout_spec.page)

    pdf = FPDF(unit="mm", format=cast(Any, paper_format))
    pdf.set_auto_page_break(False)

    include_instructions = inputs.doc_type != DOC_TYPE_KIT
    layout, fallback_lines = _compute_layout(
        inputs,
        layout_spec,
        pdf,
        key_lines,
        include_instructions=include_instructions,
    )
    key_lines = list(layout.key_lines)
    spec = spec.with_key_lines(key_lines)
    layout_spec = _layout_spec(spec, doc_id=str(doc_id), page_label="Page 1 / 1")

    keys_first_page_only = bool(spec.keys.first_page_only)
    instructions_first_page_only = bool(spec.instructions.first_page_only)
    layout_rest = None
    if instructions_first_page_only or keys_first_page_only:
        layout_rest, _ = _compute_layout(
            inputs,
            layout_spec,
            pdf,
            key_lines,
            include_keys=not keys_first_page_only,
            include_instructions=include_instructions and not instructions_first_page_only,
        )

    qr_config = inputs.qr_config or QrConfig()
    qr_payloads = (
        list(inputs.qr_payloads)
        if inputs.qr_payloads is not None
        else [encode_frame(frame) for frame in inputs.frames]
    )
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
    render_html_to_pdf(html, inputs.output_path)


def _layout_spec(spec: DocumentSpec, doc_id: str, page_label: str) -> DocumentSpec:
    return spec.with_header(doc_id=doc_id, page_label=page_label)


def _template_context(
    spec: DocumentSpec,
    layout,
    pages: list[dict[str, object]],
    *,
    doc_id: str,
) -> dict[str, object]:
    return {
        "page_size_css": spec.page.size,
        "page_width_mm": layout.page_w,
        "page_height_mm": layout.page_h,
        "margin_mm": layout.margin,
        "usable_width_mm": layout.usable_w,
        "doc_id": doc_id,
        "keys": {"lines": list(spec.keys.lines)},
        "fallback": {"width_mm": layout.fallback_width},
        "pages": pages,
    }


def _data_uri(png_bytes: bytes) -> str:
    encoded = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _qr_payload_to_data_uri(payload: bytes | str, *, config: QrConfig) -> str:
    qr_image = qr_bytes(payload, **_qr_kwargs(config))
    return _data_uri(qr_image)


def _qr_kwargs(config: QrConfig) -> dict[str, Any]:
    return vars(config)


__all__ = [
    "FallbackSection",
    "RenderInputs",
    "_compute_layout",
    "render_frames_to_pdf",
]
