"""Measured recovery content placed in the template's original document regions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from itertools import groupby

from ethernity.render.direct_pdf import fallback_layout
from ethernity.render.direct_pdf.artwork import (
    Artwork,
    document_values,
    expanded_elements,
    text_style,
)
from ethernity.render.direct_pdf.artwork_metadata import metadata_plans
from ethernity.render.direct_pdf.document_inputs import DocumentRenderContext
from ethernity.render.direct_pdf.metadata import RecoveryFields, recovery_fields
from ethernity.render.direct_pdf.page import PaintPlan
from ethernity.render.direct_pdf.recovery_metadata import paginate_recovery_passphrase
from ethernity.render.direct_pdf.types import PdfRect
from ethernity.render.template import FallbackProfile, LayoutElement, MetadataArtwork, PageArtwork
from ethernity.render.types import FallbackSummary, RenderInputs


def profile(
    painter: Artwork, data: FallbackProfile
) -> fallback_layout.ResponsiveFallbackPageProfile:
    x, y, width, height = data.box
    sx, sy = painter.scale
    return fallback_layout.ResponsiveFallbackPageProfile(
        PdfRect(x * sx, y * sy, width * sx, height * sy),
        fallback_layout.ResponsiveFallbackSpec(
            4,
            data.row_height * min(1, sy),
            text_style(painter.definition, data.body_style),
            text_style(painter.definition, data.number_style),
            data.left * sx,
            data.right * sx,
            data.reserved,
            data.number_gap * sx,
            data.number_width * sx,
            data.number_padding * sx,
            data.inline_number,
            data.safety,
            data.columns,
            data.column_gap * sx,
        ),
    )


def place_elements(
    painter: Artwork,
    elements: tuple[LayoutElement, ...],
    values: Mapping[str, str | int],
    x: float,
    y: float,
    prefix: str,
    height: float | None = None,
    width: float | None = None,
) -> list[PaintPlan]:
    placed = []
    for element in expanded_elements(painter.definition, elements):
        ex, ey, ew, eh = element.box
        box = (
            ex + x,
            ey + y,
            width if width is not None and element.stretch_x else ew,
            height if height is not None else eh,
        )
        update = {"box": box}
        if element.line:
            x1, y1, x2, y2 = element.line
            update["line"] = (x1 + x, y1 + y, x2 + x, y2 + y)
        placed.append(element.model_copy(update=update))
    return painter.paint_plans(PageArtwork(elements=tuple(placed)), values, prefix=prefix)


def fallback_plans(
    painter: Artwork, data: FallbackProfile, page: fallback_layout.FallbackPage
) -> list[PaintPlan]:
    area = data.box
    resolved = profile(painter, data)
    capacity = fallback_layout.fallback_capacity(
        resolved.area, row_height_mm=resolved.spec.row_height_mm, reserved_height_mm=data.reserved
    )
    row_height = (
        area[3] / capacity if data.fill_rows else resolved.spec.row_height_mm / painter.scale[1]
    )
    result = []
    row_elements = _numbered_row(painter, data, page)
    for section, rows in groupby(page.entries, key=lambda row: row.entry.section_index):
        rows = tuple(rows)
        start, end = min(row.row_index for row in rows), max(row.row_index for row in rows)
        result.extend(
            place_elements(
                painter,
                data.section,
                {},
                area[0],
                area[1] + start * row_height,
                f"p{page.page_number}-fallback-section-{section}",
                (end - start + 1) * row_height,
                area[2],
            )
        )
        for row in rows:
            title = isinstance(row.entry, fallback_layout.FallbackTitleEntry)
            values: dict[str, str | int]
            if isinstance(row.entry, fallback_layout.FallbackTitleEntry):
                values = {"title": row.entry.title}
            else:
                assert row.display_line_number is not None
                values = {"payload": row.entry.text, "number": row.display_line_number}

            elements = data.title if title else row_elements
            result.extend(
                place_elements(
                    painter,
                    elements,
                    values,
                    area[0] + row.column_index * (area[2] + data.column_gap) / data.columns,
                    area[1] + row.row_index * row_height,
                    f"p{page.page_number}-fallback-{section}-{row.row_index}-{row.column_index}",
                )
            )
    if data.empty:
        used = {row.row_index for row in page.entries}
        for index in range(capacity):
            if index not in used:
                result.extend(
                    place_elements(
                        painter,
                        data.empty,
                        {},
                        area[0],
                        area[1] + index * row_height,
                        f"p{page.page_number}-fallback-empty-{index}",
                    )
                )
    return result


def _numbered_row(
    painter: Artwork, data: FallbackProfile, page: fallback_layout.FallbackPage
) -> tuple[LayoutElement, ...]:
    """Grow the number gutter and consume the same width from the payload card."""
    if data.inline_number:
        return data.row
    spec = profile(painter, data).spec
    width = (
        fallback_layout.measured_fallback_number_width(
            painter.surface,
            page,
            style=spec.number_style,
            minimum_width_mm=spec.number_minimum_width_mm,
            padding_mm=spec.number_padding_mm,
        )
        / painter.scale[0]
    )
    extra = width - data.number_width
    elements = expanded_elements(painter.definition, data.row)
    payload = next(element for element in elements if element.text == "{payload}")
    payload_left, _, payload_width, _ = payload.box
    adjusted = []
    for element in elements:
        x, y, w, h = element.box
        if element.text == "{number:02d}.":
            w += extra
        elif (element.kind == "panel" or element.text == "{payload}") and (
            x <= payload_left and x + w >= payload_left + payload_width
        ):
            x += extra
            w -= extra
        adjusted.append(element.model_copy(update={"box": (x, y, w, h)}))
    return tuple(adjusted)


def recovery_document(
    painter: Artwork, inputs: RenderInputs, context: DocumentRenderContext
) -> tuple[list[list[PaintPlan]], FallbackSummary]:
    document = painter.definition.document(inputs.doc_type)
    spec = document.recovery
    meta = inputs.recovery_meta
    if spec is None or meta is None:
        raise ValueError("Recovery artwork requires recovery metadata and layout")
    pp = spec.passphrase
    if pp.single_line and meta.passphrase_lines and meta.passphrase_print_mode == "literal":
        meta = replace(meta, passphrase_lines=(" ".join(meta.passphrase_lines),))
    sx, sy = painter.scale
    continuation = PdfRect(
        *(value * (sx if i % 2 == 0 else sy) for i, value in enumerate(pp.continuation_box))
    )
    pagination = paginate_recovery_passphrase(
        painter.surface,
        meta,
        style=text_style(painter.definition, pp.style),
        guidance_style=text_style(painter.definition, pp.guidance_style),
        max_width_mm=pp.width * sx,
        inline_height_mm=pp.height,
        continuation_width_mm=continuation.width_mm,
        continuation_height_mm=continuation.height_mm,
        line_height_multiplier=pp.line_height,
    )
    fields = recovery_fields(pagination.inline_meta, single_line_passphrase=pp.single_line)
    values = document_values(context)
    values.update(
        passphrase="\n".join(fields.passphrase.value_lines),
        quorum="\n".join(fields.quorum.value_lines),
        signing_public_key="\n".join(fields.signing_key.value_lines),
        signing_public_key_inline=" ".join(fields.signing_key.value_lines),
        print_mode=pagination.inline_meta.passphrase_print_mode,
    )
    values.update(page="Page 1 / 1")
    metadata_spec = spec.metadata
    delta = 0.0
    if metadata_spec:
        delta = metadata_plans(painter, metadata_spec, fields, values, "measure").shift_y

        def moved_profile(data: FallbackProfile) -> FallbackProfile:
            x, y, w, h = data.box
            return data.model_copy(
                update={
                    "box": (x, y, w, h + delta)
                    if metadata_spec.bottom_anchor
                    else (x, y + delta, w, h - delta)
                }
            )

        if metadata_spec.flow != "boxes" or metadata_spec.bottom_anchor:
            spec = spec.model_copy(
                update={
                    "first": moved_profile(spec.first),
                    "continuation": spec.continuation
                    if metadata_spec.bottom_anchor or not metadata_spec.repeat_on_continuation
                    else moved_profile(spec.continuation),
                }
            )
    fallback = fallback_layout.resolve_responsive_fallback_pagination(
        painter.surface,
        inputs.fallback_sections or (),
        first_profile=profile(painter, spec.first),
        continuation_profile=profile(painter, spec.continuation),
        first_page_single_section=context.capabilities.recovery_first_page_single_section,
        section_gap_rows=spec.section_gap_rows,
    )
    values["page_count"] = len(fallback.pages) + len(pagination.continuation_pages)
    pages = []
    for page in fallback.pages:
        art = document.first if page.page_number == 1 else document.continuation or document.first
        row_spec = spec.first if page.page_number == 1 else spec.continuation
        show_metadata = metadata_spec is not None and (
            page.page_number == 1
            or (metadata_spec.repeat_on_continuation and metadata_spec.flow != "boxes")
        )
        if show_metadata and metadata_spec and delta:
            art = _shift_artwork(painter, art, metadata_spec, delta)
        values["page"] = f"Page {page.page_number} / {values['page_count']}"
        plans = painter.paint_plans(
            art, {**values, "page_number": page.page_number}, prefix=f"p{page.page_number}"
        )
        if show_metadata and metadata_spec:
            page_fields = _page_fields(
                fields, page.page_number, bool(pagination.continuation_pages)
            )
            metadata = metadata_plans(
                painter, metadata_spec, page_fields, values, f"p{page.page_number}"
            )
            plans.extend(metadata.plans)
        plans.extend(fallback_plans(painter, row_spec, page))
        pages.append(plans)
    for part in pagination.continuation_pages:
        number = len(pages) + 1
        plans = painter.paint_plans(
            pp.page,
            {
                **values,
                "page_number": number,
                "continuation_index": part.page_index,
                "continuation_count": part.total_pages,
                "continuation_text": part.text,
                "continuation_instructions": part.instructions,
                "print_mode": part.print_mode,
            },
            prefix=f"p{number}",
        )
        pages.append(plans)
    return pages, fallback_layout.build_fallback_summary(inputs, fallback.sections, fallback.pages)


def _shift_artwork(
    painter: Artwork, art: PageArtwork, metadata_spec: MetadataArtwork, delta: float
) -> PageArtwork:
    elements = []
    for element in expanded_elements(painter.definition, art.elements):
        x, y, w, h = element.box
        if metadata_spec.shift_start - 1e-6 <= y < metadata_spec.shift_end - 1e-6:
            y += delta
        if element.key.endswith("fallback-panel"):
            y += delta
            h -= delta
        elements.append(element.model_copy(update={"box": (x, y, w, h)}))
    art = art.model_copy(update={"elements": tuple(elements)})
    return art


def _page_fields(
    fields: RecoveryFields, page_number: int, has_continuation: bool
) -> RecoveryFields:
    if page_number > 1 and has_continuation:
        return replace(fields, passphrase=replace(fields.passphrase, value_lines=(), guidance=""))
    return fields
