"""Forge recovery document rendering through direct PDF primitives.

This module is the first `RenderInputs`-driven production slice of the direct renderer. It keeps
browser-independent geometry here, while reusing the existing render semantics for copy, fallback
encoding, doc types, recovery metadata, and proofs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from ethernity.core.bounds import MAX_FALLBACK_LINES
from ethernity.encoding.framing import encode_frame
from ethernity.encoding.zbase32 import ZBASE32_ALPHABET, encode_zbase32
from ethernity.render.direct_pdf.assets import packaged_direct_pdf_assets
from ethernity.render.direct_pdf.components import (
    Panel,
    Rule,
    TextAlign,
    TextBox,
)
from ethernity.render.direct_pdf.debug import write_direct_layout_debug_json
from ethernity.render.direct_pdf.forge.common import (
    FORGE_SLATE_50,
    FORGE_SLATE_100,
    FORGE_SLATE_200,
    FORGE_SLATE_300,
    FORGE_SLATE_500,
    FORGE_SLATE_600,
    FORGE_SLATE_800,
    FORGE_SLATE_900,
    ForgePageLayout,
    ForgeShellContext,
    build_forge_content_constraints,
    build_forge_footer_plans,
    build_forge_header_plans,
    build_forge_page_layout,
    build_forge_shell_context,
)
from ethernity.render.direct_pdf.forge.theme import FORGE_THEME
from ethernity.render.direct_pdf.layout_proof import build_direct_layout_proof
from ethernity.render.direct_pdf.page import (
    ComponentGroup,
    DirectPdfPagePlan,
    PaintPlan,
    SeparationConstraint,
    build_page_plan,
)
from ethernity.render.direct_pdf.page_geometry import resolve_page_geometry
from ethernity.render.direct_pdf.recovery_metadata import (
    RecoveryPassphraseContinuationPage,
    RecoveryPassphrasePagination,
    paginate_recovery_passphrase,
)
from ethernity.render.direct_pdf.structured_common import component_prefix
from ethernity.render.direct_pdf.surface import FpdfSurface, PdfSurface
from ethernity.render.direct_pdf.text_fit import TextFitPolicy, fit_text_to_width
from ethernity.render.direct_pdf.types import PdfRect, TextStyle
from ethernity.render.doc_types import DOC_TYPE_RECOVERY
from ethernity.render.fallback_text import fallback_section_title, format_zbase32_lines
from ethernity.render.proofs import build_render_artifact_proof, frame_digest
from ethernity.render.recovery_meta import RecoveryMeta, recovery_passphrase_display
from ethernity.render.types import (
    FallbackSection,
    RenderArtifactProof,
    RenderFallbackProof,
    RenderInputs,
    RenderResult,
)

_COMPONENT_BASE = "forge-recovery"
_FALLBACK_ROW_HEIGHT_MM = 6.4
_FALLBACK_COLUMN_GAP_MM = 12.0
_FALLBACK_MINIMUM_LINE_NUMBER_WIDTH_MM = 8.5
_FALLBACK_LINE_NUMBER_PADDING_MM = 0.8
_FALLBACK_LINE_GAP_MM = 1.5
_FALLBACK_GROUP_SIZE = 4
_FALLBACK_LINE_LENGTH = 44
_FALLBACK_PAYLOAD_MIN_FIT_SIZE_PT = 7.0
_METADATA_VALUE_PADDING_TOP_MM = 2.0
_METADATA_VALUE_PADDING_BOTTOM_MM = 0.2
_ICON_WARNING = chr(0xE002)


@dataclass(frozen=True)
class ForgeRecoveryDirectPlan:
    """Measured pages and app-wide proofs for one direct Forge recovery render."""

    page_plans: tuple[DirectPdfPagePlan, ...]
    fallback_proof: RenderFallbackProof
    artifact_proof: RenderArtifactProof


@dataclass(frozen=True)
class _ForgeRecoveryGeometry:
    layout: ForgePageLayout
    first_page_fallback_area: PdfRect
    continuation_fallback_area: PdfRect
    metadata_top_mm: float
    metadata_rows: tuple[_ForgeMetadataRowGeometry, ...]


@dataclass(frozen=True)
class _ForgeMetadataRowGeometry:
    label: str
    guidance: str
    guidance_height_mm: float
    text: str
    box_height_mm: float


@dataclass(frozen=True)
class _FallbackSectionLines:
    section_index: int
    title: str | None
    lines: tuple[str, ...]


@dataclass(frozen=True)
class _FallbackTitleEntry:
    section_index: int
    title: str


@dataclass(frozen=True)
class _FallbackLineEntry:
    section_index: int
    line_number: int
    text: str


_FallbackEntry = _FallbackTitleEntry | _FallbackLineEntry


@dataclass(frozen=True)
class _FallbackPageEntry:
    entry: _FallbackEntry
    row_index: int
    column_index: int | None
    display_line_number: int | None


@dataclass(frozen=True)
class _FallbackPageLayout:
    page_number: int
    area: PdfRect
    rows_per_column: int
    entries: tuple[_FallbackPageEntry, ...]


def _forge_recovery_geometry(
    surface: PdfSurface,
    inputs: RenderInputs,
    recovery_meta: RecoveryMeta,
) -> _ForgeRecoveryGeometry:
    layout = build_forge_page_layout(resolve_page_geometry(inputs))
    metadata_rows = _metadata_row_geometries(
        surface,
        recovery_meta,
        width_mm=layout.regions.safe.width_mm,
    )
    metadata_height_mm = _metadata_required_height_mm(metadata_rows)
    metadata_top_mm = layout.regions.body.bottom_mm - metadata_height_mm
    first_fallback_top_mm = layout.regions.body.y_mm + 74.0
    first_fallback_bottom_mm = metadata_top_mm - 4.0
    if first_fallback_bottom_mm - first_fallback_top_mm < 2 * _FALLBACK_ROW_HEIGHT_MM:
        raise ValueError(
            "Forge recovery page cannot fit fallback text and required metadata at legible sizes"
        )
    continuation_top_mm = layout.regions.body.y_mm + 22.0
    return _ForgeRecoveryGeometry(
        layout=layout,
        first_page_fallback_area=PdfRect(
            layout.regions.safe.x_mm,
            first_fallback_top_mm,
            layout.regions.safe.width_mm,
            first_fallback_bottom_mm - first_fallback_top_mm,
        ),
        continuation_fallback_area=PdfRect(
            layout.regions.safe.x_mm,
            continuation_top_mm,
            layout.regions.safe.width_mm,
            layout.regions.body.bottom_mm - continuation_top_mm,
        ),
        metadata_top_mm=metadata_top_mm,
        metadata_rows=metadata_rows,
    )


def _metadata_required_height_mm(rows: Sequence[_ForgeMetadataRowGeometry]) -> float:
    return 12.0 + sum(_metadata_row_advance_mm(row) for row in rows)


def _metadata_row_advance_mm(row: _ForgeMetadataRowGeometry) -> float:
    return 5.2 + row.box_height_mm + 3.0


def render_forge_recovery_direct_pdf(inputs: RenderInputs) -> RenderResult:
    """Render a Forge recovery document directly to PDF and return validation proofs."""

    page = resolve_page_geometry(inputs)
    surface = FpdfSurface(page_width_mm=page.width_mm, page_height_mm=page.height_mm)
    packaged_direct_pdf_assets().register_fonts(surface)
    plan = build_forge_recovery_direct_plan(surface, inputs)
    layout_proof = build_direct_layout_proof(plan.page_plans)
    write_direct_layout_debug_json(
        inputs=inputs,
        page_plans=plan.page_plans,
        style_name="forge",
        layout_proof=layout_proof,
    )
    for page_plan in plan.page_plans:
        page_plan.paint(surface)
    surface.output(inputs.output_path)
    return RenderResult(
        fallback_proof=plan.fallback_proof,
        artifact_proof=plan.artifact_proof,
        layout_proof=layout_proof,
    )


def build_forge_recovery_direct_plan(
    surface: PdfSurface,
    inputs: RenderInputs,
) -> ForgeRecoveryDirectPlan:
    """Build measured direct-PDF plans and render proofs for Forge recovery inputs."""

    _validate_inputs(inputs)
    context = build_forge_shell_context(inputs, doc_type=DOC_TYPE_RECOVERY)
    recovery_meta = inputs.recovery_meta or RecoveryMeta()
    layout = build_forge_page_layout(resolve_page_geometry(inputs))
    passphrase_pagination = _paginate_forge_passphrase(surface, recovery_meta, layout=layout)
    geometry = _forge_recovery_geometry(surface, inputs, passphrase_pagination.inline_meta)
    sections, fallback_pages = _responsive_fallback_layout(
        surface,
        inputs.fallback_sections or (),
        geometry=geometry,
        first_page_single_section=context.capabilities.recovery_first_page_single_section,
    )
    total_pages = len(fallback_pages) + len(passphrase_pagination.continuation_pages)
    fallback_page_plans = tuple(
        _build_page(
            surface,
            context,
            geometry=geometry,
            fallback_page=fallback_page,
            total_pages=total_pages,
        )
        for fallback_page in fallback_pages
    )
    passphrase_page_plans = tuple(
        _build_passphrase_continuation_page(
            surface,
            context,
            layout=layout,
            continuation_page=continuation_page,
            page_number=len(fallback_pages) + continuation_page.page_index,
            total_pages=total_pages,
        )
        for continuation_page in passphrase_pagination.continuation_pages
    )
    page_plans = fallback_page_plans + passphrase_page_plans
    fallback_proof = _build_fallback_proof(inputs, sections, fallback_pages)
    artifact_proof = build_render_artifact_proof(
        inputs,
        encoded_payload_count=len(inputs.qr_payloads or inputs.frames),
        physical_qr_count=0,
        physical_qr_payload_indexes=(),
        page_count=len(page_plans),
        fallback_proof=fallback_proof,
    )
    return ForgeRecoveryDirectPlan(
        page_plans=page_plans,
        fallback_proof=fallback_proof,
        artifact_proof=artifact_proof,
    )


def _paginate_forge_passphrase(
    surface: PdfSurface,
    recovery_meta: RecoveryMeta,
    *,
    layout: ForgePageLayout,
) -> RecoveryPassphrasePagination:
    style = _metadata_value_style()
    guidance_style = _metadata_guidance_style()
    continuation_rect = _passphrase_continuation_value_rect(layout)
    return paginate_recovery_passphrase(
        surface,
        recovery_meta,
        style=style,
        guidance_style=guidance_style,
        max_width_mm=layout.regions.safe.width_mm - 6.0,
        inline_height_mm=4.0 * surface.line_height(style, multiplier=1.2),
        continuation_height_mm=continuation_rect.height_mm,
        line_height_multiplier=1.2,
    )


def _passphrase_continuation_value_rect(layout: ForgePageLayout) -> PdfRect:
    panel_y_mm = layout.regions.body.y_mm + 31.0
    panel_bottom_mm = layout.regions.body.bottom_mm - 4.0
    panel_height_mm = panel_bottom_mm - panel_y_mm
    if panel_height_mm <= 8.0:
        raise ValueError("Forge page has zero-capacity passphrase continuation area")
    return PdfRect(
        layout.regions.safe.x_mm + 3.0,
        panel_y_mm + 2.0,
        layout.regions.safe.width_mm - 6.0,
        panel_height_mm - 4.0,
    )


def _validate_inputs(inputs: RenderInputs) -> None:
    normalized_doc_type = inputs.doc_type.strip().lower()
    if normalized_doc_type != DOC_TYPE_RECOVERY:
        raise ValueError("direct Forge recovery renderer only supports recovery documents")
    if inputs.render_qr:
        raise ValueError("direct Forge recovery renderer does not place physical QR codes")
    if not inputs.render_fallback:
        raise ValueError("direct Forge recovery renderer requires fallback rendering")
    if not inputs.frames:
        raise ValueError("frames cannot be empty for direct Forge recovery rendering")
    if not inputs.fallback_sections:
        raise ValueError("fallback_sections are required for direct Forge recovery rendering")
    if inputs.recovery_meta is None:
        raise ValueError("recovery metadata is required for direct Forge recovery rendering")

    resolve_page_geometry(inputs)


def _fallback_sections(
    sections: Sequence[FallbackSection],
    *,
    line_length: int,
) -> tuple[_FallbackSectionLines, ...]:
    resolved: list[_FallbackSectionLines] = []
    for index, section in enumerate(sections):
        encoded = encode_zbase32(encode_frame(section.frame))
        lines = format_zbase32_lines(
            encoded,
            group_size=_FALLBACK_GROUP_SIZE,
            line_length=line_length,
            line_count=MAX_FALLBACK_LINES,
        )
        resolved.append(
            _FallbackSectionLines(
                section_index=index,
                title=fallback_section_title(section.label),
                lines=tuple(lines),
            )
        )
    return tuple(resolved)


def _responsive_fallback_layout(
    surface: PdfSurface,
    sections: Sequence[FallbackSection],
    *,
    geometry: _ForgeRecoveryGeometry,
    first_page_single_section: bool,
) -> tuple[tuple[_FallbackSectionLines, ...], tuple[_FallbackPageLayout, ...]]:
    """Reflow fallback lines until every page's widest number gutter leaves readable text."""

    line_length = _FALLBACK_LINE_LENGTH
    while True:
        resolved_sections = _fallback_sections(sections, line_length=line_length)
        pages = _paginate_fallback_entries(
            _fallback_entries(resolved_sections),
            geometry=geometry,
            first_page_single_section=first_page_single_section,
        )
        measured_line_length = min(_fallback_line_length_for_page(surface, page) for page in pages)
        if measured_line_length >= line_length:
            return resolved_sections, pages
        line_length = measured_line_length


