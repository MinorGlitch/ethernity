"""One-page recovery sheets with measured fallback density and original artwork."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace

from ethernity.encoding.zbase32 import ZBASE32_ALPHABET
from ethernity.qr.codec import QrConfig
from ethernity.render.direct_pdf import document_inputs, fallback_layout
from ethernity.render.direct_pdf.artwork import (
    Artwork,
    color,
    document_values,
    expanded_elements,
    text_style,
)
from ethernity.render.direct_pdf.components import Line
from ethernity.render.direct_pdf.page import PaintPlan
from ethernity.render.direct_pdf.text_measure import measured_grouped_line_length
from ethernity.render.template import LayoutElement, PageArtwork, SheetDensity, SheetFallback
from ethernity.render.types import FallbackSummary, RenderInputs


@dataclass(frozen=True)
class _MeasuredSheet:
    """Readable fallback density, with column width in template coordinates."""

    density: SheetDensity
    sections: tuple[fallback_layout.FallbackSectionLines, ...]
    entries: tuple[fallback_layout.FallbackEntry, ...]
    column_width: float
    capacity: int


def sheet_document(
    painter: Artwork,
    inputs: RenderInputs,
    context: document_inputs.DocumentRenderContext,
    payload: bytes | str,
) -> tuple[list[list[PaintPlan]], FallbackSummary]:
    document = painter.definition.document(inputs.doc_type)
    spec = document.sheet
    if spec is None:
        raise ValueError("Recovery sheet requires a fallback layout")
    _, sy = painter.scale
    area = spec.box
    measured = _sheet_content(painter, inputs, spec)
    density, sections, entries = measured.density, measured.sections, measured.entries
    column_width = measured.column_width
    stride = (density.row_height + density.row_gap) / sy
    title_extra = density.title_extra_height / sy
    unlabeled = not sections[0].title
    display_entries = (
        (fallback_layout.FallbackTitleEntry(0, "SHARD PAYLOAD"), *entries) if unlabeled else entries
    )
    rows = min(measured.capacity, len(display_entries))
    if spec.balanced_columns:
        rows = math.ceil(len(display_entries) / density.columns)
    height = spec.top + rows * stride + title_extra + spec.bottom if spec.bottom_anchor else area[3]
    top = area[1] + area[3] - height if spec.bottom_anchor else area[1]
    values = document_values(context)
    values.update(
        page_number=1,
        page_count=1,
        doc_id_short=context.doc_id[:10],
        fallback_title=sections[0].title or "",
    )
    items = document_inputs.qr_payload_items((payload,), config=inputs.qr_config or QrConfig())
    art = _fit_qr(painter, document.first, spec.qr_bottom_gap, top)
    art = _center_qr(painter, art, spec.qr_area_top, top)
    plans = painter.paint_plans(art, values, prefix="p1", items=items)

    def draw(
        elements: tuple[LayoutElement, ...],
        x: float,
        y: float,
        vals: Mapping[str, str | int],
        prefix: str,
        size: float | None = None,
        column: bool = False,
        row_height: float | None = None,
    ) -> list[PaintPlan]:
        placed = []
        for e in expanded_elements(painter.definition, elements):
            ex, ey, w, h = e.box
            if e.stretch_x:
                w = w + column_width - (area[2] - 2 * spec.padding) if column else area[2]
            if e.stretch_y:
                h = height
            if size is not None and e.kind == "text":
                h = min(h, row_height or density.row_height) / sy
            placed.append(
                e.model_copy(
                    update={
                        "box": (ex + x, ey + y, w, h),
                        "font_size": (
                            max(
                                6.5,
                                min(text_style(painter.definition, e.style or "").size_pt, size),
                            )
                            if e.text == "{number:02d}."
                            else size
                        )
                        if e.kind == "text" and size
                        else None,
                    }
                )
            )
        return painter.paint_plans(PageArtwork(elements=tuple(placed)), vals, prefix=prefix)

    decoration = draw(spec.decoration, area[0], top, values, "p1-sheet")
    if spec.hatch:
        # Hatch underneath the border, headings and fallback text.
        plans.extend(decoration[:1])
        plans.extend(_hatch_plans(painter, spec, top, height))
        plans.extend(decoration[1:])
    else:
        plans.extend(decoration)
    for index, entry in enumerate(display_entries):
        column, row = divmod(index, rows)
        is_title = isinstance(entry, fallback_layout.FallbackTitleEntry)
        vals: dict[str, str | int] = (
            {"title": entry.title}
            if isinstance(entry, fallback_layout.FallbackTitleEntry)
            else {"payload": entry.text, "number": entry.line_number}
        )
        plans.extend(
            draw(
                spec.title if is_title else spec.row,
                area[0] + column * (column_width + spec.column_gap),
                top + spec.top + row * stride + (title_extra if column or row else 0),
                vals,
                f"p1-fallback-{index}",
                density.title_size if is_title else density.font_size,
                True,
                density.title_height if is_title else None,
            )
        )
    placed = tuple(
        fallback_layout.FallbackPageEntry(
            entry,
            index,
            None if isinstance(entry, fallback_layout.FallbackTitleEntry) else entry.line_number,
        )
        for index, entry in enumerate(entries)
    )
    summary = fallback_layout.build_fallback_summary(
        inputs, sections, (fallback_layout.FallbackPage(1, tuple(placed)),)
    )
    return [plans], summary


def _fit_qr(painter: Artwork, art: PageArtwork, gap: float | None, bottom: float) -> PageArtwork:
    """Keep a compact sheet's QR full-sized unless its fallback needs the space."""
    if gap is None:
        return art
    fitted = []
    for element in expanded_elements(painter.definition, art.elements):
        if element.qr_slot is not None:
            if element.kind != "image":
                raise ValueError("Sheet QR fitting requires an unframed QR image")
            x, y, width, height = element.box
            size = min(width, height, bottom - gap - y)
            if size <= 0:
                raise ValueError("Sheet QR image does not fit above the fallback card")
            element = element.model_copy(update={"box": (x + width - size, y, size, size)})
        fitted.append(element)
    return art.model_copy(update={"elements": tuple(fitted)})


