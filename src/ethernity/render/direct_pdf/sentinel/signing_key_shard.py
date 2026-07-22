"""Sentinel signing-key shard rendering through direct PDF primitives."""

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
    SENTINEL_BORDER,
    SENTINEL_GRID_LINE,
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
from ethernity.render.doc_types import DOC_TYPE_SIGNING_KEY_SHARD
from ethernity.render.fallback_text import fallback_section_title, format_zbase32_lines
from ethernity.render.proofs import build_render_artifact_proof, frame_digest
from ethernity.render.types import (
    FallbackSection,
    RenderArtifactProof,
    RenderFallbackProof,
    RenderInputs,
    RenderResult,
)

_COMPONENT_BASE = "sentinel-signing-key-shard"
_FALLBACK_GROUP_SIZE = 4
_FALLBACK_TEXT_SIZE_PT = 6.0
_FALLBACK_MAX_COLUMNS = 2
_FALLBACK_ROW_HEIGHT_MM = 2.5
_FALLBACK_ROW_GAP_MM = 0.15
_FALLBACK_RESCUE_ROW_HEIGHT_MM = 2.3
_FALLBACK_RESCUE_ROW_GAP_MM = 0.05
_FALLBACK_COLUMN_GAP_MM = 4.0
_FALLBACK_HORIZONTAL_INSET_MM = 4.5
_FALLBACK_LINE_START_OFFSET_MM = 6.0
_FALLBACK_BOTTOM_Y_MM = 275.0
_FALLBACK_BOTTOM_PADDING_MM = 0.8
_FALLBACK_TEXT_WIDTH_SAFETY_MM = 0.5
_FALLBACK_UPPER_CONTENT_CLEARANCE_MM = 6.0
_QR_FRAME_RECT = PdfRect(11.0, 96.0, 62.5, 62.5)
_QR_IMAGE_RECT = PdfRect(14.2, 99.1, 56.0, 56.0)
_QR_CAPTION_RECT = PdfRect(77.0, 96.0, 122.0, 5.0)
_WARNING_RECT = PdfRect(11.0, 36.5, 188.0, 41.5)
_REFERENCE_RECT = PdfRect(77.0, 103.0, 122.0, 22.0)
_SPECS_RECT = PdfRect(77.0, 128.0, 122.0, 30.5)
_DASH_LENGTH_MM = 2.0
_DASH_GAP_MM = 1.6
_ICON_WARNING = chr(0xE002)
_ICON_GROUP_WORK = chr(0xE886)
_ICON_FINGERPRINT = chr(0xE90D)


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
class SentinelSigningKeyShardDirectPlan:
    """Measured pages and app-wide proofs for one Sentinel signing-key shard render."""

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


def render_sentinel_signing_key_shard_direct_pdf(inputs: RenderInputs) -> RenderResult:
    """Render a Sentinel signing-key shard document directly to PDF."""

    surface = build_sentinel_surface(inputs)
    packaged_direct_pdf_assets().register_fonts(surface)
    plan = build_sentinel_signing_key_shard_direct_plan(surface, inputs)
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


def build_sentinel_signing_key_shard_direct_plan(
    surface: PdfSurface,
    inputs: RenderInputs,
) -> SentinelSigningKeyShardDirectPlan:
    """Build measured direct-PDF plans and render proofs for Sentinel signing-key shard inputs."""

    _validate_inputs(inputs)
    payload = _resolved_qr_payload(inputs)
    qr_image_bytes = qr_image(payload, config=inputs.qr_config or QrConfig())
    context = build_sentinel_shell_context(inputs, doc_type=DOC_TYPE_SIGNING_KEY_SHARD)
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
    return SentinelSigningKeyShardDirectPlan(
        page_plans=page_plans,
        fallback_proof=fallback_proof,
        artifact_proof=artifact_proof,
    )