def _fallback_entries(sections: Sequence[_FallbackSectionLines]) -> tuple[_FallbackEntry, ...]:
    entries: list[_FallbackEntry] = []
    for section in sections:
        if section.title:
            entries.append(
                _FallbackTitleEntry(section_index=section.section_index, title=section.title)
            )
        for line_number, line in enumerate(section.lines, start=1):
            entries.append(
                _FallbackLineEntry(
                    section_index=section.section_index,
                    line_number=line_number,
                    text=line,
                )
            )
    return tuple(entries)


def _paginate_fallback_entries(
    entries: Sequence[_FallbackEntry],
    *,
    geometry: _ForgeRecoveryGeometry,
    first_page_single_section: bool,
) -> tuple[_FallbackPageLayout, ...]:
    if not entries:
        raise ValueError("direct Forge recovery renderer has no fallback entries to render")

    remaining = tuple(entries)
    page_number = 1
    pages: list[_FallbackPageLayout] = []
    while remaining:
        area = _fallback_area_for_page(page_number, geometry=geometry)
        rows_per_column = _fallback_rows_per_column(area)
        page_entries, consumed = _consume_page_entries(
            remaining,
            rows_per_column=rows_per_column,
            stop_after_current_section=first_page_single_section and page_number == 1,
        )
        if consumed <= 0:
            raise ValueError("fallback layout cannot fit even one entry on a page")
        pages.append(
            _FallbackPageLayout(
                page_number=page_number,
                area=area,
                rows_per_column=rows_per_column,
                entries=page_entries,
            )
        )
        remaining = remaining[consumed:]
        page_number += 1
    return tuple(pages)


