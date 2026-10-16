"""Discover a template and execute the shared PDF engine."""

from __future__ import annotations

from ethernity.page_sizes import PaperSize
from ethernity.render.designs import load_design_definition
from ethernity.render.direct_pdf import document
from ethernity.render.direct_pdf.engine import plan_document
from ethernity.render.direct_pdf.page_geometry import resolve_page_geometry
from ethernity.render.types import RenderedDocumentSummary, RenderInputs, RenderResult


def _require_supported(inputs: RenderInputs) -> str:
    if not inputs.frames and (inputs.render_qr or inputs.render_fallback):
        raise ValueError("frames cannot be empty when QR or fallback rendering is enabled")
    definition = load_design_definition(inputs.design_name)
    if not definition.supports_doc_type(inputs.doc_type):
        raise ValueError(f"design {definition.name!r} does not support {inputs.doc_type!r}")
    geometry = resolve_page_geometry(inputs)
    definition.require_page_size(
        inputs.doc_type,
        PaperSize(
            name=geometry.paper_size,
            display_name=geometry.paper_size,
            width_mm=geometry.width_mm,
            height_mm=geometry.height_mm,
        ),
    )
    return definition.name


def render_frames_to_pdf(inputs: RenderInputs) -> RenderResult:
    style_name = _require_supported(inputs)
    return document.render_document_plan(
        inputs,
        style_name=style_name,
        builder=plan_document,
        creation_date=document.explicit_creation_date(inputs),
    )


def plan_document_summary(inputs: RenderInputs) -> RenderedDocumentSummary:
    _require_supported(inputs)
    return plan_document(document.build_document_surface(inputs), inputs).document_summary


__all__ = ["plan_document_summary", "render_frames_to_pdf"]