def _validate_inputs(inputs: RenderInputs) -> None:
    normalized_doc_type = inputs.doc_type.strip().lower()
    if normalized_doc_type != DOC_TYPE_SIGNING_KEY_SHARD:
        raise ValueError(
            "direct Sentinel signing-key shard renderer only supports signing-key shards"
        )
    if not inputs.render_qr:
        raise ValueError("direct Sentinel signing-key shard renderer requires QR rendering")
    if not inputs.render_fallback:
        raise ValueError("direct Sentinel signing-key shard renderer requires fallback rendering")
    validate_single_shard_fallback_contract(
        inputs,
        renderer_label="direct Sentinel signing-key shard renderer",
    )

    resolve_page_geometry(inputs)

    qr_config = inputs.qr_config or QrConfig()
    qr_kind = str(qr_config.kind or "png").strip().lower()
    if qr_kind != "png":
        raise ValueError("direct Sentinel signing-key shard renderer supports PNG QR images only")


def _resolved_qr_payload(inputs: RenderInputs) -> bytes | str:
    if inputs.qr_payloads is not None:
        payloads = tuple(inputs.qr_payloads)
    else:
        payloads = (encode_frame(inputs.frames[0]),)
    if len(payloads) != 1:
        raise ValueError("direct Sentinel signing-key shard renderer requires one QR payload")
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
    qr_bottom_y_mm = page_layout.map_y(_QR_FRAME_RECT.y_mm) + _QR_FRAME_RECT.height_mm
    structured_content_bottom_y_mm = page_layout.map_y(_SPECS_RECT.bottom_mm)
    minimum_top_y_mm = (
        max(qr_bottom_y_mm, structured_content_bottom_y_mm) + _FALLBACK_UPPER_CONTENT_CLEARANCE_MM
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
        "direct Sentinel signing-key shard fallback cannot fit between the upper content "
        f"and footer using up to {_FALLBACK_MAX_COLUMNS} measured columns"
    )


def _fallback_column_width(page_layout: SentinelPageLayout, *, columns: int) -> float:
    if columns <= 0:
        raise ValueError("fallback columns must be positive")
    inner_width_mm = page_layout.safe_rect.width_mm - (2.0 * _FALLBACK_HORIZONTAL_INSET_MM)
    column_width_mm = (inner_width_mm - ((columns - 1) * _FALLBACK_COLUMN_GAP_MM)) / columns
    if column_width_mm <= 0:
        raise ValueError(
            "direct Sentinel signing-key shard fallback has no horizontal text capacity"
        )
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
        raise ValueError("direct Sentinel signing-key shard renderer has no fallback entries")

    panel_rect, grid = _fallback_grid(
        page_layout,
        entry_count=len(entries),
        layout_profile=layout_profile,
    )
    if len(entries) > grid.capacity:
        raise ValueError(
            "direct Sentinel signing-key shard fallback exceeds the single-page layout capacity: "
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
    caption_id = f"{prefix}-qr-caption"
    plans: list[PaintPlan] = []
    plans.extend(
        build_sentinel_header_plans(
            surface,
            context,
            page_label=page_label,
            page_number=fallback_page.page_number,
            component_base=_COMPONENT_BASE,
            top_strip_text="Signing Key Shard // Restricted Access // Store Separately",
            title_default="Signing Authority Shard",
            subtitle_default=_shard_subtitle(context),
        )
    )
    plans.extend(_warning_plans(surface, context, prefix=prefix))
    plans.extend(_payload_heading_plans(surface, context, prefix=prefix))
    plans.extend(_primary_qr_plans(surface, qr_image=qr_image, prefix=prefix))
    fallback_plans = _fallback_plans(
        surface,
        context,
        fallback_page=fallback_page,
        prefix=prefix,
    )
    plans.extend(fallback_plans)
    plans.extend(_reference_plans(surface, context, page_label=page_label, prefix=prefix))
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
                member_component_ids=(frame_id, image_id, *marker_ids, caption_id),
                image_component_id=image_id,
                marker_component_ids=marker_ids,
                minimum_marker_clearance_mm=2.3,
                caption_component_id=caption_id,
            ),
        ),
        physical_component_ids=tuple(plan.component_id for plan in fallback_plans),
    )


