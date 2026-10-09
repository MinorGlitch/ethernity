"""Measured inventory rows in the template's writable table."""

from __future__ import annotations

from dataclasses import dataclass

from ethernity.render.direct_pdf.artwork import Artwork, document_values, text_style
from ethernity.render.direct_pdf.artwork_recovery import place_elements
from ethernity.render.direct_pdf.content import InventoryRow, inventory_rows
from ethernity.render.direct_pdf.document_inputs import DocumentRenderContext, non_negative_int
from ethernity.render.direct_pdf.page import PaintPlan
from ethernity.render.direct_pdf.text_fit import fit_text_to_width
from ethernity.render.template import InventoryArtwork, LayoutElement, PageArtwork
from ethernity.render.types import RenderInputs


@dataclass(frozen=True)
class _MeasuredRow:
    """Row artwork and vertical extent in template coordinates."""

    elements: tuple[LayoutElement, ...]
    height: float


@dataclass(frozen=True)
class _PlacedRow:
    source: InventoryRow
    layout: _MeasuredRow
    offset_y: float


def _measure_row(painter: Artwork, spec: InventoryArtwork, row: InventoryRow) -> _MeasuredRow:
    values = {"identifier": row.identifier, "detail": row.detail, "status": row.status}
    sx, sy = painter.scale
    height = spec.row_height
    elements = []
    for element in spec.row:
        x, y, width, box_height = element.box
        if element.kind == "text" and element.fit == "wrap":
            fit = fit_text_to_width(
                painter.surface,
                element.text.format_map(values),
                text_style(painter.definition, element.style or ""),
                max_width_mm=width * sx,
                line_height_multiplier=element.line_height,
            )
            measured = max(box_height, fit.height_mm / sy)
            height = max(height, spec.row_height + measured - box_height)
            element = element.model_copy(update={"box": (x, y, width, measured)})
        elements.append(element)
    measured_elements = tuple(
        e.model_copy(update={"box": (*e.box[:3], height)})
        if e.kind == "panel" and e.box[3] == spec.row_height
        else e
        for e in elements
    )
    return _MeasuredRow(measured_elements, height)


def inventory_document(
    painter: Artwork, inputs: RenderInputs, context: DocumentRenderContext
) -> list[list[PaintPlan]]:
    document = painter.definition.document(inputs.doc_type)
    rows = inventory_rows(inputs)
    batches: list[tuple[PageArtwork, list[_PlacedRow]]] = []
    cursor = 0
    while cursor < len(rows):
        page = document.first if not batches else document.continuation or document.first
        spec = page.inventory
        if spec is None:
            raise ValueError("Inventory page requires a row layout")
        available = spec.row_height * spec.capacity
        batch: list[_PlacedRow] = []
        height = 0.0
        while cursor < len(rows):
            measured = _measure_row(painter, spec, rows[cursor])
            row_height = measured.height
            if row_height > available:
                raise ValueError("inventory row cannot fit on a page")
            if height + row_height > available + 1e-6:
                break
            batch.append(_PlacedRow(rows[cursor], measured, height))
            height += row_height
            cursor += 1
        batches.append((page, batch))
    values = document_values(context)
    values.update(
        page_count=len(batches),
        kit_qr_page_count=non_negative_int(inputs.context.get("kit_qr_page_count"), default=0),
        kit_qr_chunk_count=non_negative_int(inputs.context.get("kit_qr_chunk_count"), default=0),
    )
    pages = []
    for number, (page, batch) in enumerate(batches, 1):
        plans = painter.paint_plans(page, {**values, "page_number": number}, prefix=f"p{number}")
        assert page.inventory is not None
        for index, placed in enumerate(batch):
            row = placed.source
            plans.extend(
                place_elements(
                    painter,
                    placed.layout.elements,
                    {"identifier": row.identifier, "detail": row.detail, "status": row.status},
                    0,
                    page.inventory.top + placed.offset_y,
                    f"p{number}-inventory-{index}",
                )
            )
        pages.append(plans)
    return pages