def _fallback_area_for_page(
    page_number: int,
    *,
    geometry: _ForgeRecoveryGeometry,
) -> PdfRect:
    if page_number <= 1:
        return geometry.first_page_fallback_area
    return geometry.continuation_fallback_area


def _fallback_rows_per_column(area: PdfRect) -> int:
    rows = math.floor(area.height_mm / _FALLBACK_ROW_HEIGHT_MM)
    if rows < 2:
        raise ValueError("fallback area must fit at least two rows")
    return rows


def _consume_page_entries(
    entries: Sequence[_FallbackEntry],
    *,
    rows_per_column: int,
    stop_after_current_section: bool,
) -> tuple[tuple[_FallbackPageEntry, ...], int]:
    placed: list[_FallbackPageEntry] = []
    row_index = 0
    column_index = 0
    consumed = 0
    display_line_number = 0
    first_section_index = _entry_section_index(entries[0]) if entries else None

    for index, entry in enumerate(entries):
        if (
            stop_after_current_section
            and first_section_index is not None
            and _entry_section_index(entry) != first_section_index
        ):
            break
        if isinstance(entry, _FallbackTitleEntry):
            display_line_number = 0
            next_entry = entries[index + 1] if index + 1 < len(entries) else None
            title_row = row_index + (1 if column_index else 0)
            required_rows = 2 if isinstance(next_entry, _FallbackLineEntry) else 1
            if title_row + required_rows > rows_per_column:
                break
            placed.append(
                _FallbackPageEntry(
                    entry=entry,
                    row_index=title_row,
                    column_index=None,
                    display_line_number=None,
                )
            )
            row_index = title_row + 1
            column_index = 0
            consumed += 1
            continue

        if row_index >= rows_per_column:
            break
        display_line_number += 1
        placed.append(
            _FallbackPageEntry(
                entry=entry,
                row_index=row_index,
                column_index=column_index,
                display_line_number=display_line_number,
            )
        )
        if column_index == 0:
            column_index = 1
        else:
            row_index += 1
            column_index = 0
        consumed += 1

    return tuple(placed), consumed