def _shard_subtitle(context: SentinelShellContext) -> str:
    shard_index = _positive_int(context.values.get("shard_index"), default=1)
    shard_total = _positive_int(context.values.get("shard_total"), default=1)
    return f"Signing authority shard {shard_index} of {shard_total}"


def _warning_plans(
    surface: PdfSurface,
    context: SentinelShellContext,
    *,
    prefix: str,
) -> list[PaintPlan]:
    threshold = _positive_int(context.values.get("shard_threshold"), default=0)
    shard_total = _positive_int(context.values.get("shard_total"), default=1)
    if threshold <= 0:
        threshold = shard_total
    doc_short = context.doc_id[:10]
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-warning-fill",
            stroke=None,
            fill=PdfColor(255, 251, 242),
            line_width_mm=0.2,
        ).plan(surface, _WARNING_RECT),
        *_dashed_rect_plans(
            surface,
            prefix=prefix,
            name="warning-border",
            rect=_WARNING_RECT,
            color=SENTINEL_BLACK,
            line_width_mm=0.35,
        ),
        Panel(
            component_id=f"{prefix}-warning-icon-bg",
            stroke=None,
            fill=PdfColor(255, 237, 191),
            line_width_mm=0.2,
        ).plan(surface, PdfRect(16.5, 42.1, 12.1, 15.0)),
        TextBox(
            component_id=f"{prefix}-warning-icon",
            text=_ICON_WARNING,
            style=SENTINEL_THEME.symbol_style(size_pt=19.0, color=SENTINEL_BLACK),
            policy=TextFitPolicy.FAIL,
            line_height_multiplier=1.0,
        ).plan(surface, PdfRect(19.0, 45.8, 7.5, 8.5)),
        TextBox(
            component_id=f"{prefix}-warning-title",
            text=str(context.copy.get("warning_title") or "Critical Security Notice").upper(),
            style=SENTINEL_THEME.sans_style(size_pt=15.0, bold=True, color=SENTINEL_BLACK),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=9.0,
            line_height_multiplier=1.0,
        ).plan(surface, PdfRect(33.0, 43.0, 140.0, 7.0)),
        TextBox(
            component_id=f"{prefix}-warning-body",
            text=str(context.copy.get("warning_body") or ""),
            style=SENTINEL_THEME.sans_style(size_pt=9.8, color=SENTINEL_TEXT),
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=1.1,
        ).plan(surface, PdfRect(33.0, 51.7, 158.0, 13.2)),
        TextBox(
            component_id=f"{prefix}-warning-threshold-icon",
            text=_ICON_GROUP_WORK,
            style=SENTINEL_THEME.symbol_style(size_pt=9.0, color=SENTINEL_TEXT),
            policy=TextFitPolicy.FAIL,
            line_height_multiplier=1.0,
        ).plan(surface, PdfRect(33.0, 68.6, 4.0, 4.0)),
        TextBox(
            component_id=f"{prefix}-warning-threshold",
            text=f"THRESHOLD: {threshold}/{shard_total} REQUIRED",
            style=SENTINEL_THEME.sans_style(
                size_pt=8.5,
                bold=True,
                color=SENTINEL_TEXT,
                char_spacing_mm=0.18,
            ),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.5,
        ).plan(surface, PdfRect(38.0, 68.0, 52.0, 4.5)),
        TextBox(
            component_id=f"{prefix}-warning-doc-icon",
            text=_ICON_FINGERPRINT,
            style=SENTINEL_THEME.symbol_style(size_pt=9.0, color=SENTINEL_TEXT),
            policy=TextFitPolicy.FAIL,
            line_height_multiplier=1.0,
        ).plan(surface, PdfRect(90.0, 68.6, 4.0, 4.0)),
        TextBox(
            component_id=f"{prefix}-warning-doc",
            text=f"DOC: {doc_short}",
            style=SENTINEL_THEME.sans_style(
                size_pt=8.5,
                bold=True,
                color=SENTINEL_TEXT,
                char_spacing_mm=0.18,
            ),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.5,
        ).plan(surface, PdfRect(95.0, 68.0, 55.0, 4.5)),
    ]
    return plans


