"""One document engine for data-only PDF templates."""

from __future__ import annotations

from ethernity.page_sizes import PaperSize
from ethernity.qr.codec import QrConfig
from ethernity.render.checks import build_rendered_document_summary
from ethernity.render.design_style import load_page_template
from ethernity.render.direct_pdf import document_inputs
from ethernity.render.direct_pdf.artwork import Artwork, document_values
from ethernity.render.direct_pdf.artwork_inventory import inventory_document
from ethernity.render.direct_pdf.artwork_recovery import recovery_document
from ethernity.render.direct_pdf.artwork_sheet import sheet_document
from ethernity.render.direct_pdf.components import ImageBoxPlan, TextBoxPlan
from ethernity.render.direct_pdf.document import DirectPdfDocumentPlan
from ethernity.render.direct_pdf.page import (
    LayoutRegion,
    PaintPlan,
    SeparationConstraint,
    build_page_plan,
)
from ethernity.render.direct_pdf.page_geometry import resolve_page_geometry
from ethernity.render.direct_pdf.surface import PdfSurface
from ethernity.render.doc_types import (
    DOC_TYPE_KIT,
    DOC_TYPE_KIT_INDEX,
    DOC_TYPE_MAIN,
    DOC_TYPE_RECOVERY,
    DOC_TYPE_SHARD,
    DOC_TYPE_SIGNING_KEY_SHARD,
)
from ethernity.render.types import FallbackSummary, RenderInputs


def plan_document(surface: PdfSurface, inputs: RenderInputs) -> DirectPdfDocumentPlan:
    """Validate once, compose measured blocks, and account for every payload."""
    kind = inputs.doc_type.strip().lower()
    if kind in (DOC_TYPE_MAIN, DOC_TYPE_KIT):
        document_inputs.validate_qr_inputs(inputs, expected_doc_type=kind)
    elif kind == DOC_TYPE_RECOVERY:
        document_inputs.validate_recovery_inputs(inputs)
    elif kind in (DOC_TYPE_SHARD, DOC_TYPE_SIGNING_KEY_SHARD):
        document_inputs.validate_single_qr_fallback_inputs(inputs, expected_doc_type=kind)
    elif kind == DOC_TYPE_KIT_INDEX:
        document_inputs.validate_kit_index_inputs(inputs)
    else:
        raise ValueError(f"unsupported document type: {kind}")

    context = document_inputs.build_document_render_context(inputs, doc_type=kind)
    geometry = resolve_page_geometry(inputs)
    page = PaperSize(
        geometry.paper_size, geometry.paper_size, geometry.width_mm, geometry.height_mm
    )
    painter = Artwork(surface, load_page_template(inputs.design_name, page), geometry.rect)
    fallback: FallbackSummary | None = None
    payloads: tuple[bytes | str, ...] = ()
    physical_indexes: tuple[int, ...] = ()
    if kind in (DOC_TYPE_MAIN, DOC_TYPE_KIT):
        payloads = document_inputs.resolved_qr_payloads(inputs)
        pages = _qr_document(painter, inputs, context, payloads)
        physical_indexes = tuple(range(len(payloads)))
    elif kind == DOC_TYPE_RECOVERY:
        pages, fallback = recovery_document(painter, inputs, context)
    elif kind in (DOC_TYPE_SHARD, DOC_TYPE_SIGNING_KEY_SHARD):
        payloads = (document_inputs.resolved_single_qr_payload(inputs),)
        pages, fallback = sheet_document(painter, inputs, context, payloads[0])
        physical_indexes = (0,)
    else:
        pages = inventory_document(painter, inputs, context)
    page_plans = tuple(
        build_page_plan(
            page_number=number,
            rect=painter.page,
            plans=content,
            separation_constraints=_content_constraints(content),
        )
        for number, content in enumerate(pages, 1)
    )
    summary = build_rendered_document_summary(
        inputs,
        qr_payloads=payloads,
        encoded_payload_count=len(inputs.frames),
        physical_qr_count=len(physical_indexes),
        physical_qr_payload_indexes=physical_indexes,
        page_count=len(pages),
        fallback_summary=fallback,
    )
    return DirectPdfDocumentPlan(page_plans, summary, fallback)


def _qr_document(
    painter: Artwork,
    inputs: RenderInputs,
    context: document_inputs.DocumentRenderContext,
    payloads: tuple[bytes | str, ...],
) -> list[list[PaintPlan]]:
    definition = painter.definition
    document = definition.document(inputs.doc_type)
    continuation = document.continuation or document.first
    if min(document.first.qr_capacity, continuation.qr_capacity) < 1:
        raise ValueError("QR artwork must contain at least one slot on every page")
    items = document_inputs.qr_payload_items(payloads, config=inputs.qr_config or QrConfig())
    batches = []
    cursor = 0
    while cursor < len(items):
        page = document.first if cursor == 0 else continuation
        batches.append((page, items[cursor : cursor + page.qr_capacity]))
        cursor += page.qr_capacity
    values = document_values(context)
    batches.extend((page, ()) for page in document.trailing)
    values.update(page_count=len(batches), segment_count=len(items))
    return [
        painter.paint_plans(
            page, {**values, "page_number": number}, prefix=f"p{number}", items=batch
        )
        for number, (page, batch) in enumerate(batches, 1)
    ]


def _content_constraints(plans: list[PaintPlan]) -> tuple[SeparationConstraint, ...]:
    """Check visible ink and QR regions; decorative panels may contain their text."""
    regions = []
    for plan in plans:
        if isinstance(plan, TextBoxPlan):
            rect = plan.layout.used_rect
        elif isinstance(plan, ImageBoxPlan):
            rect = plan.layout.rect
        else:
            continue
        if rect.width_mm > 0 and rect.height_mm > 0:
            regions.append(LayoutRegion(plan.component_id, rect))
    # For each rectangle, check the next visible rectangle in the same horizontal span.
    # If that pair is separate, every later rectangle in that span is also below it.
    regions.sort(key=lambda region: region.rect.y_mm)
    constraints = []
    for index, first in enumerate(regions):
        for second in regions[index + 1 :]:
            if min(first.rect.right_mm, second.rect.right_mm) > max(
                first.rect.x_mm, second.rect.x_mm
            ):
                constraints.append(SeparationConstraint(f"content-{index}", first, second))
                break
    return tuple(constraints)