def _entry_section_index(entry: _FallbackEntry) -> int:
    return entry.section_index


def _build_fallback_proof(
    inputs: RenderInputs,
    sections: Sequence[_FallbackSectionLines],
    pages: Sequence[_FallbackPageLayout],
) -> RenderFallbackProof:
    emitted_lines = tuple(
        page_entry.entry.text
        for page in pages
        for page_entry in page.entries
        if isinstance(page_entry.entry, _FallbackLineEntry)
    )
    emitted_section_chunks = {
        (page.page_number, page_entry.entry.section_index)
        for page in pages
        for page_entry in page.entries
        if isinstance(page_entry.entry, _FallbackLineEntry)
    }
    return RenderFallbackProof(
        section_frame_digests=tuple(
            frame_digest(section.frame) for section in inputs.fallback_sections or ()
        ),
        section_titles=tuple(section.title for section in sections if section.title),
        expected_section_count=len(sections),
        emitted_block_count=len(emitted_section_chunks),
        emitted_line_count=len(emitted_lines),
        consumed_section_count=len(sections),
        fully_consumed=True,
        emitted_fallback_lines=emitted_lines,
    )


def _build_page(
    surface: PdfSurface,
    context: ForgeShellContext,
    *,
    geometry: _ForgeRecoveryGeometry,
    fallback_page: _FallbackPageLayout,
    total_pages: int,
) -> DirectPdfPagePlan:
    page_number = fallback_page.page_number
    page_label = f"PAGE {page_number} / {total_pages}"
    plans: list[PaintPlan] = []
    plans.extend(
        build_forge_header_plans(
            surface,
            context,
            page_label=page_label,
            page_number=page_number,
            component_base=_COMPONENT_BASE,
            classification_default="Manual Entry Only",
            title_default="Recovery Document",
            subtitle_default="Keys + Text Fallback",
            page_rect=geometry.layout.page.rect,
        )
    )
    if page_number == 1:
        plans.extend(
            _warning_plans(
                surface,
                context,
                layout=geometry.layout,
                page_number=page_number,
            )
        )
        plans.extend(_instruction_plans(surface, context, layout=geometry.layout))
    else:
        plans.extend(
            _continuation_plans(
                surface,
                context,
                layout=geometry.layout,
                page_number=page_number,
            )
        )
    plans.extend(_fallback_plans(surface, fallback_page))
    if page_number == 1:
        plans.extend(
            _metadata_plans(
                surface,
                geometry.metadata_rows,
                layout=geometry.layout,
                top_mm=geometry.metadata_top_mm,
            )
        )
    plans.extend(
        build_forge_footer_plans(
            surface,
            context,
            page_label=page_label,
            page_number=page_number,
            component_base=_COMPONENT_BASE,
            page_rect=geometry.layout.page.rect,
        )
    )
    prefix = component_prefix(_COMPONENT_BASE, page_number)
    fallback_ids = tuple(
        (
            f"{prefix}-fallback-title-{index}"
            if isinstance(page_entry.entry, _FallbackTitleEntry)
            else f"{prefix}-fallback-line-box-{index}"
        )
        for index, page_entry in enumerate(fallback_page.entries)
    )
    content_ids = fallback_ids + (
        (f"{prefix}-warning-panel", f"{prefix}-instructions-body")
        if page_number == 1
        else (f"{prefix}-continuation-panel",)
    )
    metadata_ids = (
        tuple(f"{prefix}-metadata-box-{index}" for index, _ in enumerate(geometry.metadata_rows))
        if page_number == 1
        else ()
    )
    constraints = list(
        build_forge_content_constraints(
            component_base=_COMPONENT_BASE,
            page_number=page_number,
            layout=geometry.layout,
            content_component_ids=content_ids + metadata_ids,
        )
    )
    top_group_ids = (
        (f"{prefix}-instructions-body",) if page_number == 1 else (f"{prefix}-continuation-panel",)
    )
    constraints.append(
        SeparationConstraint(
            constraint_id=f"{prefix}-fallback-after-intro",
            first=ComponentGroup(group_id=f"{prefix}-intro", component_ids=top_group_ids),
            second=ComponentGroup(
                group_id=f"{prefix}-fallback-content",
                component_ids=fallback_ids,
            ),
            minimum_clearance_mm=3.0,
        )
    )
    if page_number == 1 and metadata_ids:
        constraints.append(
            SeparationConstraint(
                constraint_id=f"{prefix}-metadata-after-fallback",
                first=ComponentGroup(
                    group_id=f"{prefix}-fallback-for-metadata",
                    component_ids=fallback_ids,
                ),
                second=ComponentGroup(
                    group_id=f"{prefix}-metadata-content",
                    component_ids=metadata_ids,
                ),
                minimum_clearance_mm=3.0,
            )
        )
    return build_page_plan(
        page_number=page_number,
        rect=geometry.layout.page.rect,
        plans=plans,
        separation_constraints=constraints,
    )