def _center_qr(painter: Artwork, art: PageArtwork, top: float | None, bottom: float) -> PageArtwork:
    """Center the complete QR group above the measured fallback card."""
    if top is None:
        return art
    elements = expanded_elements(painter.definition, art.elements)
    qr = [element for element in elements if element.qr_slot is not None]
    if not qr:
        raise ValueError("Sheet QR centering requires a QR group")
    start = min(element.box[1] for element in qr)
    end = max(element.box[1] + element.box[3] for element in qr)
    if end - start > bottom - top:
        raise ValueError("Sheet QR group does not fit above the fallback card")
    offset = (top + bottom - start - end) / 2
    centered = []
    for element in elements:
        if element.qr_slot is not None:
            x, y, width, height = element.box
            element = element.model_copy(update={"box": (x, y + offset, width, height)})
            if element.line:
                x1, y1, x2, y2 = element.line
                element = element.model_copy(update={"line": (x1, y1 + offset, x2, y2 + offset)})
        centered.append(element)
    return art.model_copy(update={"elements": tuple(centered)})


def _sheet_content(painter: Artwork, inputs: RenderInputs, spec: SheetFallback) -> _MeasuredSheet:
    sx, sy = painter.scale
    area = spec.box
    for density in spec.profiles:
        column_width = (
            area[2] - 2 * spec.padding - (density.columns - 1) * spec.column_gap
        ) / density.columns
        font = replace(text_style(painter.definition, spec.body_style), size_pt=density.font_size)
        width = column_width * sx - spec.payload_inset
        if spec.numbering == "inline":
            width -= painter.surface.measure_text_width("99. ", font)
        payload_width = min(
            (
                element.box[2]
                + (column_width - (area[2] - 2 * spec.padding) if element.stretch_x else 0)
            )
            * sx
            for element in expanded_elements(painter.definition, spec.row)
            if "{payload}" in element.text
        )
        width = min(width, payload_width)
        length = measured_grouped_line_length(
            painter.surface,
            style=font,
            alphabet=ZBASE32_ALPHABET,
            group_size=4,
            max_width_mm=width,
            safety_mm=spec.safety,
        )
        sections = fallback_layout.fallback_sections(
            inputs.fallback_sections or (), group_size=4, line_length=length
        )
        entries = fallback_layout.fallback_entries(sections)
        stride = (density.row_height + density.row_gap) / sy
        capacity = math.floor(
            (area[3] - spec.top - spec.bottom - density.title_extra_height / sy) / stride
        )
        if capacity > 0 and len(entries) + int(not sections[0].title) <= capacity * density.columns:
            break
    else:
        raise ValueError("Recovery sheet fallback exceeds its readable one-page capacity")
    return _MeasuredSheet(density, sections, entries, column_width, capacity)


def _hatch_plans(
    painter: Artwork, spec: SheetFallback, top: float, height: float
) -> list[PaintPlan]:
    """Place hatch lines from template coordinates into physical page coordinates."""
    assert spec.hatch is not None
    sx, sy = painter.scale
    area = spec.box
    plans: list[PaintPlan] = []
    left = (area[0] + spec.hatch_inset) * sx
    right = (area[0] + area[2] - spec.hatch_inset) * sx
    ht = (height - 2 * spec.hatch_inset) * sy
    yt = (top + spec.hatch_inset) * sy
    offset = left - ht
    index = 0
    while offset <= right:
        x1 = max(left, offset)
        y1 = yt + max(0, left - offset)
        x2 = min(right, offset + ht)
        y2 = yt + ht - max(0, offset + ht - right)
        if y1 <= yt + ht and y2 >= yt and (x1 != x2 or y1 != y2):
            plans.append(
                Line(f"p1-sheet-hatch-{index}", color(spec.hatch), 0.12).plan(
                    painter.surface, start_x_mm=x1, start_y_mm=y1, end_x_mm=x2, end_y_mm=y2
                )
            )
        offset += spec.hatch_step
        index += 1
    return plans