def _payload_heading_plans(
    surface: PdfSurface,
    context: SentinelShellContext,
    *,
    prefix: str,
) -> list[PaintPlan]:
    return [
        *_payload_icon_plans(surface, prefix=prefix),
        TextBox(
            component_id=f"{prefix}-payload-heading",
            text=str(context.copy.get("key_material_label") or "Key Material Payload").upper(),
            style=SENTINEL_THEME.sans_style(size_pt=14.5, bold=True, color=SENTINEL_BLACK),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=9.0,
            line_height_multiplier=1.0,
        ).plan(surface, PdfRect(19.2, 85.7, 90.0, 7.0)),
        Panel(
            component_id=f"{prefix}-payload-encoding-badge",
            stroke=None,
            fill=SENTINEL_BACKGROUND,
            line_width_mm=0.2,
        ).plan(surface, PdfRect(150.0, 85.0, 49.0, 6.5)),
        TextBox(
            component_id=f"{prefix}-payload-encoding",
            text="Encoding: QR + Text",
            style=SENTINEL_THEME.mono_style(size_pt=8.8, color=SENTINEL_TEXT),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.5,
            align=TextAlign.RIGHT,
        ).plan(surface, PdfRect(148.0, 85.5, 51.0, 6.0)),
        Rule(
            component_id=f"{prefix}-payload-rule",
            color=SENTINEL_BLACK,
        ).plan(surface, PdfRect(11.0, 93.0, 188.0, 0.35)),
    ]