def _build_passphrase_continuation_page(
    surface: PdfSurface,
    context: ForgeShellContext,
    *,
    layout: ForgePageLayout,
    continuation_page: RecoveryPassphraseContinuationPage,
    page_number: int,
    total_pages: int,
) -> DirectPdfPagePlan:
    prefix = component_prefix(_COMPONENT_BASE, page_number)
    page_label = f"PAGE {page_number} / {total_pages}"
    value_rect = _passphrase_continuation_value_rect(layout)
    panel_rect = PdfRect(
        value_rect.x_mm - 3.0,
        value_rect.y_mm - 2.0,
        value_rect.width_mm + 6.0,
        value_rect.height_mm + 4.0,
    )
    plans: list[PaintPlan] = []
    plans.extend(
        build_forge_header_plans(
            surface,
            context,
            page_label=page_label,
            page_number=page_number,
            component_base=_COMPONENT_BASE,
            classification_default="Manual Entry Only",
            classification_override="Passphrase Metadata",
            title_default="Recovery Document",
            subtitle_default="Passphrase Continuation",
            page_rect=layout.page.rect,
        )
    )
    plans.extend(
        [
            TextBox(
                component_id=f"{prefix}-passphrase-continuation-title",
                text=(
                    "PASSPHRASE CONTINUATION "
                    f"{continuation_page.page_index} / {continuation_page.total_pages}"
                ),
                style=FORGE_THEME.sans_style(
                    size_pt=10.5,
                    bold=True,
                    color=FORGE_SLATE_900,
                ),
                policy=TextFitPolicy.FAIL,
            ).plan(
                surface,
                PdfRect(
                    layout.regions.safe.x_mm,
                    layout.regions.body.y_mm + 4.0,
                    layout.regions.safe.width_mm,
                    5.0,
                ),
            ),
            TextBox(
                component_id=f"{prefix}-passphrase-continuation-instructions",
                text=continuation_page.instructions,
                style=FORGE_THEME.sans_style(size_pt=8.0, color=FORGE_SLATE_600),
                policy=TextFitPolicy.WRAP,
            ).plan(
                surface,
                PdfRect(
                    layout.regions.safe.x_mm,
                    layout.regions.body.y_mm + 11.0,
                    layout.regions.safe.width_mm,
                    15.0,
                ),
            ),
            Panel(
                component_id=f"{prefix}-passphrase-continuation-panel",
                stroke=FORGE_SLATE_300,
                fill=FORGE_SLATE_50,
                line_width_mm=0.2,
            ).plan(surface, panel_rect),
            TextBox(
                component_id=f"{prefix}-passphrase-continuation-value",
                text=continuation_page.text,
                style=_metadata_value_style(),
                policy=TextFitPolicy.FAIL,
                line_height_multiplier=1.2,
            ).plan(surface, value_rect),
        ]
    )
    plans.extend(
        build_forge_footer_plans(
            surface,
            context,
            page_label=page_label,
            page_number=page_number,
            component_base=_COMPONENT_BASE,
            page_rect=layout.page.rect,
        )
    )
    constraints = build_forge_content_constraints(
        component_base=_COMPONENT_BASE,
        page_number=page_number,
        layout=layout,
        content_component_ids=(
            f"{prefix}-passphrase-continuation-title",
            f"{prefix}-passphrase-continuation-instructions",
            f"{prefix}-passphrase-continuation-panel",
        ),
    )
    return build_page_plan(
        page_number=page_number,
        rect=layout.page.rect,
        plans=plans,
        separation_constraints=constraints,
    )


