#!/usr/bin/env python3
# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program.
# If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations

import functools
from datetime import date, datetime, timezone
from typing import Any, cast

from fpdf import FPDF

from ..encoding.framing import encode_frame
from ..qr.codec import QrConfig, qr_bytes
from .doc_types import DOC_TYPE_KIT
from .fallback import build_fallback_sections_data
from .html_to_pdf import render_html_to_pdf
from .layout import compute_layout
from .pages import build_pages
from .spec import DocumentSpec, document_spec
from .templating import render_template
from .text import page_format
from .types import FallbackSection, RenderInputs

_QR_URL_PREFIX = "https://ethernity.local/qr/"


def render_frames_to_pdf(inputs: RenderInputs) -> None:
    if not inputs.frames:
        raise ValueError("frames cannot be empty")

    base_context = dict(inputs.context)
    created_value = base_context.get("created_timestamp_utc")
    if created_value is None:
        created_value = base_context.get("created_date")

    created_dt = None
    created_timestamp_utc = None
    if isinstance(created_value, datetime):
        if created_value.tzinfo is None:
            created_value = created_value.replace(tzinfo=timezone.utc)
        created_dt = created_value.astimezone(timezone.utc)
    elif isinstance(created_value, date):
        created_dt = datetime.combine(created_value, datetime.min.time(), tzinfo=timezone.utc)
    elif isinstance(created_value, str):
        created_value = created_value.strip()
        if created_value:
            if "UTC" in created_value or created_value.endswith("Z"):
                created_timestamp_utc = created_value
            else:
                created_timestamp_utc = f"{created_value} UTC"

    if created_timestamp_utc is None:
        created_dt = created_dt or datetime.now(timezone.utc)
        created_timestamp_utc = created_dt.strftime("%Y-%m-%d %H:%M UTC")

    base_context["created_timestamp_utc"] = created_timestamp_utc
    if created_dt is not None:
        base_context["created_date"] = created_dt.date().isoformat()
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
    paper_format = page_format(layout_spec.page)

    pdf = FPDF(unit="mm", format=cast(Any, paper_format))
    pdf.set_auto_page_break(False)

    include_instructions = inputs.doc_type != DOC_TYPE_KIT
    layout, fallback_lines = compute_layout(
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
        layout_rest, _ = compute_layout(
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
    qr_resources: dict[str, tuple[str, bytes]] = {}
    qr_image_builder = functools.partial(
        _qr_payload_to_url,
        config=qr_config,
        resources=qr_resources,
    )

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
    context["created_timestamp_utc"] = created_timestamp_utc
    if created_dt is not None:
        context["created_date"] = created_dt.date().isoformat()
    html = render_template(inputs.template_path, context)
    render_html_to_pdf(html, inputs.output_path, resources=qr_resources)


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


def _qr_payload_to_url(
    payload: bytes | str,
    *,
    config: QrConfig,
    resources: dict[str, tuple[str, bytes]],
) -> str:
    kind = str(config.kind or "png").strip().lower()
    qr_image = qr_bytes(payload, **_qr_kwargs(config))
    url = f"{_QR_URL_PREFIX}{len(resources) + 1}.{kind}"
    resources[url] = (_qr_content_type(kind), qr_image)
    return url


def _qr_content_type(kind: str) -> str:
    if kind == "png":
        return "image/png"
    if kind == "svg":
        return "image/svg+xml"
    if kind in {"jpg", "jpeg"}:
        return "image/jpeg"
    if kind == "gif":
        return "image/gif"
    return "application/octet-stream"


def _qr_kwargs(config: QrConfig) -> dict[str, Any]:
    return vars(config)


__all__ = [
    "FallbackSection",
    "RenderInputs",
    "render_frames_to_pdf",
]