def _payload_icon_plans(surface: PdfSurface, *, prefix: str) -> list[PaintPlan]:
    square = 1.25
    gap = 0.45
    x_mm = 11.1
    y_mm = 86.2
    cells = ((0, 0), (1, 0), (0, 1), (2, 0), (0, 2), (2, 2), (1, 2))
    return [
        Panel(
            component_id=f"{prefix}-payload-icon-{index}",
            stroke=None,
            fill=SENTINEL_BLACK,
            line_width_mm=0.2,
        ).plan(
            surface,
            PdfRect(
                x_mm + col * (square + gap),
                y_mm + row * (square + gap),
                square,
                square,
            ),
        )
        for index, (col, row) in enumerate(cells)
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
            stroke=SENTINEL_BLACK,
            fill=SENTINEL_WHITE,
            line_width_mm=0.75,
        ).plan(surface, _QR_FRAME_RECT),
        ImageBox(
            component_id=f"{prefix}-qr-image",
            image=qr_image,
            image_type="PNG",
        ).plan(surface, _QR_IMAGE_RECT),
    ]
    plans.extend(
        build_sentinel_corner_mark_plans(
            surface,
            component_prefix=prefix,
            marker_name="qr",
            rect=_QR_FRAME_RECT,
            color=SENTINEL_BLACK,
            length_mm=3.0,
            width_mm=0.7,
        )
    )
    plans.append(
        TextBox(
            component_id=f"{prefix}-qr-caption",
            text="SCAN IN OFFLINE KIT",
            style=SENTINEL_THEME.sans_style(
                size_pt=8.0,
                bold=True,
                color=SENTINEL_TEXT,
                char_spacing_mm=0.28,
            ),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
            align=TextAlign.CENTER,
        ).plan(surface, _QR_CAPTION_RECT)
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
            component_id=f"{prefix}-payload-panel",
            stroke=SENTINEL_GRID_LINE,
            fill=SENTINEL_BACKGROUND,
            line_width_mm=0.2,
        ).plan(surface, area),
    ]
    for index, page_entry in enumerate(fallback_page.entries):
        if isinstance(page_entry.entry, _FallbackTitleEntry):
            plans.append(
                TextBox(
                    component_id=f"{prefix}-fallback-title-{index}",
                    text=page_entry.entry.title.upper(),
                    style=SENTINEL_THEME.mono_style(
                        size_pt=fallback_page.layout_profile.title_size_pt,
                        bold=True,
                        color=SENTINEL_TEXT,
                        char_spacing_mm=0.22,
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
    if not fallback_page.entries:
        plans.append(
            TextBox(
                component_id=f"{prefix}-fallback-empty",
                text=str(context.copy.get("empty_fallback_text") or "No fallback payload."),
                style=SENTINEL_THEME.mono_style(size_pt=7.0, color=SENTINEL_TEXT),
                policy=TextFitPolicy.WRAP,
            ).plan(
                surface,
                PdfRect(
                    area.x_mm + 4.5,
                    area.y_mm + 7.0,
                    area.width_mm - 9.0,
                    8.0,
                ),
            )
        )
    return plans


def _reference_plans(
    surface: PdfSurface,
    context: SentinelShellContext,
    *,
    page_label: str,
    prefix: str,
) -> list[PaintPlan]:
    reference_rect = _REFERENCE_RECT
    specs_rect = _SPECS_RECT
    return [
        Panel(
            component_id=f"{prefix}-reference-panel",
            stroke=SENTINEL_BORDER,
            fill=PdfColor(250, 248, 244),
            line_width_mm=0.2,
        ).plan(surface, reference_rect),
        TextBox(
            component_id=f"{prefix}-reference-label",
            text=str(context.copy.get("master_fingerprint_label") or "Master Fingerprint").upper(),
            style=SENTINEL_THEME.sans_style(
                size_pt=8.0,
                bold=True,
                color=SENTINEL_TEXT,
                char_spacing_mm=0.24,
            ),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(
            surface,
            PdfRect(
                reference_rect.x_mm + 3.5,
                reference_rect.y_mm + 3.0,
                reference_rect.width_mm - 7.0,
                4.0,
            ),
        ),
        TextBox(
            component_id=f"{prefix}-reference-doc-id",
            text=context.doc_id,
            style=SENTINEL_THEME.mono_style(size_pt=8.0, bold=True, color=SENTINEL_BLACK),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(
            surface,
            PdfRect(
                reference_rect.x_mm + 3.5,
                reference_rect.y_mm + 9.0,
                reference_rect.width_mm - 7.0,
                4.0,
            ),
        ),
        TextBox(
            component_id=f"{prefix}-reference-help",
            text="Use this value to verify shard set integrity.",
            style=SENTINEL_THEME.sans_style(size_pt=7.0, color=SENTINEL_TEXT),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(
            surface,
            PdfRect(
                reference_rect.x_mm + 3.5,
                reference_rect.y_mm + 15.0,
                reference_rect.width_mm - 7.0,
                4.0,
            ),
        ),
        Panel(
            component_id=f"{prefix}-specs-panel",
            stroke=SENTINEL_BORDER,
            fill=PdfColor(250, 248, 244),
            line_width_mm=0.2,
        ).plan(surface, specs_rect),
        *_spec_row_plans(
            surface,
            prefix=prefix,
            row_index=0,
            label="SCHEMA",
            value="Signing Key Shard",
            panel_rect=specs_rect,
            y_mm=specs_rect.y_mm + 3.0,
        ),
        *_spec_row_plans(
            surface,
            prefix=prefix,
            row_index=1,
            label="GENERATED",
            value=context.created_timestamp_utc,
            panel_rect=specs_rect,
            y_mm=specs_rect.y_mm + 11.0,
        ),
        *_spec_row_plans(
            surface,
            prefix=prefix,
            row_index=2,
            label="PAGE",
            value=page_label,
            panel_rect=specs_rect,
            y_mm=specs_rect.y_mm + 19.0,
        ),
    ]


def _spec_row_plans(
    surface: PdfSurface,
    *,
    prefix: str,
    row_index: int,
    label: str,
    value: str,
    panel_rect: PdfRect,
    y_mm: float,
) -> list[PaintPlan]:
    content_x_mm = panel_rect.x_mm + 3.5
    content_width_mm = panel_rect.width_mm - 7.0
    label_width_mm = 36.0
    value_x_mm = content_x_mm + label_width_mm + 6.0
    value_width_mm = content_width_mm - label_width_mm - 6.0
    plans: list[PaintPlan] = [
        TextBox(
            component_id=f"{prefix}-spec-label-{row_index}",
            text=label,
            style=SENTINEL_THEME.sans_style(
                size_pt=9.0,
                bold=True,
                color=SENTINEL_TEXT,
                char_spacing_mm=0.18,
            ),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(content_x_mm, y_mm, label_width_mm, 4.5)),
        TextBox(
            component_id=f"{prefix}-spec-value-{row_index}",
            text=value,
            style=SENTINEL_THEME.mono_style(size_pt=8.5, color=SENTINEL_TEXT),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(value_x_mm, y_mm, value_width_mm, 4.5)),
    ]
    if row_index < 2:
        plans.append(
            Rule(
                component_id=f"{prefix}-spec-rule-{row_index}",
                color=SENTINEL_BORDER,
            ).plan(surface, PdfRect(content_x_mm, y_mm + 5.0, content_width_mm, 0.18))
        )
    return plans


def _dashed_rect_plans(
    surface: PdfSurface,
    *,
    prefix: str,
    name: str,
    rect: PdfRect,
    color: PdfColor,
    line_width_mm: float,
) -> list[PaintPlan]:
    plans: list[PaintPlan] = []
    plans.extend(
        _dashed_line_plans(
            surface,
            prefix=prefix,
            name=f"{name}-top",
            start_x=rect.x_mm,
            start_y=rect.y_mm,
            end_x=rect.right_mm,
            end_y=rect.y_mm,
            color=color,
            line_width_mm=line_width_mm,
        )
    )
    plans.extend(
        _dashed_line_plans(
            surface,
            prefix=prefix,
            name=f"{name}-bottom",
            start_x=rect.x_mm,
            start_y=rect.bottom_mm,
            end_x=rect.right_mm,
            end_y=rect.bottom_mm,
            color=color,
            line_width_mm=line_width_mm,
        )
    )
    plans.extend(
        _dashed_line_plans(
            surface,
            prefix=prefix,
            name=f"{name}-left",
            start_x=rect.x_mm,
            start_y=rect.y_mm,
            end_x=rect.x_mm,
            end_y=rect.bottom_mm,
            color=color,
            line_width_mm=line_width_mm,
        )
    )
    plans.extend(
        _dashed_line_plans(
            surface,
            prefix=prefix,
            name=f"{name}-right",
            start_x=rect.right_mm,
            start_y=rect.y_mm,
            end_x=rect.right_mm,
            end_y=rect.bottom_mm,
            color=color,
            line_width_mm=line_width_mm,
        )
    )
    return plans


def _dashed_line_plans(
    surface: PdfSurface,
    *,
    prefix: str,
    name: str,
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    color: PdfColor,
    line_width_mm: float,
) -> list[PaintPlan]:
    horizontal = start_y == end_y
    length = abs(end_x - start_x) if horizontal else abs(end_y - start_y)
    if length <= 0:
        return []
    plans: list[PaintPlan] = []
    cursor = 0.0
    index = 0
    while cursor < length:
        dash_end = min(cursor + _DASH_LENGTH_MM, length)
        if horizontal:
            x1 = start_x + cursor
            x2 = start_x + dash_end
            y1 = y2 = start_y
        else:
            y1 = start_y + cursor
            y2 = start_y + dash_end
            x1 = x2 = start_x
        plans.append(
            Line(
                component_id=f"{prefix}-{name}-dash-{index}",
                color=color,
                line_width_mm=line_width_mm,
            ).plan(surface, start_x_mm=x1, start_y_mm=y1, end_x_mm=x2, end_y_mm=y2)
        )
        cursor += _DASH_LENGTH_MM + _DASH_GAP_MM
        index += 1
    return plans


def _positive_int(value: object, *, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(0, value)


__all__ = [
    "SentinelSigningKeyShardDirectPlan",
    "build_sentinel_signing_key_shard_direct_plan",
    "render_sentinel_signing_key_shard_direct_pdf",
]