def _warning_plans(
    surface: PdfSurface,
    context: ForgeShellContext,
    *,
    layout: ForgePageLayout,
    page_number: int,
) -> list[PaintPlan]:
    prefix = component_prefix(_COMPONENT_BASE, page_number)
    x_mm = layout.regions.safe.x_mm
    width_mm = layout.regions.safe.width_mm
    return [
        Panel(
            component_id=f"{prefix}-warning-panel",
            stroke=FORGE_SLATE_300,
            fill=FORGE_SLATE_100,
            line_width_mm=0.25,
        ).plan(surface, PdfRect(x_mm, 55.0, width_mm, 21.0)),
        TextBox(
            component_id=f"{prefix}-warning-icon",
            text=_ICON_WARNING,
            style=FORGE_THEME.symbol_style(size_pt=13.0, color=FORGE_SLATE_900),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=8.0,
        ).plan(surface, PdfRect(x_mm + 5.0, 60.0, 15.0, 7.0)),
        TextBox(
            component_id=f"{prefix}-warning-title",
            text=str(context.copy.get("warning_title") or "Critical Security Warning").upper(),
            style=FORGE_THEME.sans_style(size_pt=9.0, bold=True, color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(x_mm + 23.0, 58.0, 128.0, 5.2)),
        TextBox(
            component_id=f"{prefix}-warning-body",
            text=str(context.copy.get("warning_body") or ""),
            style=FORGE_THEME.sans_style(size_pt=9.0, color=FORGE_SLATE_800),
            policy=TextFitPolicy.WRAP,
        ).plan(surface, PdfRect(x_mm + 23.0, 64.0, width_mm - 34.0, 9.2)),
    ]


def _instruction_plans(
    surface: PdfSurface,
    context: ForgeShellContext,
    *,
    layout: ForgePageLayout,
) -> list[PaintPlan]:
    body = "\n".join(
        f"{index}. {line}" for index, line in enumerate(context.instruction_lines, start=1)
    )
    return [
        TextBox(
            component_id="forge-recovery-p1-instructions-title",
            text=context.instructions_label.upper(),
            style=FORGE_THEME.sans_style(size_pt=10.5, bold=True, color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(layout.regions.safe.x_mm + 2.0, 85.0, 52.0, 6.0)),
        Rule(
            component_id="forge-recovery-p1-instructions-title-rule",
            color=FORGE_SLATE_900,
        ).plan(surface, PdfRect(layout.regions.safe.x_mm + 2.0, 92.5, 29.0, 0.35)),
        TextBox(
            component_id="forge-recovery-p1-instructions-body",
            text=body,
            style=FORGE_THEME.sans_style(size_pt=10.5, color=FORGE_SLATE_800),
            policy=TextFitPolicy.WRAP,
        ).plan(
            surface,
            PdfRect(
                layout.regions.safe.x_mm + 2.0,
                98.0,
                layout.regions.safe.width_mm - 12.0,
                16.5,
            ),
        ),
    ]


def _continuation_plans(
    surface: PdfSurface,
    context: ForgeShellContext,
    *,
    layout: ForgePageLayout,
    page_number: int,
) -> list[PaintPlan]:
    prefix = component_prefix(_COMPONENT_BASE, page_number)
    return [
        Panel(
            component_id=f"{prefix}-continuation-panel",
            stroke=FORGE_SLATE_200,
            fill=FORGE_SLATE_50,
            line_width_mm=0.18,
        ).plan(
            surface,
            PdfRect(
                layout.regions.safe.x_mm,
                layout.regions.body.y_mm + 4.0,
                layout.regions.safe.width_mm,
                12.0,
            ),
        ),
        TextBox(
            component_id=f"{prefix}-continuation-hint",
            text=str(context.copy.get("continuation_hint") or "Fallback text continued"),
            style=FORGE_THEME.sans_style(size_pt=8.0, color=FORGE_SLATE_600),
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.CENTER,
            min_size_pt=6.0,
        ).plan(
            surface,
            PdfRect(
                layout.regions.safe.x_mm + 4.0,
                layout.regions.body.y_mm + 7.5,
                layout.regions.safe.width_mm - 8.0,
                5.0,
            ),
        ),
    ]


def _fallback_plans(
    surface: PdfSurface,
    fallback_page: _FallbackPageLayout,
) -> list[PaintPlan]:
    prefix = component_prefix(_COMPONENT_BASE, fallback_page.page_number)
    area = fallback_page.area
    line_number_width_mm = _fallback_line_number_width_mm(surface, fallback_page)
    plans: list[PaintPlan] = []
    for index, page_entry in enumerate(fallback_page.entries):
        if isinstance(page_entry.entry, _FallbackTitleEntry):
            plans.extend(_fallback_title_plans(surface, prefix, page_entry, index, area))
        else:
            plans.extend(
                _fallback_line_plans(
                    surface,
                    prefix,
                    page_entry,
                    index,
                    area,
                    line_number_width_mm=line_number_width_mm,
                )
            )
    return plans


def _fallback_line_number_width_mm(
    surface: PdfSurface,
    fallback_page: _FallbackPageLayout,
) -> float:
    maximum_display_number = max(
        (
            entry.display_line_number or 0
            for entry in fallback_page.entries
            if isinstance(entry.entry, _FallbackLineEntry)
        ),
        default=0,
    )
    maximum_label = f"{maximum_display_number:02d}."
    measured_width_mm = surface.measure_text_width(
        maximum_label,
        _fallback_line_number_style(),
    )
    return max(
        _FALLBACK_MINIMUM_LINE_NUMBER_WIDTH_MM,
        measured_width_mm + _FALLBACK_LINE_NUMBER_PADDING_MM,
    )


def _fallback_line_length_for_page(
    surface: PdfSurface,
    fallback_page: _FallbackPageLayout,
) -> int:
    """Return the longest grouped payload line that remains readable on this page."""

    line_number_width_mm = _fallback_line_number_width_mm(surface, fallback_page)
    text_width_mm = _fallback_payload_text_width_mm(
        fallback_page.area,
        line_number_width_mm=line_number_width_mm,
    )
    fit_style = _fallback_payload_style(size_pt=_FALLBACK_PAYLOAD_MIN_FIT_SIZE_PT)
    widest_character = max(
        ZBASE32_ALPHABET,
        key=lambda character: surface.measure_text_width(character, fit_style),
    )
    maximum_group_count = (_FALLBACK_LINE_LENGTH + 1) // (_FALLBACK_GROUP_SIZE + 1)
    for group_count in range(maximum_group_count, 0, -1):
        candidate = " ".join(widest_character * _FALLBACK_GROUP_SIZE for _ in range(group_count))
        if surface.measure_text_width(candidate, fit_style) <= text_width_mm:
            return len(candidate)
    raise ValueError(
        "Forge recovery fallback column cannot fit one encoded group at the readable font floor"
    )


def _fallback_payload_panel_width_mm(
    area: PdfRect,
    *,
    line_number_width_mm: float,
) -> float:
    column_width_mm = (area.width_mm - _FALLBACK_COLUMN_GAP_MM) / 2.0
    payload_width_mm = column_width_mm - line_number_width_mm - _FALLBACK_LINE_GAP_MM - 5.0
    if payload_width_mm <= 3.6:
        raise ValueError(
            "Forge recovery fallback column is too narrow for its line numbers and payload"
        )
    return payload_width_mm


def _fallback_payload_text_width_mm(
    area: PdfRect,
    *,
    line_number_width_mm: float,
) -> float:
    return (
        _fallback_payload_panel_width_mm(
            area,
            line_number_width_mm=line_number_width_mm,
        )
        - 3.6
    )


def _fallback_line_number_style() -> TextStyle:
    return FORGE_THEME.mono_style(size_pt=10.5, color=FORGE_SLATE_500)


def _fallback_payload_style(*, size_pt: float) -> TextStyle:
    return FORGE_THEME.mono_style(size_pt=size_pt, color=FORGE_SLATE_800)


def _fallback_title_plans(
    surface: PdfSurface,
    prefix: str,
    page_entry: _FallbackPageEntry,
    index: int,
    area: PdfRect,
) -> list[PaintPlan]:
    assert isinstance(page_entry.entry, _FallbackTitleEntry)
    row_y = area.y_mm + page_entry.row_index * _FALLBACK_ROW_HEIGHT_MM + 1.1
    return [
        TextBox(
            component_id=f"{prefix}-fallback-title-{index}",
            text=page_entry.entry.title.upper(),
            style=FORGE_THEME.sans_style(size_pt=7.5, bold=True, color=FORGE_SLATE_600),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(area.x_mm + 5.0, row_y, area.width_mm - 10.0, 4.6)),
    ]


def _fallback_line_plans(
    surface: PdfSurface,
    prefix: str,
    page_entry: _FallbackPageEntry,
    index: int,
    area: PdfRect,
    *,
    line_number_width_mm: float,
) -> list[PaintPlan]:
    assert isinstance(page_entry.entry, _FallbackLineEntry)
    if page_entry.display_line_number is None:
        raise ValueError("fallback payload line is missing its display number")
    column_index = page_entry.column_index or 0
    column_width = (area.width_mm - _FALLBACK_COLUMN_GAP_MM) / 2.0
    column_x = area.x_mm + 5.0 + column_index * (column_width + _FALLBACK_COLUMN_GAP_MM)
    row_y = area.y_mm + page_entry.row_index * _FALLBACK_ROW_HEIGHT_MM + 0.7
    payload_x = column_x + line_number_width_mm + _FALLBACK_LINE_GAP_MM
    payload_width = _fallback_payload_panel_width_mm(
        area,
        line_number_width_mm=line_number_width_mm,
    )
    line_number_text = f"{page_entry.display_line_number:02d}."
    return [
        TextBox(
            component_id=f"{prefix}-fallback-line-number-{index}",
            text=line_number_text,
            style=_fallback_line_number_style(),
            policy=TextFitPolicy.FAIL,
            align=TextAlign.RIGHT,
        ).plan(
            surface,
            PdfRect(column_x, row_y + 1.0, line_number_width_mm, 4.8),
        ),
        Panel(
            component_id=f"{prefix}-fallback-line-box-{index}",
            stroke=FORGE_SLATE_200,
            fill=FORGE_SLATE_50,
            line_width_mm=0.15,
        ).plan(surface, PdfRect(payload_x, row_y, payload_width, 5.6)),
        TextBox(
            component_id=f"{prefix}-fallback-line-text-{index}",
            text=page_entry.entry.text,
            style=_fallback_payload_style(size_pt=9.0),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.8,
        ).plan(surface, PdfRect(payload_x + 1.8, row_y + 1.0, payload_width - 3.6, 4.4)),
    ]


def _metadata_plans(
    surface: PdfSurface,
    rows: Sequence[_ForgeMetadataRowGeometry],
    *,
    layout: ForgePageLayout,
    top_mm: float,
) -> list[PaintPlan]:
    prefix = component_prefix(_COMPONENT_BASE, 1)
    x_mm = layout.regions.safe.x_mm
    width_mm = layout.regions.safe.width_mm
    plans: list[PaintPlan] = [
        Rule(
            component_id=f"{prefix}-metadata-rule",
            color=FORGE_SLATE_900,
        ).plan(surface, PdfRect(x_mm, top_mm, width_mm, 0.75)),
        TextBox(
            component_id=f"{prefix}-metadata-title",
            text="EXTENDED METADATA",
            style=FORGE_THEME.sans_style(size_pt=10.5, bold=True, color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(x_mm + 2.0, top_mm + 5.0, 75.0, 6.0)),
    ]
    cursor_y = top_mm + 12.0
    for index, row in enumerate(rows):
        row_plans, cursor_y = _metadata_row_plans(
            surface,
            row,
            index=index,
            x_mm=x_mm,
            width_mm=width_mm,
            y_mm=cursor_y,
        )
        plans.extend(row_plans)
    if cursor_y > layout.regions.body.bottom_mm + 0.01:
        raise ValueError("recovery metadata exceeds the measured Forge page body")
    return plans


def _metadata_rows(meta: RecoveryMeta) -> tuple[tuple[str, tuple[str, ...], str], ...]:
    rows: list[tuple[str, tuple[str, ...], str]] = []
    if meta.quorum_value:
        rows.append((meta.quorum_label, (meta.quorum_value,), ""))
    if meta.passphrase_lines:
        passphrase = recovery_passphrase_display(meta)
        rows.append((passphrase.label, passphrase.value_lines, passphrase.guidance))
    elif meta.passphrase:
        rows.append((meta.passphrase_label, (meta.passphrase,), ""))
    if meta.signing_pub_lines:
        rows.append(("Master Signing Public Key", tuple(meta.signing_pub_lines), ""))
    return tuple(rows)


def _metadata_row_geometries(
    surface: PdfSurface,
    meta: RecoveryMeta,
    *,
    width_mm: float,
) -> tuple[_ForgeMetadataRowGeometry, ...]:
    value_width_mm = width_mm - 6.0
    if value_width_mm <= 0:
        raise ValueError("Forge recovery metadata width must be positive")
    value_style = _metadata_value_style()
    guidance_style = _metadata_guidance_style()
    rows: list[_ForgeMetadataRowGeometry] = []
    for label, lines, guidance in _metadata_rows(meta):
        text = "\n".join(lines)
        fit = fit_text_to_width(
            surface,
            text,
            value_style,
            max_width_mm=value_width_mm,
            policy=TextFitPolicy.WRAP,
        )
        guidance_height_mm = 0.0
        if guidance:
            guidance_height_mm = (
                fit_text_to_width(
                    surface,
                    guidance,
                    guidance_style,
                    max_width_mm=value_width_mm,
                    policy=TextFitPolicy.WRAP,
                    line_height_multiplier=1.15,
                ).height_mm
                + 1.0
            )
        box_height_mm = max(
            7.8,
            _METADATA_VALUE_PADDING_TOP_MM
            + guidance_height_mm
            + fit.height_mm
            + _METADATA_VALUE_PADDING_BOTTOM_MM,
        )
        rows.append(
            _ForgeMetadataRowGeometry(
                label=label,
                guidance=guidance,
                guidance_height_mm=guidance_height_mm,
                text=text,
                box_height_mm=box_height_mm,
            )
        )
    return tuple(rows)


def _metadata_value_style() -> TextStyle:
    return FORGE_THEME.mono_style(size_pt=9.0, color=FORGE_SLATE_800)


def _metadata_guidance_style() -> TextStyle:
    return FORGE_THEME.sans_style(size_pt=6.4, color=FORGE_SLATE_600)


def _metadata_row_plans(
    surface: PdfSurface,
    row: _ForgeMetadataRowGeometry,
    *,
    index: int,
    x_mm: float,
    width_mm: float,
    y_mm: float,
) -> tuple[list[PaintPlan], float]:
    box_height = row.box_height_mm
    box_y = y_mm + 5.2
    prefix = component_prefix(_COMPONENT_BASE, 1)
    plans: list[PaintPlan] = [
        TextBox(
            component_id=f"{prefix}-metadata-label-{index}",
            text=row.label.upper(),
            style=FORGE_THEME.sans_style(size_pt=9.0, bold=True, color=FORGE_SLATE_600),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(x_mm, y_mm, width_mm, 4.8)),
        Panel(
            component_id=f"{prefix}-metadata-box-{index}",
            stroke=FORGE_SLATE_300,
            fill=FORGE_SLATE_50,
            line_width_mm=0.2,
        ).plan(surface, PdfRect(x_mm, box_y, width_mm, box_height)),
    ]
    value_y_mm = box_y + _METADATA_VALUE_PADDING_TOP_MM
    if row.guidance:
        plans.append(
            TextBox(
                component_id=f"{prefix}-metadata-guidance-{index}",
                text=row.guidance,
                style=_metadata_guidance_style(),
                policy=TextFitPolicy.WRAP,
                line_height_multiplier=1.15,
            ).plan(
                surface,
                PdfRect(
                    x_mm + 3.0,
                    value_y_mm,
                    width_mm - 6.0,
                    row.guidance_height_mm - 1.0,
                ),
            )
        )
        value_y_mm += row.guidance_height_mm
    plans.append(
        TextBox(
            component_id=f"{prefix}-metadata-value-{index}",
            text=row.text,
            style=_metadata_value_style(),
            policy=TextFitPolicy.WRAP,
        ).plan(
            surface,
            PdfRect(
                x_mm + 3.0,
                value_y_mm,
                width_mm - 6.0,
                box_y + box_height - value_y_mm,
            ),
        )
    )
    return plans, box_y + box_height + 3.0


__all__ = [
    "ForgeRecoveryDirectPlan",
    "build_forge_recovery_direct_plan",
    "render_forge_recovery_direct_pdf",
]
