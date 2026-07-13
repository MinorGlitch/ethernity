"""Sentinel shard-document rendering through direct PDF primitives."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from ethernity.core.bounds import MAX_FALLBACK_LINES
from ethernity.encoding.framing import encode_frame
from ethernity.encoding.zbase32 import ZBASE32_ALPHABET, encode_zbase32
from ethernity.qr.codec import QrConfig
from ethernity.render.direct_pdf.assets import packaged_direct_pdf_assets
from ethernity.render.direct_pdf.components import ImageBox, Line, Panel, Rule, TextAlign, TextBox
from ethernity.render.direct_pdf.debug import write_direct_layout_debug_json
from ethernity.render.direct_pdf.layout_proof import build_direct_layout_proof
from ethernity.render.direct_pdf.page import DirectPdfPagePlan, PaintPlan
from ethernity.render.direct_pdf.page_geometry import resolve_page_geometry
from ethernity.render.direct_pdf.responsive_layout import GridPolicy, ResolvedGrid, resolve_grid
from ethernity.render.direct_pdf.sentinel.common import (
    SENTINEL_BACKGROUND,
    SENTINEL_BLACK,
    SENTINEL_GRID_LINE,
    SENTINEL_ORANGE,
    SENTINEL_TEXT,
    SENTINEL_WHITE,
    SentinelPageLayout,
    SentinelQrCompound,
    SentinelShellContext,
    build_sentinel_corner_mark_plans,
    build_sentinel_footer_plans,
    build_sentinel_header_plans,
    build_sentinel_page_plan,
    build_sentinel_shell_context,
    build_sentinel_surface,
    sentinel_corner_mark_component_ids,
)
from ethernity.render.direct_pdf.sentinel.theme import SENTINEL_THEME
from ethernity.render.direct_pdf.shard_contract import validate_single_shard_fallback_contract
from ethernity.render.direct_pdf.structured_common import component_prefix, qr_image
from ethernity.render.direct_pdf.surface import PdfSurface
from ethernity.render.direct_pdf.text_fit import TextFitPolicy
from ethernity.render.direct_pdf.text_measure import measured_grouped_line_length
from ethernity.render.direct_pdf.types import PdfColor, PdfRect
from ethernity.render.doc_types import DOC_TYPE_SHARD
from ethernity.render.fallback_text import fallback_section_title, format_zbase32_lines
from ethernity.render.proofs import build_render_artifact_proof, frame_digest
from ethernity.render.types import (
    FallbackSection,
    RenderArtifactProof,
    RenderFallbackProof,
    RenderInputs,
    RenderResult,
)

_COMPONENT_BASE = "sentinel-shard"
_FALLBACK_GROUP_SIZE = 4
_FALLBACK_TEXT_SIZE_PT = 6.0
_FALLBACK_MAX_COLUMNS = 2
_FALLBACK_ROW_HEIGHT_MM = 2.5
_FALLBACK_ROW_GAP_MM = 0.15
_FALLBACK_RESCUE_ROW_HEIGHT_MM = 2.3
_FALLBACK_RESCUE_ROW_GAP_MM = 0.05
_FALLBACK_COLUMN_GAP_MM = 4.0
_FALLBACK_HORIZONTAL_INSET_MM = 4.5
_FALLBACK_LINE_START_OFFSET_MM = 13.0
_FALLBACK_BOTTOM_Y_MM = 275.0
_FALLBACK_BOTTOM_PADDING_MM = 0.8
_FALLBACK_TEXT_WIDTH_SAFETY_MM = 0.5
_FALLBACK_UPPER_CONTENT_CLEARANCE_MM = 6.0
_QR_FRAME_RECT = PdfRect(68.6, 80.0, 72.7, 72.7)
_QR_IMAGE_RECT = PdfRect(71.1, 82.5, 67.7, 67.7)
_FALLBACK_HATCH_INSET_MM = 0.6
_FALLBACK_HATCH_STEP_MM = 2.75
_FALLBACK_HATCH_COLOR = PdfColor(245, 246, 248)
_ICON_WARNING = chr(0xE002)
_ICON_KEYBOARD = chr(0xE312)


@dataclass(frozen=True)
class _FallbackLayoutProfile:
    columns: int
    text_size_pt: float
    title_size_pt: float
    row_height_mm: float
    row_gap_mm: float


_FALLBACK_LAYOUT_PROFILES = (
    _FallbackLayoutProfile(
        columns=1,
        text_size_pt=_FALLBACK_TEXT_SIZE_PT,
        title_size_pt=7.0,
        row_height_mm=_FALLBACK_ROW_HEIGHT_MM,
        row_gap_mm=_FALLBACK_ROW_GAP_MM,
    ),
    _FallbackLayoutProfile(
        columns=2,
        text_size_pt=_FALLBACK_TEXT_SIZE_PT,
        title_size_pt=_FALLBACK_TEXT_SIZE_PT,
        row_height_mm=_FALLBACK_RESCUE_ROW_HEIGHT_MM,
        row_gap_mm=_FALLBACK_RESCUE_ROW_GAP_MM,
    ),
)


@dataclass(frozen=True)
class SentinelShardDirectPlan:
    """Measured pages and app-wide proofs for one direct Sentinel shard render."""

    page_plans: tuple[DirectPdfPagePlan, ...]
    fallback_proof: RenderFallbackProof
    artifact_proof: RenderArtifactProof


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
    rect: PdfRect


@dataclass(frozen=True)
class _FallbackPage:
    page_number: int
    panel_rect: PdfRect
    layout_profile: _FallbackLayoutProfile
    entries: tuple[_FallbackPageEntry, ...]


def render_sentinel_shard_direct_pdf(inputs: RenderInputs) -> RenderResult:
    """Render a Sentinel shard document directly to PDF and return validation proofs."""

    surface = build_sentinel_surface(inputs)
    packaged_direct_pdf_assets().register_fonts(surface)
    plan = build_sentinel_shard_direct_plan(surface, inputs)
    layout_proof = build_direct_layout_proof(plan.page_plans)
    write_direct_layout_debug_json(
        inputs=inputs,
        page_plans=plan.page_plans,
        style_name="sentinel",
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


def build_sentinel_shard_direct_plan(
    surface: PdfSurface,
    inputs: RenderInputs,
) -> SentinelShardDirectPlan:
    """Build measured direct-PDF plans and render proofs for Sentinel shard inputs."""

    _validate_inputs(inputs)
    payload = _resolved_qr_payload(inputs)
    qr_image_bytes = qr_image(payload, config=inputs.qr_config or QrConfig())
    context = build_sentinel_shell_context(inputs, doc_type=DOC_TYPE_SHARD)
    sections, fallback_pages = _resolve_fallback_layout(
        surface,
        inputs.fallback_sections or (),
        page_layout=context.page_layout,
    )
    page_plans = tuple(
        _build_page(
            surface,
            context,
            fallback_page,
            qr_image=qr_image_bytes,
            total_pages=len(fallback_pages),
        )
        for fallback_page in fallback_pages
    )
    fallback_proof = _build_fallback_proof(inputs, sections, fallback_pages)
    artifact_proof = build_render_artifact_proof(
        inputs,
        qr_payloads=(payload,),
        encoded_payload_count=1,
        physical_qr_count=len(page_plans),
        physical_qr_payload_indexes=tuple(0 for _ in page_plans),
        page_count=len(page_plans),
        fallback_proof=fallback_proof,
    )
    return SentinelShardDirectPlan(
        page_plans=page_plans,
        fallback_proof=fallback_proof,
        artifact_proof=artifact_proof,
    )


def _validate_inputs(inputs: RenderInputs) -> None:
    normalized_doc_type = inputs.doc_type.strip().lower()
    if normalized_doc_type != DOC_TYPE_SHARD:
        raise ValueError("direct Sentinel shard renderer only supports shard documents")
    if not inputs.render_qr:
        raise ValueError("direct Sentinel shard renderer requires QR rendering")
    if not inputs.render_fallback:
        raise ValueError("direct Sentinel shard renderer requires fallback rendering")
    validate_single_shard_fallback_contract(
        inputs,
        renderer_label="direct Sentinel shard renderer",
    )

    resolve_page_geometry(inputs)

    qr_config = inputs.qr_config or QrConfig()
    qr_kind = str(qr_config.kind or "png").strip().lower()
    if qr_kind != "png":
        raise ValueError("direct Sentinel shard renderer currently supports PNG QR images only")


def _resolved_qr_payload(inputs: RenderInputs) -> bytes | str:
    if inputs.qr_payloads is not None:
        payloads = tuple(inputs.qr_payloads)
    else:
        payloads = (encode_frame(inputs.frames[0]),)
    if len(payloads) != 1:
        raise ValueError("direct Sentinel shard renderer requires exactly one QR payload")
    return payloads[0]


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


def _resolve_fallback_layout(
    surface: PdfSurface,
    sections: Sequence[FallbackSection],
    *,
    page_layout: SentinelPageLayout,
) -> tuple[tuple[_FallbackSectionLines, ...], tuple[_FallbackPage, ...]]:
    minimum_top_y_mm = (
        page_layout.map_y(_QR_FRAME_RECT.y_mm)
        + _QR_FRAME_RECT.height_mm
        + _FALLBACK_UPPER_CONTENT_CLEARANCE_MM
    )
    return _select_fallback_layout(
        surface,
        sections,
        page_layout=page_layout,
        minimum_top_y_mm=minimum_top_y_mm,
    )


def _select_fallback_layout(
    surface: PdfSurface,
    sections: Sequence[FallbackSection],
    *,
    page_layout: SentinelPageLayout,
    minimum_top_y_mm: float,
) -> tuple[tuple[_FallbackSectionLines, ...], tuple[_FallbackPage, ...]]:
    for layout_profile in _FALLBACK_LAYOUT_PROFILES:
        resolved_sections, pages = _build_fallback_candidate(
            surface,
            sections,
            page_layout=page_layout,
            layout_profile=layout_profile,
        )
        if pages[0].panel_rect.y_mm >= minimum_top_y_mm:
            return resolved_sections, pages
    raise ValueError(
        "direct Sentinel shard fallback cannot fit between the primary QR and footer "
        f"using up to {_FALLBACK_MAX_COLUMNS} measured columns"
    )


def _fallback_column_width(page_layout: SentinelPageLayout, *, columns: int) -> float:
    if columns <= 0:
        raise ValueError("fallback columns must be positive")
    inner_width_mm = page_layout.safe_rect.width_mm - (2.0 * _FALLBACK_HORIZONTAL_INSET_MM)
    column_width_mm = (inner_width_mm - ((columns - 1) * _FALLBACK_COLUMN_GAP_MM)) / columns
    if column_width_mm <= 0:
        raise ValueError("direct Sentinel shard fallback has no horizontal text capacity")
    return column_width_mm


def _build_fallback_candidate(
    surface: PdfSurface,
    sections: Sequence[FallbackSection],
    *,
    page_layout: SentinelPageLayout,
    layout_profile: _FallbackLayoutProfile,
) -> tuple[tuple[_FallbackSectionLines, ...], tuple[_FallbackPage, ...]]:
    column_width_mm = _fallback_column_width(
        page_layout,
        columns=layout_profile.columns,
    )
    style = SENTINEL_THEME.mono_style(
        size_pt=layout_profile.text_size_pt,
        color=SENTINEL_BLACK,
    )
    line_length = measured_grouped_line_length(
        surface,
        style=style,
        alphabet=ZBASE32_ALPHABET,
        group_size=_FALLBACK_GROUP_SIZE,
        max_width_mm=column_width_mm,
        safety_mm=_FALLBACK_TEXT_WIDTH_SAFETY_MM,
    )
    resolved_sections = _fallback_sections(sections, line_length=line_length)
    pages = _paginate_fallback_entries(
        _fallback_entries(resolved_sections),
        page_layout=page_layout,
        layout_profile=layout_profile,
    )
    return resolved_sections, pages


def _paginate_fallback_entries(
    entries: Sequence[_FallbackEntry],
    *,
    page_layout: SentinelPageLayout,
    layout_profile: _FallbackLayoutProfile,
) -> tuple[_FallbackPage, ...]:
    if not entries:
        raise ValueError("direct Sentinel shard renderer has no fallback entries to render")

    panel_rect, grid = _fallback_grid(
        page_layout,
        entry_count=len(entries),
        layout_profile=layout_profile,
    )
    if len(entries) > grid.capacity:
        raise ValueError(
            "direct Sentinel shard fallback exceeds the single-page layout capacity: "
            f"entries={len(entries)}, capacity={grid.capacity}"
        )
    return (
        _FallbackPage(
            page_number=1,
            panel_rect=panel_rect,
            layout_profile=layout_profile,
            entries=tuple(
                _FallbackPageEntry(entry=entry, rect=rect)
                for entry, rect in zip(
                    entries,
                    _column_major_item_rects(grid, len(entries)),
                    strict=True,
                )
            ),
        ),
    )


def _fallback_grid(
    page_layout: SentinelPageLayout,
    *,
    entry_count: int,
    layout_profile: _FallbackLayoutProfile,
) -> tuple[PdfRect, ResolvedGrid]:
    columns = layout_profile.columns
    if columns <= 0 or columns > _FALLBACK_MAX_COLUMNS:
        raise ValueError(f"fallback columns must be between 1 and {_FALLBACK_MAX_COLUMNS}")
    rows = math.ceil(entry_count / columns)
    rows_height_mm = rows * layout_profile.row_height_mm + (rows - 1) * layout_profile.row_gap_mm
    panel_bottom_mm = page_layout.map_y(_FALLBACK_BOTTOM_Y_MM)
    panel_height_mm = _FALLBACK_LINE_START_OFFSET_MM + rows_height_mm + _FALLBACK_BOTTOM_PADDING_MM
    area = PdfRect(
        page_layout.safe_rect.x_mm,
        panel_bottom_mm - panel_height_mm,
        page_layout.safe_rect.width_mm,
        panel_height_mm,
    )
    row_area = PdfRect(
        area.x_mm + _FALLBACK_HORIZONTAL_INSET_MM,
        area.y_mm + _FALLBACK_LINE_START_OFFSET_MM,
        area.width_mm - (2.0 * _FALLBACK_HORIZONTAL_INSET_MM),
        rows_height_mm,
    )
    item_width_mm = _fallback_column_width(page_layout, columns=columns)
    grid = resolve_grid(
        row_area,
        GridPolicy(
            max_columns=columns,
            max_rows=rows,
            preferred_item_width_mm=item_width_mm,
            preferred_item_height_mm=layout_profile.row_height_mm,
            minimum_item_width_mm=item_width_mm,
            minimum_item_height_mm=layout_profile.row_height_mm,
            minimum_column_gap_mm=(_FALLBACK_COLUMN_GAP_MM if columns > 1 else 0.0),
            minimum_row_gap_mm=layout_profile.row_gap_mm,
        ),
    )
    return area, grid


def _column_major_item_rects(grid: ResolvedGrid, item_count: int) -> tuple[PdfRect, ...]:
    return tuple(
        PdfRect(
            grid.container.x_mm + (index // grid.rows) * (grid.item_width_mm + grid.column_gap_mm),
            grid.container.y_mm + (index % grid.rows) * (grid.item_height_mm + grid.row_gap_mm),
            grid.item_width_mm,
            grid.item_height_mm,
        )
        for index in range(item_count)
    )


def _build_fallback_proof(
    inputs: RenderInputs,
    sections: Sequence[_FallbackSectionLines],
    pages: Sequence[_FallbackPage],
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
    context: SentinelShellContext,
    fallback_page: _FallbackPage,
    *,
    qr_image: bytes,
    total_pages: int,
) -> DirectPdfPagePlan:
    page_label = f"Page {fallback_page.page_number} / {total_pages}"
    prefix = component_prefix(_COMPONENT_BASE, fallback_page.page_number)
    marker_ids = sentinel_corner_mark_component_ids(prefix, "qr")
    frame_id = f"{prefix}-qr-frame"
    image_id = f"{prefix}-qr-image"
    plans: list[PaintPlan] = []
    plans.extend(
        build_sentinel_header_plans(
            surface,
            context,
            page_label=page_label,
            page_number=fallback_page.page_number,
            component_base=_COMPONENT_BASE,
            top_strip_text="Passphrase Shard // Store Separately // Threshold Protected",
            title_default="Shard Document",
            subtitle_default=_shard_subtitle(context),
        )
    )
    plans.extend(_warning_plans(surface, context, prefix=prefix))
    plans.extend(_shard_label_plans(surface, context, prefix=prefix))
    plans.extend(_primary_qr_plans(surface, qr_image=qr_image, prefix=prefix))
    fallback_plans = _fallback_plans(
        surface,
        context,
        fallback_page=fallback_page,
        prefix=prefix,
    )
    plans.extend(fallback_plans)
    plans.extend(
        build_sentinel_footer_plans(
            surface,
            context,
            page_label=page_label,
            page_number=fallback_page.page_number,
            component_base=_COMPONENT_BASE,
        )
    )
    return build_sentinel_page_plan(
        page_number=fallback_page.page_number,
        page_layout=context.page_layout,
        plans=plans,
        qr_compounds=(
            SentinelQrCompound(
                anchor_component_id=frame_id,
                member_component_ids=(frame_id, image_id, *marker_ids),
                image_component_id=image_id,
                marker_component_ids=marker_ids,
                minimum_marker_clearance_mm=4.5,
            ),
        ),
        physical_component_ids=tuple(plan.component_id for plan in fallback_plans),
    )


def _shard_subtitle(context: SentinelShellContext) -> str:
    shard_index = _positive_int(context.values.get("shard_index"), default=1)
    shard_total = _positive_int(context.values.get("shard_total"), default=1)
    return f"Shard {shard_index} of {shard_total}"


def _warning_plans(
    surface: PdfSurface,
    context: SentinelShellContext,
    *,
    prefix: str,
) -> list[PaintPlan]:
    return [
        Panel(
            component_id=f"{prefix}-warning-panel",
            stroke=None,
            fill=SENTINEL_BACKGROUND,
            line_width_mm=0.18,
        ).plan(surface, PdfRect(15.0, 32.0, 180.0, 25.2)),
        Rule(
            component_id=f"{prefix}-warning-accent",
            color=SENTINEL_ORANGE,
        ).plan(surface, PdfRect(15.0, 32.0, 0.85, 25.2)),
        TextBox(
            component_id=f"{prefix}-warning-icon",
            text=_ICON_WARNING,
            style=SENTINEL_THEME.symbol_style(size_pt=18.0, color=SENTINEL_ORANGE),
            policy=TextFitPolicy.FAIL,
            line_height_multiplier=1.0,
        ).plan(surface, PdfRect(20.0, 39.5, 8.0, 8.0)),
        TextBox(
            component_id=f"{prefix}-warning-title",
            text=str(context.copy.get("warning_title") or "Critical Security Notice").upper(),
            style=SENTINEL_THEME.sans_style(
                size_pt=10.5,
                bold=True,
                color=SENTINEL_TEXT,
                char_spacing_mm=0.32,
            ),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=8.0,
            line_height_multiplier=1.0,
        ).plan(surface, PdfRect(30.0, 37.0, 118.0, 4.5)),
        TextBox(
            component_id=f"{prefix}-warning-body",
            text=str(context.copy.get("warning_body") or ""),
            style=SENTINEL_THEME.sans_style(size_pt=9.4, color=SENTINEL_TEXT),
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=1.12,
        ).plan(surface, PdfRect(30.0, 43.9, 162.0, 12.0)),
    ]


def _shard_label_plans(
    surface: PdfSurface,
    context: SentinelShellContext,
    *,
    prefix: str,
) -> list[PaintPlan]:
    shard_index = _positive_int(context.values.get("shard_index"), default=1)
    return [
        TextBox(
            component_id=f"{prefix}-shard-label",
            text=f"SHARD {shard_index:02d}",
            style=SENTINEL_THEME.sans_style(size_pt=27.0, bold=True, color=SENTINEL_BLACK),
            policy=TextFitPolicy.FAIL,
            align=TextAlign.CENTER,
            line_height_multiplier=1.0,
        ).plan(surface, PdfRect(52.0, 61.5, 106.0, 10.0)),
    ]


def _primary_qr_plans(
    surface: PdfSurface,
    *,
    qr_image: bytes,
    prefix: str,
) -> list[PaintPlan]:
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-qr-frame",
            stroke=SENTINEL_GRID_LINE,
            fill=SENTINEL_WHITE,
            line_width_mm=0.2,
        ).plan(surface, _QR_FRAME_RECT),
        ImageBox(
            component_id=f"{prefix}-qr-image",
            image=qr_image,
            image_type="PNG",
        ).plan(surface, _QR_IMAGE_RECT),
    ]
    corner_rect = PdfRect(
        _QR_FRAME_RECT.x_mm - 3.0,
        _QR_FRAME_RECT.y_mm - 3.0,
        _QR_FRAME_RECT.width_mm + 6.0,
        _QR_FRAME_RECT.height_mm + 6.0,
    )
    plans.extend(
        build_sentinel_corner_mark_plans(
            surface,
            component_prefix=prefix,
            marker_name="qr",
            rect=corner_rect,
            color=SENTINEL_ORANGE,
            length_mm=6.0,
            width_mm=0.45,
        )
    )
    return plans


def _fallback_plans(
    surface: PdfSurface,
    context: SentinelShellContext,
    *,
    fallback_page: _FallbackPage,
    prefix: str,
) -> list[PaintPlan]:
    area = fallback_page.panel_rect
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-fallback-panel",
            fill=SENTINEL_WHITE,
            line_width_mm=0.2,
        ).plan(surface, area),
        *_fallback_hatch_plans(surface, prefix=prefix, rect=area),
        Panel(
            component_id=f"{prefix}-fallback-border",
            stroke=SENTINEL_GRID_LINE,
            fill=None,
            line_width_mm=0.2,
        ).plan(surface, area),
        TextBox(
            component_id=f"{prefix}-fallback-icon",
            text=_ICON_KEYBOARD,
            style=SENTINEL_THEME.symbol_style(size_pt=9.0, color=SENTINEL_BLACK),
            policy=TextFitPolicy.FAIL,
            line_height_multiplier=1.0,
        ).plan(surface, PdfRect(area.x_mm + 4.5, area.y_mm + 5.6, 5.0, 5.0)),
        TextBox(
            component_id=f"{prefix}-fallback-label",
            text=str(
                context.copy.get("manual_transcription_label") or "Manual Transcription"
            ).upper(),
            style=SENTINEL_THEME.sans_style(
                size_pt=9.0,
                bold=True,
                color=SENTINEL_TEXT,
                char_spacing_mm=0.30,
            ),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=7.2,
        ).plan(surface, PdfRect(area.x_mm + 10.0, area.y_mm + 5.0, 70.0, 5.0)),
    ]
    for index, page_entry in enumerate(fallback_page.entries):
        if isinstance(page_entry.entry, _FallbackTitleEntry):
            plans.append(
                TextBox(
                    component_id=f"{prefix}-fallback-title-{index}",
                    text=page_entry.entry.title.upper(),
                    style=SENTINEL_THEME.sans_style(
                        size_pt=fallback_page.layout_profile.title_size_pt,
                        bold=True,
                        color=SENTINEL_TEXT,
                        char_spacing_mm=0.18,
                    ),
                    policy=TextFitPolicy.SHRINK,
                    min_size_pt=6.0,
                    line_height_multiplier=1.0,
                ).plan(surface, page_entry.rect)
            )
            continue
        plans.append(
            TextBox(
                component_id=f"{prefix}-fallback-line-{index}",
                text=page_entry.entry.text,
                style=SENTINEL_THEME.mono_style(
                    size_pt=fallback_page.layout_profile.text_size_pt,
                    color=SENTINEL_BLACK,
                ),
                policy=TextFitPolicy.FAIL,
                min_size_pt=fallback_page.layout_profile.text_size_pt,
                line_height_multiplier=1.0,
            ).plan(surface, page_entry.rect)
        )
    return plans


def _fallback_hatch_plans(
    surface: PdfSurface,
    *,
    prefix: str,
    rect: PdfRect,
) -> list[PaintPlan]:
    hatch_rect = PdfRect(
        rect.x_mm + _FALLBACK_HATCH_INSET_MM,
        rect.y_mm + _FALLBACK_HATCH_INSET_MM,
        rect.width_mm - (_FALLBACK_HATCH_INSET_MM * 2.0),
        rect.height_mm - (_FALLBACK_HATCH_INSET_MM * 2.0),
    )
    plans: list[PaintPlan] = []
    offset = hatch_rect.x_mm - hatch_rect.height_mm
    index = 0
    while offset <= hatch_rect.right_mm:
        segment = _clipped_diagonal_segment(hatch_rect, offset)
        if segment is not None:
            start_x, start_y, end_x, end_y = segment
            plans.append(
                Line(
                    component_id=f"{prefix}-fallback-hatch-{index}",
                    color=_FALLBACK_HATCH_COLOR,
                    line_width_mm=0.12,
                ).plan(
                    surface,
                    start_x_mm=start_x,
                    start_y_mm=start_y,
                    end_x_mm=end_x,
                    end_y_mm=end_y,
                )
            )
            index += 1
        offset += _FALLBACK_HATCH_STEP_MM
    return plans


def _clipped_diagonal_segment(
    rect: PdfRect,
    top_x_mm: float,
) -> tuple[float, float, float, float] | None:
    start_x = top_x_mm
    start_y = rect.y_mm
    end_x = top_x_mm + rect.height_mm
    end_y = rect.bottom_mm
    if start_x < rect.x_mm:
        delta = rect.x_mm - start_x
        start_x = rect.x_mm
        start_y += delta
    if end_x > rect.right_mm:
        delta = end_x - rect.right_mm
        end_x = rect.right_mm
        end_y -= delta
    if start_y > rect.bottom_mm or end_y < rect.y_mm:
        return None
    if start_x == end_x and start_y == end_y:
        return None
    return (start_x, start_y, end_x, end_y)


def _positive_int(value: object, *, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(0, value)


__all__ = [
    "SentinelShardDirectPlan",
    "build_sentinel_shard_direct_plan",
    "render_sentinel_shard_direct_pdf",
]
