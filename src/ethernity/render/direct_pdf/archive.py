"""Archive design rendering through direct PDF primitives."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace

from ethernity.encoding.zbase32 import ZBASE32_ALPHABET
from ethernity.qr.codec import QrConfig
from ethernity.render.direct_pdf.assets import MATERIAL_SYMBOLS_FAMILY
from ethernity.render.direct_pdf.components import (
    Ellipse,
    ImageBox,
    Line,
    Panel,
    Rule,
    TextAlign,
    TextBox,
)
from ethernity.render.direct_pdf.fallback_layout import (
    FallbackPage as _FallbackPage,
    FallbackSectionLines as _FallbackSectionLines,
    FallbackTitleEntry as _FallbackTitleEntry,
    ResponsiveFallbackPageProfile,
    ResponsiveFallbackSpec,
    build_fallback_proof as _build_fallback_proof,
    fallback_entries as _fallback_entries,
    fallback_sections as _fallback_sections,
    paginate_fallback_entries as _paginate_fallback_entries,
    resolve_responsive_fallback_pagination,
)
from ethernity.render.direct_pdf.page import (
    ComponentGroup,
    DirectPdfPagePlan,
    LayoutRegion,
    PaintPlan,
    SeparationConstraint,
    build_page_plan,
)
from ethernity.render.direct_pdf.page_geometry import PageGeometry, resolve_page_geometry
from ethernity.render.direct_pdf.recovery_metadata import (
    RecoveryPassphraseContinuationPage,
    RecoveryPassphrasePagination,
    paginate_recovery_passphrase,
)
from ethernity.render.direct_pdf.responsive_layout import (
    GridPolicy,
    ResolvedGrid,
    resolve_grid,
)
from ethernity.render.direct_pdf.structured_common import (
    QrPage as _QrPage,
    QrPayloadItem as _QrPayloadItem,
    StructuredContext as _ArchiveContext,
    StructuredDirectPlan as ArchiveDirectPlan,
    StructuredPlanBuilder,
    build_artifact_proof as build_render_artifact_proof,
    build_structured_context as _build_archive_context,
    component_prefix as _component_prefix,
    paginate_qr_items as _paginate_qr_items,
    positive_int as _positive_int,
    qr_image as _qr_image,
    qr_payload_items as _qr_payload_items,
    render_structured_plan,
    resolved_qr_payloads as _resolved_qr_payloads,
    resolved_single_qr_payload as _resolved_single_qr_payload,
    validate_qr_inputs as _validate_qr_inputs,
    validate_recovery_inputs as _validate_recovery_inputs,
    validate_single_qr_fallback_inputs as _validate_single_qr_fallback_inputs,
)
from ethernity.render.direct_pdf.surface import PdfSurface
from ethernity.render.direct_pdf.text_fit import TextFitPolicy, fit_text_to_width
from ethernity.render.direct_pdf.text_measure import measured_grouped_line_length
from ethernity.render.direct_pdf.types import PdfColor, PdfRect, TextStyle
from ethernity.render.doc_types import (
    DOC_TYPE_KIT,
    DOC_TYPE_MAIN,
    DOC_TYPE_RECOVERY,
    DOC_TYPE_SHARD,
    DOC_TYPE_SIGNING_KEY_SHARD,
)
from ethernity.render.recovery_meta import (
    RecoveryMeta,
    recovery_passphrase_display,
)
from ethernity.render.template_style import load_template_style
from ethernity.render.types import RenderInputs, RenderResult

_MARGIN_MM = 14.0
_CONTENT_X_MM = 14.0
_REFERENCE_CONTENT_WIDTH_MM = 182.0
_INK = PdfColor(17, 20, 24)
_INK_SOFT = PdfColor(75, 85, 99)
_MUTED = PdfColor(107, 114, 128)
_MUTED_SOFT = PdfColor(156, 163, 175)
_RULE = PdfColor(209, 213, 219)
_RULE_DARK = PdfColor(15, 23, 42)
_ACCENT = PdfColor(23, 99, 207)
_PANEL = PdfColor(249, 250, 251)
_PAPER = PdfColor(255, 255, 255)
_QR_COLUMNS = 3
_MAIN_FIRST_PAGE_QR_ROWS = 3
_MAIN_CONTINUATION_QR_ROWS = 4
_KIT_QR_ROWS_PER_PAGE = 3
_QR_CARD_SIZE_MM = 58.0
_QR_CARD_GAP_MM = 3.2
_QR_IMAGE_SIZE_MM = 50.5
_KIT_QR_CARD_SIZE_MM = 56.5
_KIT_QR_IMAGE_SIZE_MM = 44.0
_FALLBACK_GROUP_SIZE = 4
_FALLBACK_ROW_HEIGHT_MM = 4.25
_RECOVERY_FALLBACK_BODY_SIZE_PT = 6.6
_RECOVERY_FALLBACK_LEFT_INSET_MM = 2.6
_RECOVERY_FALLBACK_RIGHT_INSET_MM = 2.4
_RECOVERY_FALLBACK_LINE_SAFETY_MM = 0.2
_SHARD_FALLBACK_COLUMNS = 2
_SHARD_FALLBACK_COLUMN_GAP_MM = 4.0
_SHARD_FALLBACK_ROW_HEIGHT_MM = 2.9
_SHARD_FALLBACK_HEIGHT_MM = 116.0
_SHARD_FALLBACK_LINE_SAFETY_MM = 0.2
_ICON_HUB = chr(0xE9F4)
_ICON_LANGUAGE = chr(0xE894)
_ICON_BUILD = chr(0xE869)
_ICON_ADJUST = chr(0xE39E)
_ICON_CHECK_BOX = chr(0xE835)
_ICON_VERIFIED_USER = chr(0xE8E8)
_ICON_LOCK = chr(0xE897)

_MAIN_FIRST_PAGE_QR_TOP_MM = 56.5
_MAIN_CONTINUATION_QR_TOP_MM = 38.0
_FOOTER_BOTTOM_INSET_MM = 16.7
_QR_GRID_FOOTER_CLEARANCE_MM = 3.0
_MINIMUM_QR_CARD_SIZE_MM = 44.0
_RECOVERY_HEADER_RULE_MIN_Y_MM = 46.0
_RECOVERY_META_RULE_CLEARANCE_MM = 2.0
_RECOVERY_HEADER_INSTRUCTIONS_OFFSET_MM = 3.0
_RECOVERY_INSTRUCTIONS_HEIGHT_MM = 15.0
_RECOVERY_INSTRUCTIONS_HEADING_GAP_MM = 2.5
_RECOVERY_HEADING_FALLBACK_OFFSET_MM = 12.5
_RECOVERY_META_VALUE_PADDING_MM = 0.2
_RECOVERY_SIGNING_KEY_MIN_SIZE_PT = 6.0


@dataclass(frozen=True)
class _ArchiveMainGeometry:
    page: PageGeometry
    content_width_mm: float
    grid_bottom_mm: float
    first_page_grid: ResolvedGrid
    continuation_grid: ResolvedGrid


@dataclass(frozen=True)
class _ArchiveRecoveryGeometry:
    page: PageGeometry
    content_rect: PdfRect
    metadata_rects: tuple[PdfRect, ...]
    header_rule_y_mm: float
    instructions_area: PdfRect
    fallback_heading_y_mm: float
    fallback_area: PdfRect
    validation_area: PdfRect
    footer_rule_y_mm: float


@dataclass(frozen=True)
class _ArchiveRecoveryMetadataRow:
    label: str
    values: tuple[str, ...]
    guidance: str = ""
    visible: bool = True
    grouped_signing_key: bool = False


@dataclass(frozen=True)
class _ArchiveSingleGeometry:
    page: PageGeometry
    content_rect: PdfRect
    qr_frame: PdfRect
    fallback_area: PdfRect
    footer_rule_y_mm: float


@dataclass(frozen=True)
class _ArchiveShardFallbackLayout:
    columns: int
    row_height_mm: float
    line_length: int
    body_font_size_pt: float
    title_font_size_pt: float


@dataclass(frozen=True)
class _ArchiveKitGeometry:
    page: PageGeometry
    content_rect: PdfRect
    qr_grid: ResolvedGrid
    instruction_shell: PdfRect
    instruction_footer_y_mm: float


def _archive_main_geometry(inputs: RenderInputs) -> _ArchiveMainGeometry:
    page = resolve_page_geometry(inputs)
    capabilities = load_template_style(inputs.design_name).capabilities
    preferred_card_size_mm = capabilities.main_qr_grid_size_mm or _QR_CARD_SIZE_MM
    content_width_mm = page.width_mm - 2 * _CONTENT_X_MM
    footer_rule_y_mm = page.height_mm - _FOOTER_BOTTOM_INSET_MM
    grid_bottom_mm = footer_rule_y_mm - _QR_GRID_FOOTER_CLEARANCE_MM
    grid_policy = GridPolicy(
        max_columns=_QR_COLUMNS,
        max_rows=_MAIN_CONTINUATION_QR_ROWS,
        preferred_item_width_mm=preferred_card_size_mm,
        preferred_item_height_mm=preferred_card_size_mm,
        minimum_item_width_mm=_MINIMUM_QR_CARD_SIZE_MM,
        minimum_item_height_mm=_MINIMUM_QR_CARD_SIZE_MM,
        minimum_column_gap_mm=_QR_CARD_GAP_MM,
        minimum_row_gap_mm=_QR_CARD_GAP_MM,
        preserve_item_aspect_ratio=True,
        horizontal_distribution="space_between",
    )
    first_page_grid = resolve_grid(
        PdfRect(
            _CONTENT_X_MM,
            _MAIN_FIRST_PAGE_QR_TOP_MM,
            content_width_mm,
            grid_bottom_mm - _MAIN_FIRST_PAGE_QR_TOP_MM,
        ),
        replace(
            grid_policy,
            max_rows=_MAIN_FIRST_PAGE_QR_ROWS,
            vertical_distribution="space_between",
        ),
    )
    continuation_grid = resolve_grid(
        PdfRect(
            _CONTENT_X_MM,
            _MAIN_CONTINUATION_QR_TOP_MM,
            content_width_mm,
            grid_bottom_mm - _MAIN_CONTINUATION_QR_TOP_MM,
        ),
        grid_policy,
    )
    return _ArchiveMainGeometry(
        page=page,
        content_width_mm=content_width_mm,
        grid_bottom_mm=grid_bottom_mm,
        first_page_grid=first_page_grid,
        continuation_grid=continuation_grid,
    )


def _archive_recovery_geometry(
    surface: PdfSurface,
    inputs: RenderInputs,
    recovery_meta: RecoveryMeta,
    context: _ArchiveContext,
) -> _ArchiveRecoveryGeometry:
    page = resolve_page_geometry(inputs)
    content_rect = PdfRect(
        _CONTENT_X_MM,
        0.0,
        page.width_mm - 2 * _CONTENT_X_MM,
        page.height_mm,
    )
    footer_rule_y_mm = page.height_mm - _FOOTER_BOTTOM_INSET_MM
    validation_height_mm = 16.5
    validation_bottom_mm = footer_rule_y_mm - 2.0
    validation_area = PdfRect(
        content_rect.x_mm,
        validation_bottom_mm - validation_height_mm,
        content_rect.width_mm,
        validation_height_mm,
    )
    metadata_rows = _archive_recovery_metadata_rows(
        recovery_meta,
        doc_id=context.doc_id,
        created_timestamp_utc=context.created_timestamp_utc,
    )
    metadata_rects = _archive_recovery_metadata_rects(
        surface,
        metadata_rows,
        content_rect=content_rect,
    )
    metadata_bottom_mm = max(
        rect.bottom_mm
        for row, rect in zip(metadata_rows, metadata_rects, strict=True)
        if row.visible
    )
    header_rule_y_mm = max(
        _RECOVERY_HEADER_RULE_MIN_Y_MM,
        metadata_bottom_mm + _RECOVERY_META_RULE_CLEARANCE_MM,
    )
    instructions_area = PdfRect(
        content_rect.x_mm,
        header_rule_y_mm + _RECOVERY_HEADER_INSTRUCTIONS_OFFSET_MM,
        content_rect.width_mm,
        _RECOVERY_INSTRUCTIONS_HEIGHT_MM,
    )
    fallback_heading_y_mm = instructions_area.bottom_mm + _RECOVERY_INSTRUCTIONS_HEADING_GAP_MM
    fallback_top_mm = fallback_heading_y_mm + _RECOVERY_HEADING_FALLBACK_OFFSET_MM
    fallback_bottom_mm = validation_area.y_mm - 3.5
    fallback_height_mm = fallback_bottom_mm - fallback_top_mm
    if fallback_height_mm < 40.0:
        raise ValueError(
            "Archive recovery page cannot satisfy fallback and validation minimum regions: "
            f"page={page.width_mm:.3f}x{page.height_mm:.3f}mm"
        )
    return _ArchiveRecoveryGeometry(
        page=page,
        content_rect=content_rect,
        metadata_rects=metadata_rects,
        header_rule_y_mm=header_rule_y_mm,
        instructions_area=instructions_area,
        fallback_heading_y_mm=fallback_heading_y_mm,
        fallback_area=PdfRect(
            content_rect.x_mm + 2.0,
            fallback_top_mm,
            content_rect.width_mm - 4.0,
            fallback_height_mm,
        ),
        validation_area=validation_area,
        footer_rule_y_mm=footer_rule_y_mm,
    )


def _archive_recovery_metadata_rects(
    surface: PdfSurface,
    rows: Sequence[_ArchiveRecoveryMetadataRow],
    *,
    content_rect: PdfRect,
) -> tuple[PdfRect, ...]:
    reference_positions = (
        PdfRect(14.0, 26.0, 22.0, 10.0),
        PdfRect(38.0, 26.0, 28.0, 10.0),
        PdfRect(68.0, 26.0, 63.0, 10.0),
        PdfRect(133.0, 26.0, 63.0, 10.0),
        PdfRect(68.0, 26.0, 63.0, 10.0),
    )
    if len(rows) != len(reference_positions):
        raise ValueError("Archive recovery metadata rows must match reference positions")
    width_scale = content_rect.width_mm / _REFERENCE_CONTENT_WIDTH_MM
    positions: list[PdfRect] = []
    guidance_style = _body_style(size_pt=6.0, color=_INK_SOFT)
    for row, reference_rect in zip(
        rows,
        reference_positions,
        strict=True,
    ):
        width_mm = reference_rect.width_mm * width_scale
        value_width_mm = width_mm
        value_lines = _archive_recovery_metadata_value_lines(row)
        value_style = _archive_recovery_metadata_value_style(row)
        text = "\n".join(value_lines)
        fit = fit_text_to_width(
            surface,
            text,
            value_style,
            max_width_mm=value_width_mm,
            max_lines=2 if row.grouped_signing_key else None,
            policy=(TextFitPolicy.SHRINK if row.grouped_signing_key else TextFitPolicy.WRAP),
            min_size_pt=(_RECOVERY_SIGNING_KEY_MIN_SIZE_PT if row.grouped_signing_key else None),
            line_height_multiplier=1.08,
        )
        guidance_height_mm = 0.0
        if row.guidance:
            guidance_height_mm = (
                fit_text_to_width(
                    surface,
                    row.guidance,
                    guidance_style,
                    max_width_mm=value_width_mm,
                    policy=TextFitPolicy.WRAP,
                    line_height_multiplier=1.1,
                ).height_mm
                + 1.0
            )
        required_height_mm = (
            2.7 + guidance_height_mm + fit.height_mm + _RECOVERY_META_VALUE_PADDING_MM
        )
        positions.append(
            PdfRect(
                content_rect.x_mm + (reference_rect.x_mm - _CONTENT_X_MM) * width_scale,
                reference_rect.y_mm,
                width_mm,
                max(reference_rect.height_mm, required_height_mm),
            )
        )
    return tuple(positions)


def _archive_recovery_metadata_value_lines(
    row: _ArchiveRecoveryMetadataRow,
) -> tuple[str, ...]:
    values = tuple(value for value in row.values if value)
    if not row.grouped_signing_key:
        return values
    return tuple(values)


def _archive_recovery_metadata_value_style(row: _ArchiveRecoveryMetadataRow) -> TextStyle:
    if row.grouped_signing_key:
        return _mono_style(size_pt=6.4, bold=True, color=_INK)
    return _mono_style(size_pt=6.4, bold=True, color=_INK)


def _archive_recovery_metadata_rows(
    recovery_meta: RecoveryMeta,
    *,
    doc_id: str,
    created_timestamp_utc: str,
) -> tuple[_ArchiveRecoveryMetadataRow, ...]:
    passphrase = recovery_passphrase_display(recovery_meta)
    return (
        _ArchiveRecoveryMetadataRow("Document ID", (doc_id,)),
        _ArchiveRecoveryMetadataRow("Created (UTC)", (created_timestamp_utc,)),
        _ArchiveRecoveryMetadataRow(
            recovery_meta.quorum_label or "Shard Quorum",
            (recovery_meta.quorum_value,) if recovery_meta.quorum_value else (),
            visible=bool(recovery_meta.quorum_value),
        ),
        _ArchiveRecoveryMetadataRow(
            "Signing Key",
            tuple(recovery_meta.signing_pub_lines),
            visible=bool(recovery_meta.signing_pub_lines),
            grouped_signing_key=True,
        ),
        _ArchiveRecoveryMetadataRow(
            passphrase.label,
            passphrase.value_lines,
            passphrase.guidance,
            visible=bool(passphrase.value_lines),
        ),
    )


def _archive_single_geometry(inputs: RenderInputs) -> _ArchiveSingleGeometry:
    page = resolve_page_geometry(inputs)
    content_rect = PdfRect(
        _CONTENT_X_MM,
        0.0,
        page.width_mm - 2 * _CONTENT_X_MM,
        page.height_mm,
    )
    footer_rule_y_mm = page.height_mm - _FOOTER_BOTTOM_INSET_MM
    fallback_height_mm = _SHARD_FALLBACK_HEIGHT_MM
    fallback_bottom_mm = footer_rule_y_mm - 3.8
    fallback_area = PdfRect(
        content_rect.x_mm,
        fallback_bottom_mm - fallback_height_mm,
        content_rect.width_mm,
        fallback_height_mm,
    )
    qr_size_mm = min(66.0, content_rect.width_mm)
    qr_top_min_mm = 58.0
    qr_top_max_mm = fallback_area.y_mm - 9.0 - qr_size_mm
    if qr_size_mm < 55.0 or qr_top_max_mm < qr_top_min_mm:
        raise ValueError(
            "Archive shard page cannot satisfy QR and fallback minimum regions: "
            f"page={page.width_mm:.3f}x{page.height_mm:.3f}mm"
        )
    qr_top_mm = min(max(60.0, qr_top_min_mm), qr_top_max_mm)
    return _ArchiveSingleGeometry(
        page=page,
        content_rect=content_rect,
        qr_frame=PdfRect(
            content_rect.x_mm + (content_rect.width_mm - qr_size_mm) / 2.0,
            qr_top_mm,
            qr_size_mm,
            qr_size_mm,
        ),
        fallback_area=fallback_area,
        footer_rule_y_mm=footer_rule_y_mm,
    )


def _archive_kit_geometry(inputs: RenderInputs) -> _ArchiveKitGeometry:
    page = resolve_page_geometry(inputs)
    content_rect = PdfRect(
        _CONTENT_X_MM,
        0.0,
        page.width_mm - 2 * _CONTENT_X_MM,
        page.height_mm,
    )
    qr_container = PdfRect(
        content_rect.x_mm,
        45.8,
        content_rect.width_mm,
        page.height_mm - 45.8 - _MARGIN_MM,
    )
    qr_grid = resolve_grid(
        qr_container,
        GridPolicy(
            max_columns=_QR_COLUMNS,
            max_rows=_KIT_QR_ROWS_PER_PAGE,
            preferred_item_width_mm=_KIT_QR_CARD_SIZE_MM,
            preferred_item_height_mm=_KIT_QR_CARD_SIZE_MM,
            minimum_item_width_mm=_MINIMUM_QR_CARD_SIZE_MM,
            minimum_item_height_mm=_MINIMUM_QR_CARD_SIZE_MM,
            minimum_column_gap_mm=_QR_CARD_GAP_MM,
            minimum_row_gap_mm=_QR_CARD_GAP_MM,
            preserve_item_aspect_ratio=True,
            horizontal_distribution="space_between",
        ),
    )
    instruction_shell = PdfRect(
        content_rect.x_mm,
        _MARGIN_MM,
        content_rect.width_mm,
        page.height_mm - 2 * _MARGIN_MM,
    )
    instruction_column_width_mm = (instruction_shell.width_mm - 19.0) / 2.0
    if instruction_column_width_mm < 70.0:
        raise ValueError(
            "Archive kit instruction page cannot satisfy minimum column width: "
            f"page={page.width_mm:.3f}x{page.height_mm:.3f}mm"
        )
    instruction_footer_y_mm = page.height_mm - 30.0
    return _ArchiveKitGeometry(
        page=page,
        content_rect=content_rect,
        qr_grid=qr_grid,
        instruction_shell=instruction_shell,
        instruction_footer_y_mm=instruction_footer_y_mm,
    )


def render_archive_main_direct_pdf(inputs: RenderInputs) -> RenderResult:
    """Render an Archive main document directly to PDF."""

    return _render_archive_plan(inputs, build_archive_main_direct_plan)


def render_archive_recovery_direct_pdf(inputs: RenderInputs) -> RenderResult:
    """Render an Archive recovery document directly to PDF."""

    return _render_archive_plan(inputs, build_archive_recovery_direct_plan)


def render_archive_shard_direct_pdf(inputs: RenderInputs) -> RenderResult:
    """Render an Archive shard document directly to PDF."""

    return _render_archive_plan(inputs, build_archive_shard_direct_plan)


def render_archive_signing_key_shard_direct_pdf(inputs: RenderInputs) -> RenderResult:
    """Render an Archive signing-key shard document directly to PDF."""

    return _render_archive_plan(inputs, build_archive_signing_key_shard_direct_plan)


def render_archive_kit_direct_pdf(inputs: RenderInputs) -> RenderResult:
    """Render an Archive recovery-kit document directly to PDF."""

    return _render_archive_plan(inputs, build_archive_kit_direct_plan)


def _render_archive_plan(
    inputs: RenderInputs,
    builder: StructuredPlanBuilder,
) -> RenderResult:
    return render_structured_plan(inputs, style_name="archive", builder=builder)


def build_archive_main_direct_plan(surface: PdfSurface, inputs: RenderInputs) -> ArchiveDirectPlan:
    """Build measured Archive main-document pages and proof."""

    _validate_qr_inputs(inputs, expected_doc_type=DOC_TYPE_MAIN)
    payloads = _resolved_qr_payloads(inputs)
    items = _qr_payload_items(payloads, config=inputs.qr_config or QrConfig())
    geometry = _archive_main_geometry(inputs)
    qr_pages = _paginate_qr_items(
        items,
        capacity=geometry.continuation_grid.capacity,
        first_page_capacity=geometry.first_page_grid.capacity,
    )
    context = _build_archive_context(inputs, doc_type=DOC_TYPE_MAIN)
    page_plans = tuple(
        _build_main_qr_page(
            surface,
            context,
            qr_page,
            geometry=geometry,
            total_pages=len(qr_pages),
        )
        for qr_page in qr_pages
    )
    artifact_proof = build_render_artifact_proof(
        inputs,
        qr_payloads=payloads,
        encoded_payload_count=len(payloads),
        physical_qr_count=len(items),
        physical_qr_payload_indexes=tuple(item.payload_index for item in items),
        page_count=len(page_plans),
        fallback_proof=None,
    )
    return ArchiveDirectPlan(page_plans=page_plans, artifact_proof=artifact_proof)


def build_archive_recovery_direct_plan(
    surface: PdfSurface,
    inputs: RenderInputs,
) -> ArchiveDirectPlan:
    """Build measured Archive recovery-document pages and proofs."""

    _validate_recovery_inputs(inputs)
    recovery_meta = inputs.recovery_meta or RecoveryMeta()
    context = _build_archive_context(inputs, doc_type=DOC_TYPE_RECOVERY)
    passphrase_pagination = _paginate_archive_passphrase(surface, inputs, recovery_meta)
    geometry = _archive_recovery_geometry(
        surface,
        inputs,
        passphrase_pagination.inline_meta,
        context,
    )
    overflow_meta = replace(
        passphrase_pagination.inline_meta,
        passphrase=None,
        passphrase_lines=(),
        passphrase_instructions="",
    )
    continuation_geometry = (
        _archive_recovery_geometry(surface, inputs, overflow_meta, context)
        if passphrase_pagination.continuation_pages
        else geometry
    )
    fallback_spec = ResponsiveFallbackSpec(
        group_size=_FALLBACK_GROUP_SIZE,
        row_height_mm=_FALLBACK_ROW_HEIGHT_MM,
        body_style=_mono_style(size_pt=_RECOVERY_FALLBACK_BODY_SIZE_PT, color=_INK),
        number_style=_mono_style(size_pt=_RECOVERY_FALLBACK_BODY_SIZE_PT, color=_INK),
        content_left_inset_mm=_RECOVERY_FALLBACK_LEFT_INSET_MM,
        content_right_inset_mm=_RECOVERY_FALLBACK_RIGHT_INSET_MM,
        vertical_reserved_mm=4.0,
        number_gap_mm=0.0,
        inline_number=True,
        safety_mm=_RECOVERY_FALLBACK_LINE_SAFETY_MM,
    )
    fallback_pagination = resolve_responsive_fallback_pagination(
        surface,
        inputs.fallback_sections or (),
        first_profile=ResponsiveFallbackPageProfile(
            area=geometry.fallback_area,
            spec=fallback_spec,
        ),
        continuation_profile=ResponsiveFallbackPageProfile(
            area=continuation_geometry.fallback_area,
            spec=fallback_spec,
        ),
    )
    sections = fallback_pagination.sections
    fallback_pages = fallback_pagination.pages
    total_pages = len(fallback_pages) + len(passphrase_pagination.continuation_pages)
    fallback_page_plans = tuple(
        _build_recovery_page(
            surface,
            context,
            (
                passphrase_pagination.inline_meta
                if fallback_page.page_number == 1 or not passphrase_pagination.continuation_pages
                else overflow_meta
            ),
            fallback_page,
            geometry=(
                geometry
                if fallback_page.page_number == 1 or not passphrase_pagination.continuation_pages
                else continuation_geometry
            ),
            total_pages=total_pages,
        )
        for fallback_page in fallback_pages
    )
    passphrase_page_plans = tuple(
        _build_passphrase_continuation_page(
            surface,
            context,
            geometry=geometry,
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
        qr_payloads=(),
        encoded_payload_count=len(inputs.qr_payloads or inputs.frames),
        physical_qr_count=0,
        physical_qr_payload_indexes=(),
        page_count=len(page_plans),
        fallback_proof=fallback_proof,
    )
    return ArchiveDirectPlan(
        page_plans=page_plans,
        artifact_proof=artifact_proof,
        fallback_proof=fallback_proof,
    )


def _paginate_archive_passphrase(
    surface: PdfSurface,
    inputs: RenderInputs,
    recovery_meta: RecoveryMeta,
) -> RecoveryPassphrasePagination:
    page = resolve_page_geometry(inputs)
    content_width_mm = page.width_mm - 2 * _CONTENT_X_MM
    width_scale = content_width_mm / _REFERENCE_CONTENT_WIDTH_MM
    inline_width_mm = 45.0 * width_scale
    continuation_width_mm = 90.0 * width_scale
    style = _mono_style(size_pt=6.4, bold=True, color=_INK)
    guidance_style = _body_style(size_pt=6.0, color=_INK_SOFT)
    value_rect = _passphrase_continuation_value_rect(page, continuation_width_mm)
    return paginate_recovery_passphrase(
        surface,
        recovery_meta,
        style=style,
        guidance_style=guidance_style,
        max_width_mm=inline_width_mm,
        continuation_width_mm=continuation_width_mm,
        inline_height_mm=12.0 * surface.line_height(style, multiplier=1.08),
        continuation_height_mm=value_rect.height_mm,
        line_height_multiplier=1.08,
    )


def _passphrase_continuation_value_rect(
    page: PageGeometry,
    width_mm: float,
) -> PdfRect:
    top_mm = 69.0
    bottom_mm = page.height_mm - _FOOTER_BOTTOM_INSET_MM - 5.0
    if bottom_mm <= top_mm:
        raise ValueError("Archive page has zero-capacity passphrase continuation area")
    return PdfRect(
        (page.width_mm - width_mm) / 2.0,
        top_mm,
        width_mm,
        bottom_mm - top_mm,
    )


def build_archive_shard_direct_plan(
    surface: PdfSurface,
    inputs: RenderInputs,
) -> ArchiveDirectPlan:
    """Build measured Archive shard-document pages and proofs."""

    return _build_archive_single_qr_fallback_plan(
        surface,
        inputs,
        expected_doc_type=DOC_TYPE_SHARD,
    )


def build_archive_signing_key_shard_direct_plan(
    surface: PdfSurface,
    inputs: RenderInputs,
) -> ArchiveDirectPlan:
    """Build measured Archive signing-key shard pages and proofs."""

    return _build_archive_single_qr_fallback_plan(
        surface,
        inputs,
        expected_doc_type=DOC_TYPE_SIGNING_KEY_SHARD,
    )


def build_archive_kit_direct_plan(surface: PdfSurface, inputs: RenderInputs) -> ArchiveDirectPlan:
    """Build measured Archive recovery-kit pages and proof."""

    _validate_qr_inputs(inputs, expected_doc_type=DOC_TYPE_KIT)
    geometry = _archive_kit_geometry(inputs)
    payloads = _resolved_qr_payloads(inputs)
    items = _qr_payload_items(payloads, config=inputs.qr_config or QrConfig())
    qr_pages = _paginate_qr_items(items, capacity=geometry.qr_grid.capacity)
    context = _build_archive_context(inputs, doc_type=DOC_TYPE_KIT)
    total_pages = len(qr_pages) + 1
    page_plans = tuple(
        _build_kit_qr_page(
            surface,
            context,
            qr_page,
            geometry=geometry,
            total_pages=total_pages,
        )
        for qr_page in qr_pages
    )
    page_plans = (
        *page_plans,
        _build_kit_instruction_page(
            surface,
            context,
            geometry=geometry,
            page_number=total_pages,
            total_pages=total_pages,
        ),
    )
    artifact_proof = build_render_artifact_proof(
        inputs,
        qr_payloads=payloads,
        encoded_payload_count=len(payloads),
        physical_qr_count=len(items),
        physical_qr_payload_indexes=tuple(item.payload_index for item in items),
        page_count=len(page_plans),
        fallback_proof=None,
    )
    return ArchiveDirectPlan(page_plans=page_plans, artifact_proof=artifact_proof)


def _build_archive_single_qr_fallback_plan(
    surface: PdfSurface,
    inputs: RenderInputs,
    *,
    expected_doc_type: str,
) -> ArchiveDirectPlan:
    _validate_single_qr_fallback_inputs(inputs, expected_doc_type=expected_doc_type)
    geometry = _archive_single_geometry(inputs)
    payload = _resolved_single_qr_payload(inputs)
    qr_image = _qr_image(payload, config=inputs.qr_config or QrConfig())
    context = _build_archive_context(inputs, doc_type=expected_doc_type)
    fallback_layout, sections = _resolve_archive_shard_fallback(
        surface,
        inputs,
        area=geometry.fallback_area,
    )
    fallback_pages = _paginate_fallback_entries(
        _fallback_entries(sections),
        capacity=_shard_fallback_capacity(
            geometry.fallback_area,
            layout=fallback_layout,
        ),
    )
    page_plans = tuple(
        _build_single_qr_fallback_page(
            surface,
            context,
            fallback_page,
            qr_image=qr_image,
            geometry=geometry,
            fallback_layout=fallback_layout,
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
    return ArchiveDirectPlan(
        page_plans=page_plans,
        artifact_proof=artifact_proof,
        fallback_proof=fallback_proof,
    )


def _build_main_qr_page(
    surface: PdfSurface,
    context: _ArchiveContext,
    qr_page: _QrPage,
    *,
    geometry: _ArchiveMainGeometry,
    total_pages: int,
) -> DirectPdfPagePlan:
    page_label = f"Page {qr_page.page_number} / {total_pages}"
    prefix = _component_prefix("archive-main", qr_page.page_number)
    plans: list[PaintPlan] = []
    plans.extend(_archive_page_background(surface, prefix=prefix, page_rect=geometry.page.rect))
    plans.extend(
        _main_header_plans(
            surface,
            context,
            prefix=prefix,
            page_label=page_label,
            page_rect=geometry.page.rect,
        )
    )
    if qr_page.page_number == 1:
        plans.extend(
            _instructions_panel_plans(
                surface,
                context,
                prefix=prefix,
                rect=PdfRect(_CONTENT_X_MM, 31.5, geometry.content_width_mm, 20.0),
            )
        )
        plans.append(
            Rule(component_id=f"{prefix}-qr-rule", color=_RULE_DARK).plan(
                surface, PdfRect(_CONTENT_X_MM, 54.0, geometry.content_width_mm, 0.5)
            )
        )
        qr_top = _MAIN_FIRST_PAGE_QR_TOP_MM
    else:
        plans.append(
            Rule(component_id=f"{prefix}-qr-rule", color=_RULE_DARK).plan(
                surface, PdfRect(_CONTENT_X_MM, 34.0, geometry.content_width_mm, 0.5)
            )
        )
        qr_top = _MAIN_CONTINUATION_QR_TOP_MM
    grid = geometry.first_page_grid if qr_page.page_number == 1 else geometry.continuation_grid
    item_rects = grid.item_rects(
        len(qr_page.items),
        reserve_all_rows=qr_page.page_number == 1,
    )
    plans.extend(
        _qr_grid_plans(
            surface,
            qr_page,
            prefix=prefix,
            top_mm=qr_top,
            card_size_mm=grid.item_width_mm,
            image_size_mm=grid.item_width_mm * (_QR_IMAGE_SIZE_MM / _QR_CARD_SIZE_MM),
            label_prefix="SEGMENT",
            item_rects=item_rects,
        )
    )
    plans.extend(
        _footer_plans(
            surface,
            context,
            prefix=prefix,
            page_label=page_label,
            page_rect=geometry.page.rect,
        )
    )
    qr_card_ids = tuple(f"{prefix}-qr-card-{item.payload_index}" for item in qr_page.items)
    top_zone_bottom_mm = 54.5 if qr_page.page_number == 1 else 34.5
    separation_constraints = (
        SeparationConstraint(
            constraint_id=f"{prefix}-header-qr-clearance",
            first=LayoutRegion(
                region_id=f"{prefix}-header-zone",
                rect=PdfRect(0.0, 0.0, geometry.page.width_mm, top_zone_bottom_mm),
            ),
            second=ComponentGroup(group_id=f"{prefix}-qr-grid-top", component_ids=qr_card_ids),
            minimum_clearance_mm=2.0,
        ),
        SeparationConstraint(
            constraint_id=f"{prefix}-qr-footer-clearance",
            first=ComponentGroup(group_id=f"{prefix}-qr-grid", component_ids=qr_card_ids),
            second=LayoutRegion(
                region_id=f"{prefix}-footer-zone",
                rect=PdfRect(
                    _CONTENT_X_MM,
                    geometry.grid_bottom_mm + _QR_GRID_FOOTER_CLEARANCE_MM,
                    geometry.content_width_mm,
                    geometry.page.height_mm
                    - (geometry.grid_bottom_mm + _QR_GRID_FOOTER_CLEARANCE_MM),
                ),
            ),
            minimum_clearance_mm=_QR_GRID_FOOTER_CLEARANCE_MM,
        ),
    )
    return build_page_plan(
        page_number=qr_page.page_number,
        rect=geometry.page.rect,
        plans=plans,
        separation_constraints=separation_constraints,
    )


def _build_recovery_page(
    surface: PdfSurface,
    context: _ArchiveContext,
    recovery_meta: RecoveryMeta,
    fallback_page: _FallbackPage,
    *,
    geometry: _ArchiveRecoveryGeometry,
    total_pages: int,
) -> DirectPdfPagePlan:
    page_label = f"Page {fallback_page.page_number} / {total_pages}"
    prefix = _component_prefix("archive-recovery", fallback_page.page_number)
    plans: list[PaintPlan] = []
    plans.extend(_archive_page_background(surface, prefix=prefix, page_rect=geometry.page.rect))
    plans.extend(
        _recovery_header_plans(
            surface,
            context,
            recovery_meta,
            prefix=prefix,
            geometry=geometry,
        )
    )
    plans.extend(
        _instructions_panel_plans(
            surface,
            context,
            prefix=prefix,
            rect=geometry.instructions_area,
        )
    )
    plans.extend(
        _recovery_fallback_plans(
            surface,
            fallback_page,
            prefix=prefix,
            area=geometry.fallback_area,
            content_rect=geometry.content_rect,
            heading_y_mm=geometry.fallback_heading_y_mm,
        )
    )
    plans.extend(
        _recovery_validation_plans(
            surface,
            prefix=prefix,
            rect=geometry.validation_area,
        )
    )
    plans.extend(
        _footer_plans(
            surface,
            context,
            prefix=prefix,
            page_label=page_label,
            page_rect=geometry.page.rect,
        )
    )
    metadata_value_ids = tuple(
        plan.component_id for plan in plans if plan.component_id.startswith(f"{prefix}-meta-value-")
    )
    constraints = (
        SeparationConstraint(
            constraint_id=f"{prefix}-metadata-header-rule-clearance",
            first=ComponentGroup(
                group_id=f"{prefix}-metadata-values",
                component_ids=metadata_value_ids,
            ),
            second=ComponentGroup(
                group_id=f"{prefix}-header-rule-for-metadata",
                component_ids=(f"{prefix}-header-rule",),
            ),
            minimum_clearance_mm=_RECOVERY_META_RULE_CLEARANCE_MM,
        ),
        SeparationConstraint(
            constraint_id=f"{prefix}-header-instructions-clearance",
            first=ComponentGroup(
                group_id=f"{prefix}-header-rule-group",
                component_ids=(f"{prefix}-header-rule",),
            ),
            second=ComponentGroup(
                group_id=f"{prefix}-instructions-group",
                component_ids=(f"{prefix}-instructions-panel",),
            ),
            minimum_clearance_mm=(_RECOVERY_HEADER_INSTRUCTIONS_OFFSET_MM - 0.55),
        ),
        SeparationConstraint(
            constraint_id=f"{prefix}-instructions-fallback-clearance",
            first=ComponentGroup(
                group_id=f"{prefix}-instructions-for-fallback",
                component_ids=(f"{prefix}-instructions-panel",),
            ),
            second=LayoutRegion(
                region_id=f"{prefix}-fallback-section-zone",
                rect=PdfRect(
                    geometry.content_rect.x_mm,
                    geometry.fallback_heading_y_mm,
                    geometry.content_rect.width_mm,
                    geometry.fallback_area.bottom_mm - geometry.fallback_heading_y_mm,
                ),
            ),
            minimum_clearance_mm=_RECOVERY_INSTRUCTIONS_HEADING_GAP_MM,
        ),
        SeparationConstraint(
            constraint_id=f"{prefix}-fallback-validation-clearance",
            first=LayoutRegion(region_id=f"{prefix}-fallback-zone", rect=geometry.fallback_area),
            second=LayoutRegion(
                region_id=f"{prefix}-validation-zone",
                rect=geometry.validation_area,
            ),
            minimum_clearance_mm=3.5,
        ),
        SeparationConstraint(
            constraint_id=f"{prefix}-validation-footer-clearance",
            first=LayoutRegion(
                region_id=f"{prefix}-validation-zone-footer-check",
                rect=geometry.validation_area,
            ),
            second=LayoutRegion(
                region_id=f"{prefix}-footer-zone",
                rect=PdfRect(
                    geometry.content_rect.x_mm,
                    geometry.footer_rule_y_mm,
                    geometry.content_rect.width_mm,
                    geometry.page.height_mm - geometry.footer_rule_y_mm,
                ),
            ),
            minimum_clearance_mm=2.0,
        ),
    )
    return build_page_plan(
        page_number=fallback_page.page_number,
        rect=geometry.page.rect,
        plans=plans,
        separation_constraints=constraints,
    )


def _build_passphrase_continuation_page(
    surface: PdfSurface,
    context: _ArchiveContext,
    *,
    geometry: _ArchiveRecoveryGeometry,
    continuation_page: RecoveryPassphraseContinuationPage,
    page_number: int,
    total_pages: int,
) -> DirectPdfPagePlan:
    prefix = _component_prefix("archive-recovery", page_number)
    page_label = f"Page {page_number} / {total_pages}"
    passphrase_width_mm = 90.0 * (geometry.content_rect.width_mm / _REFERENCE_CONTENT_WIDTH_MM)
    value_rect = _passphrase_continuation_value_rect(
        geometry.page,
        passphrase_width_mm,
    )
    panel_rect = PdfRect(
        value_rect.x_mm - 3.0,
        value_rect.y_mm - 2.0,
        value_rect.width_mm + 6.0,
        value_rect.height_mm + 4.0,
    )
    plans: list[PaintPlan] = []
    plans.extend(_archive_page_background(surface, prefix=prefix, page_rect=geometry.page.rect))
    plans.extend(
        [
            TextBox(
                component_id=f"{prefix}-passphrase-continuation-title",
                text="RECOVERY PASSPHRASE",
                style=_display_style(size_pt=15.2, bold=True),
                policy=TextFitPolicy.SHRINK,
                min_size_pt=12.0,
            ).plan(surface, PdfRect(_CONTENT_X_MM, 16.0, 112.0, 7.0)),
            Rule(
                component_id=f"{prefix}-passphrase-continuation-title-rule",
                color=_RULE,
            ).plan(surface, PdfRect(_CONTENT_X_MM, 26.0, 90.0, 0.25)),
            TextBox(
                component_id=f"{prefix}-passphrase-continuation-doc-id",
                text=f"DOCUMENT ID: {context.doc_id}",
                style=_mono_style(size_pt=6.2, bold=True, color=_INK),
                policy=TextFitPolicy.SHRINK,
                align=TextAlign.RIGHT,
                min_size_pt=6.0,
            ).plan(
                surface,
                PdfRect(
                    geometry.page.rect.right_mm - _CONTENT_X_MM - 72.0,
                    17.0,
                    72.0,
                    4.0,
                ),
            ),
            TextBox(
                component_id=f"{prefix}-passphrase-continuation-part",
                text=(
                    "METADATA CONTINUATION "
                    f"{continuation_page.page_index} / {continuation_page.total_pages}"
                ),
                style=_mono_style(size_pt=7.2, bold=True, color=_ACCENT),
                policy=TextFitPolicy.FAIL,
            ).plan(
                surface,
                PdfRect(_CONTENT_X_MM, 36.0, geometry.content_rect.width_mm, 4.5),
            ),
            TextBox(
                component_id=f"{prefix}-passphrase-continuation-instructions",
                text=continuation_page.instructions,
                style=_body_style(size_pt=7.8, color=_INK_SOFT),
                policy=TextFitPolicy.WRAP,
            ).plan(
                surface,
                PdfRect(_CONTENT_X_MM, 43.0, geometry.content_rect.width_mm, 16.0),
            ),
            Panel(
                component_id=f"{prefix}-passphrase-continuation-panel",
                stroke=_RULE,
                fill=_PANEL,
                line_width_mm=0.25,
            ).plan(surface, panel_rect),
            TextBox(
                component_id=f"{prefix}-passphrase-continuation-value",
                text=continuation_page.text,
                style=_mono_style(size_pt=6.4, bold=True, color=_INK),
                policy=TextFitPolicy.FAIL,
                line_height_multiplier=1.08,
            ).plan(surface, value_rect),
        ]
    )
    plans.extend(
        _footer_plans(
            surface,
            context,
            prefix=prefix,
            page_label=page_label,
            page_rect=geometry.page.rect,
        )
    )
    constraints = (
        SeparationConstraint(
            constraint_id=f"{prefix}-instructions-value-clearance",
            first=ComponentGroup(
                group_id=f"{prefix}-instructions",
                component_ids=(f"{prefix}-passphrase-continuation-instructions",),
            ),
            second=ComponentGroup(
                group_id=f"{prefix}-value",
                component_ids=(f"{prefix}-passphrase-continuation-panel",),
            ),
            minimum_clearance_mm=3.0,
        ),
        SeparationConstraint(
            constraint_id=f"{prefix}-value-footer-clearance",
            first=ComponentGroup(
                group_id=f"{prefix}-value-for-footer",
                component_ids=(f"{prefix}-passphrase-continuation-panel",),
            ),
            second=LayoutRegion(
                region_id=f"{prefix}-footer-zone",
                rect=PdfRect(
                    _CONTENT_X_MM,
                    geometry.footer_rule_y_mm,
                    geometry.content_rect.width_mm,
                    geometry.page.height_mm - geometry.footer_rule_y_mm,
                ),
            ),
            minimum_clearance_mm=3.0,
        ),
    )
    return build_page_plan(
        page_number=page_number,
        rect=geometry.page.rect,
        plans=plans,
        separation_constraints=constraints,
    )


def _build_single_qr_fallback_page(
    surface: PdfSurface,
    context: _ArchiveContext,
    fallback_page: _FallbackPage,
    *,
    qr_image: bytes,
    geometry: _ArchiveSingleGeometry,
    fallback_layout: _ArchiveShardFallbackLayout,
    total_pages: int,
) -> DirectPdfPagePlan:
    page_label = f"Page {fallback_page.page_number} / {total_pages}"
    normalized_doc_type = context.doc_type.strip().lower()
    component_base = (
        "archive-signing-key-shard"
        if normalized_doc_type == DOC_TYPE_SIGNING_KEY_SHARD
        else "archive-shard"
    )
    prefix = _component_prefix(component_base, fallback_page.page_number)
    plans: list[PaintPlan] = []
    plans.extend(_archive_page_background(surface, prefix=prefix, page_rect=geometry.page.rect))
    plans.extend(
        _shard_header_plans(
            surface,
            context,
            prefix=prefix,
            page_rect=geometry.page.rect,
        )
    )
    plans.extend(
        _instructions_panel_plans(
            surface,
            context,
            prefix=prefix,
            rect=PdfRect(
                geometry.content_rect.x_mm,
                39.0,
                geometry.content_rect.width_mm,
                14.0,
            ),
        )
    )
    plans.extend(
        _single_qr_plans(
            surface,
            qr_image=qr_image,
            prefix=prefix,
            frame=geometry.qr_frame,
        )
    )
    plans.extend(
        _single_fallback_plans(
            surface,
            fallback_page,
            prefix=prefix,
            area=geometry.fallback_area,
            layout=fallback_layout,
        )
    )
    plans.extend(
        _footer_plans(
            surface,
            context,
            prefix=prefix,
            page_label=page_label,
            page_rect=geometry.page.rect,
        )
    )
    constraints = (
        SeparationConstraint(
            constraint_id=f"{prefix}-qr-fallback-clearance",
            first=ComponentGroup(
                group_id=f"{prefix}-qr",
                component_ids=(f"{prefix}-qr-frame", f"{prefix}-qr-image"),
            ),
            second=LayoutRegion(
                region_id=f"{prefix}-fallback-zone",
                rect=PdfRect(
                    geometry.fallback_area.x_mm,
                    geometry.fallback_area.y_mm - 4.8,
                    geometry.fallback_area.width_mm,
                    geometry.fallback_area.height_mm + 4.8,
                ),
            ),
            minimum_clearance_mm=4.0,
        ),
        SeparationConstraint(
            constraint_id=f"{prefix}-fallback-footer-clearance",
            first=LayoutRegion(
                region_id=f"{prefix}-fallback-zone-footer-check",
                rect=geometry.fallback_area,
            ),
            second=LayoutRegion(
                region_id=f"{prefix}-footer-zone",
                rect=PdfRect(
                    geometry.content_rect.x_mm,
                    geometry.footer_rule_y_mm,
                    geometry.content_rect.width_mm,
                    geometry.page.height_mm - geometry.footer_rule_y_mm,
                ),
            ),
            minimum_clearance_mm=3.8,
        ),
    )
    return build_page_plan(
        page_number=fallback_page.page_number,
        rect=geometry.page.rect,
        plans=plans,
        separation_constraints=constraints,
    )


def _build_kit_qr_page(
    surface: PdfSurface,
    context: _ArchiveContext,
    qr_page: _QrPage,
    *,
    geometry: _ArchiveKitGeometry,
    total_pages: int,
) -> DirectPdfPagePlan:
    page_label = f"Page {qr_page.page_number} / {total_pages}"
    prefix = _component_prefix("archive-kit", qr_page.page_number)
    plans: list[PaintPlan] = []
    plans.extend(_archive_page_background(surface, prefix=prefix, page_rect=geometry.page.rect))
    plans.extend(
        _kit_header_plans(
            surface,
            context,
            prefix=prefix,
            page_label=page_label,
            page_rect=geometry.page.rect,
        )
    )
    plans.extend(
        _kit_qr_stage_plans(
            surface,
            qr_page,
            prefix=prefix,
            geometry=geometry,
        )
    )
    qr_card_ids = tuple(f"{prefix}-qr-card-{item.payload_index}" for item in qr_page.items)
    constraints = (
        SeparationConstraint(
            constraint_id=f"{prefix}-header-qr-clearance",
            first=LayoutRegion(
                region_id=f"{prefix}-header-zone",
                rect=PdfRect(0.0, 0.0, geometry.page.width_mm, 37.0),
            ),
            second=ComponentGroup(group_id=f"{prefix}-qr-grid", component_ids=qr_card_ids),
            minimum_clearance_mm=8.0,
        ),
    )
    return build_page_plan(
        page_number=qr_page.page_number,
        rect=geometry.page.rect,
        plans=plans,
        separation_constraints=constraints,
    )


def _build_kit_instruction_page(
    surface: PdfSurface,
    context: _ArchiveContext,
    *,
    geometry: _ArchiveKitGeometry,
    page_number: int,
    total_pages: int,
) -> DirectPdfPagePlan:
    prefix = _component_prefix("archive-kit", page_number)
    plans: list[PaintPlan] = []
    plans.extend(_archive_page_background(surface, prefix=prefix, page_rect=geometry.page.rect))
    plans.extend(
        _kit_instruction_plans(
            surface,
            context,
            prefix=prefix,
            geometry=geometry,
            page_label=f"PAGE {page_number} / {total_pages}",
        )
    )
    constraints = (
        SeparationConstraint(
            constraint_id=f"{prefix}-content-footer-clearance",
            first=LayoutRegion(
                region_id=f"{prefix}-instruction-content-zone",
                rect=PdfRect(
                    geometry.instruction_shell.x_mm + 7.0,
                    47.5,
                    geometry.instruction_shell.width_mm - 14.0,
                    187.5,
                ),
            ),
            second=LayoutRegion(
                region_id=f"{prefix}-instruction-footer-zone",
                rect=PdfRect(
                    geometry.instruction_shell.x_mm + 7.0,
                    geometry.instruction_footer_y_mm,
                    geometry.instruction_shell.width_mm - 14.0,
                    geometry.instruction_shell.bottom_mm - geometry.instruction_footer_y_mm,
                ),
            ),
            minimum_clearance_mm=10.0,
        ),
    )
    return build_page_plan(
        page_number=page_number,
        rect=geometry.page.rect,
        plans=plans,
        separation_constraints=constraints,
    )


def _archive_page_background(
    surface: PdfSurface,
    *,
    prefix: str,
    page_rect: PdfRect,
) -> list[PaintPlan]:
    return [
        Panel(
            component_id=f"{prefix}-page-border",
            stroke=PdfColor(229, 231, 235),
            fill=_PAPER,
            line_width_mm=0.26,
        ).plan(surface, page_rect)
    ]


def _main_header_plans(
    surface: PdfSurface,
    context: _ArchiveContext,
    *,
    prefix: str,
    page_label: str,
    page_rect: PdfRect,
) -> list[PaintPlan]:
    meta_x_mm = page_rect.right_mm - _CONTENT_X_MM - 48.2
    title_width_mm = meta_x_mm - _CONTENT_X_MM - 15.8
    return [
        TextBox(
            component_id=f"{prefix}-title",
            text=str(context.copy.get("title") or "Main Document").upper(),
            style=_display_style(size_pt=15.0, bold=True),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=12.0,
        ).plan(surface, PdfRect(_CONTENT_X_MM, 14.0, title_width_mm, 7.5)),
        Panel(
            component_id=f"{prefix}-mode-chip",
            fill=_INK,
            line_width_mm=0.2,
        ).plan(surface, PdfRect(14.0, 23.0, 9.7, 4.2)),
        TextBox(
            component_id=f"{prefix}-mode-chip-text",
            text="MODE",
            style=_mono_style(size_pt=6.0, bold=True, color=_PAPER, char_spacing_mm=0.12),
            policy=TextFitPolicy.FAIL,
            align=TextAlign.CENTER,
        ).plan(surface, PdfRect(14.6, 24.1, 8.5, 2.6)),
        TextBox(
            component_id=f"{prefix}-subtitle",
            text=str(context.copy.get("subtitle") or "Passphrase-Protected Payload").upper(),
            style=_mono_style(size_pt=6.8, bold=True, color=_INK, char_spacing_mm=0.16),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(25.0, 23.4, 102.0, 4.0)),
        *_right_meta_plans(
            surface,
            context,
            prefix=prefix,
            page_label=page_label,
            page_rect=page_rect,
        ),
    ]


def _right_meta_plans(
    surface: PdfSurface,
    context: _ArchiveContext,
    *,
    prefix: str,
    page_label: str,
    page_rect: PdfRect,
) -> list[PaintPlan]:
    rows = (
        ("PAGE", page_label),
        ("DOC ID", context.doc_id),
        ("CREATED (UTC)", context.created_timestamp_utc),
    )
    meta_x_mm = page_rect.right_mm - _CONTENT_X_MM - 48.2
    plans: list[PaintPlan] = []
    for index, (label, value) in enumerate(rows):
        y_mm = 14.5 + index * 4.7
        plans.append(
            Rule(
                component_id=f"{prefix}-meta-rule-{index}",
                color=_RULE,
            ).plan(surface, PdfRect(meta_x_mm, y_mm + 3.6, 48.2, 0.2))
        )
        plans.append(
            TextBox(
                component_id=f"{prefix}-meta-label-{index}",
                text=label,
                style=_mono_style(size_pt=6.0, bold=True, color=_MUTED, char_spacing_mm=0.1),
                policy=TextFitPolicy.FAIL,
            ).plan(surface, PdfRect(meta_x_mm, y_mm, 18.0, 3.0))
        )
        plans.append(
            TextBox(
                component_id=f"{prefix}-meta-value-{index}",
                text=value,
                style=_mono_style(
                    size_pt=6.4,
                    bold=True,
                    color=_ACCENT if index == 1 else _INK,
                ),
                policy=TextFitPolicy.SHRINK,
                min_size_pt=6.0,
                align=TextAlign.RIGHT,
            ).plan(surface, PdfRect(meta_x_mm + 18.2, y_mm, 30.0, 3.0))
        )
    return plans


def _instructions_panel_plans(
    surface: PdfSurface,
    context: _ArchiveContext,
    *,
    prefix: str,
    rect: PdfRect,
) -> list[PaintPlan]:
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-instructions-panel",
            stroke=_RULE,
            fill=_PANEL,
            line_width_mm=0.22,
        ).plan(surface, rect),
        Rule(
            component_id=f"{prefix}-instructions-accent",
            color=_ACCENT,
        ).plan(surface, PdfRect(rect.x_mm, rect.y_mm, 1.0, rect.height_mm)),
        TextBox(
            component_id=f"{prefix}-instructions-label",
            text=context.instructions_label.upper(),
            style=_mono_style(size_pt=6.2, bold=True, color=_INK, char_spacing_mm=0.1),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(rect.x_mm + 2.8, rect.y_mm + 2.0, 25.0, 4.0)),
    ]
    y_mm = rect.y_mm + 2.0
    for index, line in enumerate(context.instruction_lines):
        plans.append(
            TextBox(
                component_id=f"{prefix}-instruction-line-{index}",
                text=line,
                style=_body_style(size_pt=7.8),
                policy=TextFitPolicy.WRAP,
                line_height_multiplier=1.22,
            ).plan(surface, PdfRect(rect.x_mm + 31.0, y_mm, rect.width_mm - 34.0, 4.0))
        )
        y_mm += 4.3
    return plans


def _qr_grid_plans(
    surface: PdfSurface,
    qr_page: _QrPage,
    *,
    prefix: str,
    top_mm: float,
    card_size_mm: float,
    image_size_mm: float,
    label_prefix: str | None,
    left_mm: float = _CONTENT_X_MM,
    column_gap_mm: float = _QR_CARD_GAP_MM,
    row_gap_mm: float = _QR_CARD_GAP_MM,
    item_rects: Sequence[PdfRect] | None = None,
) -> list[PaintPlan]:
    if item_rects is not None and len(item_rects) != len(qr_page.items):
        raise ValueError("item_rects length must match QR page item count")
    plans: list[PaintPlan] = []
    for slot_index, item in enumerate(qr_page.items):
        if item_rects is None:
            row = math.floor(slot_index / _QR_COLUMNS)
            col = slot_index % _QR_COLUMNS
            rect = PdfRect(
                left_mm + col * (card_size_mm + column_gap_mm),
                top_mm + row * (card_size_mm + row_gap_mm),
                card_size_mm,
                card_size_mm,
            )
        else:
            rect = item_rects[slot_index]
        plans.extend(
            _qr_card_plans(
                surface,
                prefix=prefix,
                item=item,
                rect=rect,
                image_size_mm=image_size_mm,
                label_prefix=label_prefix,
            )
        )
    return plans


def _qr_card_plans(
    surface: PdfSurface,
    *,
    prefix: str,
    item: _QrPayloadItem,
    rect: PdfRect,
    image_size_mm: float,
    label_prefix: str | None,
) -> list[PaintPlan]:
    image_y_mm = rect.y_mm + (rect.height_mm - image_size_mm) / 2.0
    if label_prefix is not None:
        image_y_mm = max(image_y_mm, rect.y_mm + 5.2)
    if image_y_mm + image_size_mm > rect.bottom_mm - 1.0:
        image_size_mm = rect.bottom_mm - 1.0 - image_y_mm
    if image_size_mm <= 0:
        raise ValueError("QR card has no usable image area after reserving its label")
    image_rect = PdfRect(
        rect.x_mm + (rect.width_mm - image_size_mm) / 2.0,
        image_y_mm,
        image_size_mm,
        image_size_mm,
    )
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-qr-card-{item.payload_index}",
            stroke=_RULE,
            fill=_PAPER,
            line_width_mm=0.25,
        ).plan(surface, rect),
        ImageBox(
            component_id=f"{prefix}-qr-image-{item.payload_index}",
            image=item.image,
            image_type="PNG",
        ).plan(surface, image_rect),
    ]
    if label_prefix is not None:
        plans.append(
            TextBox(
                component_id=f"{prefix}-qr-label-{item.payload_index}",
                text=f"{label_prefix} {item.label_index:02d}",
                style=_mono_style(size_pt=6.2, bold=True, color=_MUTED, char_spacing_mm=0.12),
                policy=TextFitPolicy.FAIL,
                align=TextAlign.RIGHT,
            ).plan(surface, PdfRect(rect.x_mm + 2.0, rect.y_mm + 1.6, rect.width_mm - 3.0, 3.0))
        )
    return plans


def _recovery_header_plans(
    surface: PdfSurface,
    context: _ArchiveContext,
    recovery_meta: RecoveryMeta,
    *,
    prefix: str,
    geometry: _ArchiveRecoveryGeometry,
) -> list[PaintPlan]:
    page_rect = geometry.page.rect
    content_width_mm = page_rect.width_mm - 2 * _CONTENT_X_MM
    badge_x_mm = page_rect.right_mm - _CONTENT_X_MM - 22.0
    subtitle_x_mm = page_rect.right_mm - _CONTENT_X_MM - 51.0
    plans: list[PaintPlan] = [
        TextBox(
            component_id=f"{prefix}-title",
            text=str(context.copy.get("title") or "Recovery Document").upper(),
            style=_display_style(size_pt=15.2, bold=True),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=12.0,
        ).plan(surface, PdfRect(14.0, 16.0, 112.0, 7.0)),
        Rule(
            component_id=f"{prefix}-title-rule",
            color=_RULE,
        ).plan(surface, PdfRect(14.0, 24.2, 90.0, 0.25)),
        Panel(
            component_id=f"{prefix}-badge",
            fill=_ACCENT,
            line_width_mm=0.2,
        ).plan(surface, PdfRect(badge_x_mm, 14.3, 22.0, 4.0)),
        TextBox(
            component_id=f"{prefix}-badge-text",
            text="CONFIDENTIAL",
            style=_mono_style(size_pt=6.0, bold=True, color=_PAPER, char_spacing_mm=0.12),
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.CENTER,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(badge_x_mm + 1.0, 15.2, 20.0, 2.6)),
        TextBox(
            component_id=f"{prefix}-subtitle",
            text=str(context.copy.get("subtitle") or "Keys + Text Fallback").upper(),
            style=_mono_style(size_pt=6.8, bold=True, color=_INK, char_spacing_mm=0.18),
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.RIGHT,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(subtitle_x_mm, 20.4, 51.0, 4.0)),
    ]
    plans.extend(
        _recovery_meta_grid_plans(
            surface,
            context,
            recovery_meta,
            prefix=prefix,
            positions=geometry.metadata_rects,
        )
    )
    plans.append(
        Rule(component_id=f"{prefix}-header-rule", color=_RULE_DARK).plan(
            surface,
            PdfRect(
                _CONTENT_X_MM,
                geometry.header_rule_y_mm,
                content_width_mm,
                0.55,
            ),
        )
    )
    return plans


def _recovery_meta_grid_plans(
    surface: PdfSurface,
    context: _ArchiveContext,
    recovery_meta: RecoveryMeta,
    *,
    prefix: str,
    positions: Sequence[PdfRect],
) -> list[PaintPlan]:
    rows = _archive_recovery_metadata_rows(
        recovery_meta,
        doc_id=context.doc_id,
        created_timestamp_utc=context.created_timestamp_utc,
    )
    if len(positions) != len(rows):
        raise ValueError("Archive recovery metadata positions must match metadata rows")
    plans: list[PaintPlan] = []
    for index, (row, rect) in enumerate(zip(rows, positions, strict=True)):
        if not row.visible:
            continue
        value_style = _archive_recovery_metadata_value_style(row)
        value_lines = _archive_recovery_metadata_value_lines(row)
        value_y_mm = rect.y_mm + 2.7
        if row.guidance:
            guidance_style = _body_style(size_pt=6.0, color=_INK_SOFT)
            guidance_fit = fit_text_to_width(
                surface,
                row.guidance,
                guidance_style,
                max_width_mm=rect.width_mm,
                policy=TextFitPolicy.WRAP,
                line_height_multiplier=1.1,
            )
            plans.append(
                TextBox(
                    component_id=f"{prefix}-meta-guidance-{index}",
                    text=row.guidance,
                    style=guidance_style,
                    policy=TextFitPolicy.WRAP,
                    line_height_multiplier=1.1,
                ).plan(
                    surface,
                    PdfRect(
                        rect.x_mm,
                        value_y_mm,
                        rect.width_mm,
                        guidance_fit.height_mm,
                    ),
                )
            )
            value_y_mm += guidance_fit.height_mm + 1.0
        plans.append(
            TextBox(
                component_id=f"{prefix}-meta-label-{index}",
                text=row.label.upper(),
                style=_mono_style(size_pt=6.0, bold=True, color=_INK, char_spacing_mm=0.12),
                policy=TextFitPolicy.SHRINK,
                min_size_pt=6.0,
            ).plan(surface, PdfRect(rect.x_mm, rect.y_mm, rect.width_mm, 2.6))
        )
        plans.append(
            TextBox(
                component_id=f"{prefix}-meta-value-{index}",
                text="\n".join(value_lines),
                style=value_style,
                policy=(TextFitPolicy.SHRINK if row.grouped_signing_key else TextFitPolicy.WRAP),
                min_size_pt=(
                    _RECOVERY_SIGNING_KEY_MIN_SIZE_PT if row.grouped_signing_key else None
                ),
                line_height_multiplier=1.08,
            ).plan(
                surface,
                PdfRect(
                    rect.x_mm,
                    value_y_mm,
                    rect.width_mm,
                    rect.bottom_mm - value_y_mm,
                ),
            )
        )
    return plans


def _recovery_fallback_plans(
    surface: PdfSurface,
    fallback_page: _FallbackPage,
    *,
    prefix: str,
    area: PdfRect,
    content_rect: PdfRect,
    heading_y_mm: float,
) -> list[PaintPlan]:
    plans: list[PaintPlan] = [
        TextBox(
            component_id=f"{prefix}-fallback-heading",
            text="FALLBACK BLOCKS",
            style=_display_style(size_pt=7.7, bold=True, char_spacing_mm=0.08),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(content_rect.x_mm, heading_y_mm, 48.0, 4.0)),
        Rule(
            component_id=f"{prefix}-fallback-heading-rule",
            color=_RULE,
        ).plan(
            surface,
            PdfRect(
                content_rect.x_mm + 30.0,
                heading_y_mm + 2.1,
                content_rect.width_mm - 54.0,
                0.25,
            ),
        ),
        TextBox(
            component_id=f"{prefix}-fallback-manual",
            text="MANUAL",
            style=_mono_style(size_pt=6.0, bold=True, color=_INK, char_spacing_mm=0.12),
            policy=TextFitPolicy.FAIL,
            align=TextAlign.RIGHT,
        ).plan(
            surface,
            PdfRect(content_rect.right_mm - 20.0, heading_y_mm + 0.3, 19.0, 3.0),
        ),
        Panel(
            component_id=f"{prefix}-fallback-panel",
            stroke=_RULE,
            fill=_PANEL,
            line_width_mm=0.22,
        ).plan(surface, area),
    ]
    plans.extend(_fallback_entry_plans(surface, fallback_page, prefix=prefix, area=area))
    return plans


def _resolve_archive_shard_fallback(
    surface: PdfSurface,
    inputs: RenderInputs,
    *,
    area: PdfRect,
) -> tuple[_ArchiveShardFallbackLayout, tuple[_FallbackSectionLines, ...]]:
    candidates = (
        (1, _FALLBACK_ROW_HEIGHT_MM, 8.5, 6.5),
        (_SHARD_FALLBACK_COLUMNS, _SHARD_FALLBACK_ROW_HEIGHT_MM, 6.5, 6.0),
    )
    for columns, row_height_mm, body_font_size_pt, title_font_size_pt in candidates:
        column_width_mm = _shard_fallback_column_width(area, columns=columns)
        body_style = _mono_style(size_pt=body_font_size_pt, color=_INK)
        payload_width_mm = column_width_mm - 3.0 - surface.measure_text_width("99. ", body_style)
        line_length = measured_grouped_line_length(
            surface,
            style=body_style,
            alphabet=ZBASE32_ALPHABET,
            group_size=_FALLBACK_GROUP_SIZE,
            max_width_mm=payload_width_mm,
            safety_mm=_SHARD_FALLBACK_LINE_SAFETY_MM,
        )
        layout = _ArchiveShardFallbackLayout(
            columns=columns,
            row_height_mm=row_height_mm,
            line_length=line_length,
            body_font_size_pt=body_font_size_pt,
            title_font_size_pt=title_font_size_pt,
        )
        sections = _fallback_sections(
            inputs.fallback_sections or (),
            group_size=_FALLBACK_GROUP_SIZE,
            line_length=line_length,
        )
        if len(_fallback_entries(sections)) <= _shard_fallback_capacity(area, layout=layout):
            return layout, sections
    raise ValueError("Archive shard fallback payload exceeds the responsive one-page capacity")


def _shard_fallback_column_width(area: PdfRect, *, columns: int) -> float:
    if columns <= 0:
        raise ValueError("Archive shard fallback columns must be positive")
    column_width_mm = (area.width_mm - (columns - 1) * _SHARD_FALLBACK_COLUMN_GAP_MM) / columns
    if column_width_mm <= 0:
        raise ValueError("Archive shard fallback columns have no usable width")
    return column_width_mm


def _shard_fallback_capacity(
    area: PdfRect,
    *,
    layout: _ArchiveShardFallbackLayout,
) -> int:
    rows_per_column = math.floor(area.height_mm / layout.row_height_mm)
    if rows_per_column <= 0:
        raise ValueError("Archive shard fallback area must fit at least one row per column")
    return rows_per_column * layout.columns


def _visible_shard_fallback_area(
    fallback_page: _FallbackPage,
    *,
    area: PdfRect,
    layout: _ArchiveShardFallbackLayout,
) -> PdfRect:
    rows_per_column = math.floor(area.height_mm / layout.row_height_mm)
    if rows_per_column <= 0 or not fallback_page.entries:
        raise ValueError("Archive shard fallback area has no visible rows")
    visible_rows = min(rows_per_column, len(fallback_page.entries))
    visible_height_mm = visible_rows * layout.row_height_mm
    return PdfRect(
        area.x_mm,
        area.bottom_mm - visible_height_mm,
        area.width_mm,
        visible_height_mm,
    )


def _shard_fallback_entry_plans(
    surface: PdfSurface,
    fallback_page: _FallbackPage,
    *,
    prefix: str,
    area: PdfRect,
    layout: _ArchiveShardFallbackLayout,
) -> list[PaintPlan]:
    rows_per_column = math.floor(area.height_mm / layout.row_height_mm)
    column_width_mm = _shard_fallback_column_width(area, columns=layout.columns)
    if rows_per_column <= 0 or column_width_mm <= 0:
        raise ValueError("Archive shard fallback columns have no usable area")

    plans: list[PaintPlan] = []
    if layout.columns > 1:
        plans.append(
            Rule(component_id=f"{prefix}-fallback-column-rule", color=_RULE).plan(
                surface,
                PdfRect(
                    area.x_mm + column_width_mm + _SHARD_FALLBACK_COLUMN_GAP_MM / 2.0,
                    area.y_mm,
                    0.25,
                    area.height_mm,
                ),
            )
        )
    for page_entry in fallback_page.entries:
        column_index, local_row = divmod(page_entry.row_index, rows_per_column)
        if column_index >= layout.columns:
            raise ValueError("Archive shard fallback page exceeds its measured column capacity")
        column_x_mm = area.x_mm + column_index * (column_width_mm + _SHARD_FALLBACK_COLUMN_GAP_MM)
        y_mm = area.y_mm + local_row * layout.row_height_mm
        entry = page_entry.entry
        if isinstance(entry, _FallbackTitleEntry):
            plans.append(
                TextBox(
                    component_id=f"{prefix}-fallback-title-{entry.section_index}",
                    text=entry.title.upper(),
                    style=_mono_style(
                        size_pt=layout.title_font_size_pt,
                        bold=True,
                        color=_INK,
                        char_spacing_mm=0.04,
                    ),
                    policy=TextFitPolicy.SHRINK,
                    min_size_pt=6.0,
                ).plan(
                    surface,
                    PdfRect(
                        column_x_mm + 1.5,
                        y_mm,
                        column_width_mm - 3.0,
                        min(layout.row_height_mm, 3.8),
                    ),
                )
            )
            continue
        if page_entry.display_line_number is None:
            raise ValueError("fallback payload line is missing its display number")
        plans.append(
            TextBox(
                component_id=f"{prefix}-fallback-line-{entry.section_index}-{entry.line_number}",
                text=f"{page_entry.display_line_number:02d}. {entry.text}",
                style=_mono_style(size_pt=layout.body_font_size_pt, color=_INK),
                policy=TextFitPolicy.FAIL,
            ).plan(
                surface,
                PdfRect(
                    column_x_mm + 1.5,
                    y_mm,
                    column_width_mm - 3.0,
                    min(layout.row_height_mm, 3.8),
                ),
            )
        )
    return plans


def _fallback_entry_plans(
    surface: PdfSurface,
    fallback_page: _FallbackPage,
    *,
    prefix: str,
    area: PdfRect,
) -> list[PaintPlan]:
    plans: list[PaintPlan] = []
    for page_entry in fallback_page.entries:
        y_mm = area.y_mm + 2.0 + page_entry.row_index * _FALLBACK_ROW_HEIGHT_MM
        entry = page_entry.entry
        if isinstance(entry, _FallbackTitleEntry):
            plans.append(
                TextBox(
                    component_id=f"{prefix}-fallback-title-{entry.section_index}",
                    text=entry.title.upper(),
                    style=_mono_style(size_pt=6.0, bold=True, color=_INK, char_spacing_mm=0.08),
                    policy=TextFitPolicy.SHRINK,
                    min_size_pt=6.0,
                ).plan(surface, PdfRect(area.x_mm + 1.2, y_mm, area.width_mm - 2.4, 3.0))
            )
        else:
            if page_entry.display_line_number is None:
                raise ValueError("fallback payload line is missing its display number")
            plans.append(
                TextBox(
                    component_id=f"{prefix}-fallback-line-{entry.section_index}-{entry.line_number}",
                    text=f"{page_entry.display_line_number:02d}. {entry.text}",
                    style=_mono_style(size_pt=_RECOVERY_FALLBACK_BODY_SIZE_PT, color=_INK),
                    policy=TextFitPolicy.SHRINK,
                    min_size_pt=6.5,
                ).plan(
                    surface,
                    PdfRect(
                        area.x_mm + _RECOVERY_FALLBACK_LEFT_INSET_MM,
                        y_mm,
                        area.width_mm
                        - _RECOVERY_FALLBACK_LEFT_INSET_MM
                        - _RECOVERY_FALLBACK_RIGHT_INSET_MM,
                        3.2,
                    ),
                )
            )
    return plans


def _recovery_validation_plans(
    surface: PdfSurface,
    *,
    prefix: str,
    rect: PdfRect,
) -> list[PaintPlan]:
    column_gap_mm = 6.0
    column_width_mm = (rect.width_mm - column_gap_mm) / 2.0
    second_column_x_mm = rect.x_mm + column_width_mm + column_gap_mm
    return [
        Rule(
            component_id=f"{prefix}-validation-rule",
            color=_RULE_DARK,
        ).plan(surface, PdfRect(rect.x_mm, rect.y_mm, rect.width_mm, 0.25)),
        TextBox(
            component_id=f"{prefix}-security-title",
            text="SECURITY INSTRUCTIONS",
            style=_mono_style(size_pt=6.2, bold=True, color=_INK, char_spacing_mm=0.1),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(rect.x_mm, rect.y_mm + 1.5, column_width_mm, 3.0)),
        TextBox(
            component_id=f"{prefix}-security-body",
            text=(
                "- Store this document in a fireproof and waterproof location.\n"
                "- Do not photograph or store these values in cloud services.\n"
                "- Treat all recovery material as high-risk secret data."
            ),
            style=_body_style(size_pt=6.4, color=_INK),
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=1.2,
        ).plan(
            surface,
            PdfRect(rect.x_mm, rect.y_mm + 5.5, column_width_mm, rect.height_mm - 5.5),
        ),
        TextBox(
            component_id=f"{prefix}-validation-title",
            text="VALIDATION",
            style=_mono_style(size_pt=6.2, bold=True, color=_INK, char_spacing_mm=0.1),
            policy=TextFitPolicy.FAIL,
        ).plan(
            surface,
            PdfRect(second_column_x_mm, rect.y_mm + 1.5, column_width_mm, 3.0),
        ),
        TextBox(
            component_id=f"{prefix}-validation-body",
            text="- Verified by: ____________________\n- Date validated: ____ / ____ / ____",
            style=_body_style(size_pt=6.4, color=_INK),
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=1.2,
        ).plan(
            surface,
            PdfRect(
                second_column_x_mm,
                rect.y_mm + 5.5,
                column_width_mm,
                rect.height_mm - 5.5,
            ),
        ),
    ]


def _shard_header_plans(
    surface: PdfSurface,
    context: _ArchiveContext,
    *,
    prefix: str,
    page_rect: PdfRect,
) -> list[PaintPlan]:
    shard_index = _positive_int(context.values.get("shard_index"), default=1)
    shard_total = _positive_int(context.values.get("shard_total"), default=1)
    content_width_mm = page_rect.width_mm - 2 * _CONTENT_X_MM
    badge_x_mm = page_rect.right_mm - _CONTENT_X_MM - 22.0
    return [
        TextBox(
            component_id=f"{prefix}-title",
            text=str(context.copy.get("title") or "Shard Document").upper(),
            style=_display_style(size_pt=15.0, bold=True),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=11.0,
        ).plan(surface, PdfRect(14.0, 14.0, 126.0, 7.0)),
        TextBox(
            component_id=f"{prefix}-subtitle",
            text=str(context.copy.get("subtitle") or f"Shard {shard_index} of {shard_total}"),
            style=_body_style(size_pt=7.2, bold=True),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(14.0, 22.2, 92.0, 4.0)),
        Panel(
            component_id=f"{prefix}-badge",
            fill=_INK,
            line_width_mm=0.2,
        ).plan(surface, PdfRect(badge_x_mm, 14.3, 22.0, 4.8)),
        TextBox(
            component_id=f"{prefix}-badge-text",
            text=f"SHARD {shard_index} / {shard_total}",
            style=_mono_style(size_pt=6.0, bold=True, color=_PAPER, char_spacing_mm=0.1),
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.CENTER,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(badge_x_mm + 1.0, 15.5, 20.0, 2.7)),
        TextBox(
            component_id=f"{prefix}-confidential",
            text="CONFIDENTIAL",
            style=_mono_style(size_pt=6.0, bold=True, color=_MUTED, char_spacing_mm=0.12),
            policy=TextFitPolicy.FAIL,
            align=TextAlign.RIGHT,
        ).plan(surface, PdfRect(page_rect.right_mm - _CONTENT_X_MM - 28.0, 21.0, 28.0, 3.0)),
        Panel(
            component_id=f"{prefix}-meta-panel",
            stroke=_RULE,
            fill=_PANEL,
            line_width_mm=0.2,
        ).plan(surface, PdfRect(_CONTENT_X_MM, 25.0, content_width_mm, 11.0)),
        TextBox(
            component_id=f"{prefix}-doc-id-label",
            text="DOCUMENT ID",
            style=_mono_style(size_pt=6.0, bold=True, color=_INK, char_spacing_mm=0.1),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(15.4, 26.8, 48.0, 2.6)),
        TextBox(
            component_id=f"{prefix}-doc-id",
            text=context.doc_id,
            style=_mono_style(size_pt=6.2, bold=True, color=_INK),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(15.4, 30.0, 58.0, 3.0)),
        TextBox(
            component_id=f"{prefix}-created-label",
            text="CREATED (UTC)",
            style=_mono_style(size_pt=6.0, bold=True, color=_INK, char_spacing_mm=0.1),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(61.0, 26.8, 48.0, 2.6)),
        TextBox(
            component_id=f"{prefix}-created",
            text=context.created_timestamp_utc,
            style=_mono_style(size_pt=6.2, bold=True, color=_INK),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(61.0, 30.0, 58.0, 3.0)),
        Rule(
            component_id=f"{prefix}-header-rule",
            color=_RULE_DARK,
        ).plan(surface, PdfRect(_CONTENT_X_MM, 38.0, content_width_mm, 0.55)),
    ]


def _single_qr_plans(
    surface: PdfSurface,
    *,
    qr_image: bytes,
    prefix: str,
    frame: PdfRect,
) -> list[PaintPlan]:
    image_size_mm = frame.width_mm * (51.0 / 66.0)
    image = PdfRect(
        frame.x_mm + (frame.width_mm - image_size_mm) / 2.0,
        frame.y_mm + (frame.height_mm - image_size_mm) / 2.0,
        image_size_mm,
        image_size_mm,
    )
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-qr-frame",
            stroke=_INK,
            fill=_PAPER,
            line_width_mm=0.35,
        ).plan(surface, frame),
        ImageBox(
            component_id=f"{prefix}-qr-image",
            image=qr_image,
            image_type="PNG",
        ).plan(surface, image),
    ]
    plans.extend(_corner_mark_plans(surface, prefix=prefix, rect=frame))
    return plans


def _corner_mark_plans(surface: PdfSurface, *, prefix: str, rect: PdfRect) -> list[PaintPlan]:
    return [
        Rule(component_id=f"{prefix}-corner-left-top-x", color=_INK).plan(
            surface, PdfRect(rect.x_mm - 0.6, rect.y_mm - 0.6, 4.2, 0.35)
        ),
        Rule(component_id=f"{prefix}-corner-left-top-y", color=_INK).plan(
            surface, PdfRect(rect.x_mm - 0.6, rect.y_mm - 0.6, 0.35, 4.2)
        ),
        Rule(component_id=f"{prefix}-corner-right-top-x", color=_INK).plan(
            surface, PdfRect(rect.right_mm - 3.6, rect.y_mm - 0.6, 4.2, 0.35)
        ),
        Rule(component_id=f"{prefix}-corner-right-top-y", color=_INK).plan(
            surface, PdfRect(rect.right_mm + 0.25, rect.y_mm - 0.6, 0.35, 4.2)
        ),
    ]


def _single_fallback_plans(
    surface: PdfSurface,
    fallback_page: _FallbackPage,
    *,
    prefix: str,
    area: PdfRect,
    layout: _ArchiveShardFallbackLayout,
) -> list[PaintPlan]:
    visible_area = _visible_shard_fallback_area(
        fallback_page,
        area=area,
        layout=layout,
    )
    plans: list[PaintPlan] = [
        Line(
            component_id=f"{prefix}-fallback-dashed-rule",
            color=_RULE,
            line_width_mm=0.25,
        ).plan(
            surface,
            start_x_mm=visible_area.x_mm,
            start_y_mm=visible_area.y_mm - 4.8,
            end_x_mm=visible_area.right_mm,
            end_y_mm=visible_area.y_mm - 4.8,
        ),
        TextBox(
            component_id=f"{prefix}-fallback-heading",
            text="RAW TEXT FALLBACK",
            style=_mono_style(size_pt=6.1, bold=True, color=_INK, char_spacing_mm=0.1),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(visible_area.x_mm, visible_area.y_mm - 2.8, 58.0, 3.0)),
        TextBox(
            component_id=f"{prefix}-fallback-helper",
            text="USE IF QR IS UNREADABLE",
            style=_mono_style(size_pt=6.0, color=_MUTED_SOFT, char_spacing_mm=0.1),
            policy=TextFitPolicy.FAIL,
            align=TextAlign.RIGHT,
        ).plan(
            surface,
            PdfRect(visible_area.right_mm - 60.0, visible_area.y_mm - 2.8, 60.0, 3.0),
        ),
        Panel(
            component_id=f"{prefix}-fallback-panel",
            stroke=_RULE,
            fill=_PANEL,
            line_width_mm=0.2,
        ).plan(surface, visible_area),
    ]
    plans.extend(
        _shard_fallback_entry_plans(
            surface,
            fallback_page,
            prefix=prefix,
            area=visible_area,
            layout=layout,
        )
    )
    return plans


def _kit_header_plans(
    surface: PdfSurface,
    context: _ArchiveContext,
    *,
    prefix: str,
    page_label: str,
    page_rect: PdfRect,
) -> list[PaintPlan]:
    content_width_mm = page_rect.width_mm - 2 * _CONTENT_X_MM
    lock_x_mm = page_rect.right_mm - _CONTENT_X_MM - 8.0
    return [
        TextBox(
            component_id=f"{prefix}-title",
            text=str(context.copy.get("title") or "Recovery Kit").upper(),
            style=_display_style(size_pt=15.0, bold=True),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=12.0,
        ).plan(surface, PdfRect(14.0, 14.0, 105.0, 7.0)),
        TextBox(
            component_id=f"{prefix}-subtitle",
            text=str(context.copy.get("subtitle") or "Standalone Offline HTML Bundle").upper(),
            style=_mono_style(size_pt=7.0, bold=True, color=_INK, char_spacing_mm=0.12),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(14.0, 23.0, 110.0, 4.0)),
        Panel(
            component_id=f"{prefix}-lock",
            stroke=_RULE,
            fill=PdfColor(243, 244, 246),
            line_width_mm=0.24,
        ).plan(surface, PdfRect(lock_x_mm, 14.0, 8.0, 8.0)),
        TextBox(
            component_id=f"{prefix}-lock-icon",
            text=_ICON_LOCK,
            style=_symbol_style(size_pt=17.5, color=_MUTED_SOFT),
            policy=TextFitPolicy.FAIL,
            align=TextAlign.CENTER,
            line_height_multiplier=1.0,
        ).plan(surface, PdfRect(lock_x_mm + 0.6, 14.9, 6.8, 6.5)),
        *_kit_meta_plans(
            surface,
            context,
            prefix=prefix,
            page_label=page_label,
            content_rect=PdfRect(_CONTENT_X_MM, 0.0, content_width_mm, page_rect.height_mm),
        ),
        Rule(
            component_id=f"{prefix}-header-rule",
            color=_RULE_DARK,
        ).plan(surface, PdfRect(_CONTENT_X_MM, 36.5, content_width_mm, 0.55)),
    ]


def _kit_meta_plans(
    surface: PdfSurface,
    context: _ArchiveContext,
    *,
    prefix: str,
    page_label: str,
    content_rect: PdfRect,
) -> list[PaintPlan]:
    column_gap_mm = 4.0
    column_width_mm = (content_rect.width_mm - 2 * column_gap_mm) / 3.0
    rows = (
        (
            "DOCUMENT ID",
            context.doc_id,
            TextAlign.LEFT,
            PdfRect(content_rect.x_mm, 28.0, column_width_mm, 6.0),
        ),
        (
            "CREATED (UTC)",
            context.created_timestamp_utc,
            TextAlign.CENTER,
            PdfRect(
                content_rect.x_mm + column_width_mm + column_gap_mm,
                28.0,
                column_width_mm,
                6.0,
            ),
        ),
        (
            "PAGE",
            page_label,
            TextAlign.RIGHT,
            PdfRect(
                content_rect.right_mm - column_width_mm,
                28.0,
                column_width_mm,
                6.0,
            ),
        ),
    )
    plans: list[PaintPlan] = []
    for index, (label, value, align, rect) in enumerate(rows):
        plans.append(
            TextBox(
                component_id=f"{prefix}-kit-meta-label-{index}",
                text=label,
                style=_mono_style(size_pt=6.0, bold=True, color=_INK, char_spacing_mm=0.1),
                policy=TextFitPolicy.FAIL,
                align=align,
            ).plan(surface, PdfRect(rect.x_mm, rect.y_mm, rect.width_mm, 2.6))
        )
        plans.append(
            TextBox(
                component_id=f"{prefix}-kit-meta-value-{index}",
                text=value,
                style=_mono_style(size_pt=6.4, bold=True, color=_INK),
                policy=TextFitPolicy.SHRINK,
                align=align,
                min_size_pt=6.0,
            ).plan(surface, PdfRect(rect.x_mm, rect.y_mm + 2.8, rect.width_mm, 3.0))
        )
    return plans


def _kit_qr_stage_plans(
    surface: PdfSurface,
    qr_page: _QrPage,
    *,
    prefix: str,
    geometry: _ArchiveKitGeometry,
) -> list[PaintPlan]:
    item_rects = geometry.qr_grid.item_rects(len(qr_page.items))
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-kit-stage",
            stroke=_RULE,
            fill=_PANEL,
            line_width_mm=0.2,
        ).plan(
            surface,
            PdfRect(geometry.content_rect.x_mm, 39.0, geometry.content_rect.width_mm, 66.5),
        ),
        Panel(
            component_id=f"{prefix}-kit-step-index",
            fill=PdfColor(219, 234, 254),
            line_width_mm=0.2,
        ).plan(surface, PdfRect(16.0, 41.0, 4.8, 4.8)),
        TextBox(
            component_id=f"{prefix}-kit-step-index-text",
            text=str(qr_page.page_number),
            style=_mono_style(size_pt=6.2, bold=True, color=_ACCENT),
            policy=TextFitPolicy.FAIL,
            align=TextAlign.CENTER,
        ).plan(surface, PdfRect(16.3, 42.1, 4.2, 2.8)),
        TextBox(
            component_id=f"{prefix}-kit-step-title",
            text="RECOVERY KIT PAYLOAD",
            style=_mono_style(size_pt=7.1, bold=True, color=_ACCENT, char_spacing_mm=0.12),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(22.0, 42.0, 70.0, 3.5)),
    ]
    plans.extend(
        _qr_grid_plans(
            surface,
            qr_page,
            prefix=prefix,
            top_mm=45.8,
            card_size_mm=geometry.qr_grid.item_width_mm,
            image_size_mm=(
                geometry.qr_grid.item_width_mm * (_KIT_QR_IMAGE_SIZE_MM / _KIT_QR_CARD_SIZE_MM)
            ),
            label_prefix="PART",
            item_rects=item_rects,
        )
    )
    return plans


def _kit_instruction_plans(
    surface: PdfSurface,
    context: _ArchiveContext,
    *,
    prefix: str,
    geometry: _ArchiveKitGeometry,
    page_label: str,
) -> list[PaintPlan]:
    shell = geometry.instruction_shell
    inner_x_mm = shell.x_mm + 7.0
    inner_width_mm = shell.width_mm - 14.0
    column_gap_mm = 5.0
    column_width_mm = (inner_width_mm - column_gap_mm) / 2.0
    right_column_x_mm = inner_x_mm + column_width_mm + column_gap_mm
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-instruction-shell",
            stroke=PdfColor(226, 232, 240),
            fill=_PANEL,
            line_width_mm=0.45,
        ).plan(surface, shell),
        TextBox(
            component_id=f"{prefix}-instruction-title",
            text="HOW TO REBUILD THE RECOVERY KIT",
            style=TextStyle(family="Times", size_pt=20.0, style="B", color=_INK),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=16.0,
        ).plan(surface, PdfRect(inner_x_mm, 22.0, inner_width_mm - 2.0, 10.0)),
        TextBox(
            component_id=f"{prefix}-instruction-subtitle",
            text="Use this page after scanning the QR pages. Keep everything offline.",
            style=_body_style(size_pt=10.6, color=_INK),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=8.2,
        ).plan(surface, PdfRect(inner_x_mm, 34.7, inner_width_mm - 8.0, 5.5)),
        Rule(
            component_id=f"{prefix}-instruction-rule",
            color=PdfColor(203, 213, 225),
        ).plan(surface, PdfRect(inner_x_mm, 41.8, inner_width_mm, 0.35)),
    ]
    plans.extend(
        _instruction_section_plans(
            surface,
            prefix=prefix,
            title="Scan + Assemble",
            icon=_ICON_HUB,
            lines=(
                "Scan every QR code left to right, top to bottom.",
                "Save each decoded chunk in order. Do not insert spaces or blank lines.",
                "Concatenate the chunks into one continuous file.",
                "Name the file exactly: recovery_kit.bundle.html",
            ),
            rect=PdfRect(inner_x_mm, 47.5, column_width_mm, 50.0),
            index=1,
        )
    )
    plans.extend(
        _instruction_section_plans(
            surface,
            prefix=prefix,
            title="Open the Kit",
            icon=_ICON_LANGUAGE,
            lines=(
                "Open recovery_kit.bundle.html in a browser while offline.",
                "If the file is large, wait for it to finish loading.",
                "Follow the on-screen prompts to recover your payload.",
            ),
            rect=PdfRect(inner_x_mm, 107.0, column_width_mm, 42.0),
            index=2,
        )
    )
    plans.extend(
        _instruction_section_plans(
            surface,
            prefix=prefix,
            title="Troubleshooting",
            icon=_ICON_BUILD,
            lines=(
                "If the kit does not load, re-check chunk order and re-save the file.",
                "Try another browser if rendering stalls.",
                "Confirm the file size matches the sum of all QR chunks.",
            ),
            rect=PdfRect(inner_x_mm, 157.0, column_width_mm, 48.0),
            index=3,
            bullet_icon="disc",
        )
    )
    plans.extend(
        _instruction_right_column_plans(
            surface,
            context,
            prefix=prefix,
            x_mm=right_column_x_mm,
            width_mm=column_width_mm,
        )
    )
    plans.extend(
        _instruction_footer_plans(
            surface,
            context,
            prefix=prefix,
            page_label=page_label,
            rect=PdfRect(
                inner_x_mm,
                geometry.instruction_footer_y_mm,
                inner_width_mm,
                shell.bottom_mm - geometry.instruction_footer_y_mm,
            ),
        )
    )
    return plans


def _instruction_section_plans(
    surface: PdfSurface,
    *,
    prefix: str,
    title: str,
    icon: str,
    lines: Sequence[str],
    rect: PdfRect,
    index: int,
    bullet_icon: str = "adjust",
) -> list[PaintPlan]:
    plans: list[PaintPlan] = _instruction_badge_plans(
        surface,
        prefix=prefix,
        title=title,
        icon=icon,
        rect=PdfRect(rect.x_mm, rect.y_mm, min(rect.width_mm, 23.0 + len(title) * 1.55), 8.6),
        index=index,
    )
    y_mm = rect.y_mm + 14.0
    for line_index, line in enumerate(lines):
        if bullet_icon == "disc":
            plans.append(
                Ellipse(
                    component_id=f"{prefix}-instruction-disc-{index}-{line_index}",
                    fill=_INK,
                    line_width_mm=0.18,
                ).plan(surface, PdfRect(rect.x_mm + 1.0, y_mm + 3.1, 0.9, 0.9))
            )
        else:
            plans.append(
                TextBox(
                    component_id=f"{prefix}-instruction-bullet-{index}-{line_index}",
                    text=_ICON_ADJUST,
                    style=_symbol_style(size_pt=14.0, color=_INK),
                    policy=TextFitPolicy.FAIL,
                    line_height_multiplier=1.0,
                ).plan(surface, PdfRect(rect.x_mm, y_mm, 6.0, 6.0))
            )
        text_plan = TextBox(
            component_id=f"{prefix}-instruction-line-{index}-{line_index}",
            text=line,
            style=_body_style(size_pt=10.0),
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=1.16,
        ).plan(surface, PdfRect(rect.x_mm + 8.5, y_mm - 0.2, rect.width_mm - 8.5, 12.0))
        plans.append(text_plan)
        y_mm += max(8.9, text_plan.proof.used_rect.height_mm + 2.1)
    return plans


def _instruction_badge_plans(
    surface: PdfSurface,
    *,
    prefix: str,
    title: str,
    icon: str,
    rect: PdfRect,
    index: int,
) -> list[PaintPlan]:
    return [
        Panel(
            component_id=f"{prefix}-instruction-badge-{index}",
            stroke=_INK,
            fill=None,
            line_width_mm=0.25,
        ).plan(surface, rect),
        TextBox(
            component_id=f"{prefix}-instruction-badge-icon-{index}",
            text=icon,
            style=_symbol_style(size_pt=14.0, color=_INK),
            policy=TextFitPolicy.FAIL,
            line_height_multiplier=1.0,
        ).plan(surface, PdfRect(rect.x_mm + 2.4, rect.y_mm + 1.4, 6.0, 6.0)),
        TextBox(
            component_id=f"{prefix}-instruction-badge-text-{index}",
            text=title.upper(),
            style=_body_style(size_pt=7.6, bold=True, char_spacing_mm=0.16),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.2,
        ).plan(surface, PdfRect(rect.x_mm + 10.8, rect.y_mm + 2.6, rect.width_mm - 13.0, 3.4)),
    ]


def _instruction_right_column_plans(
    surface: PdfSurface,
    context: _ArchiveContext,
    *,
    prefix: str,
    x_mm: float,
    width_mm: float,
) -> list[PaintPlan]:
    plans: list[PaintPlan] = []
    cards = (
        (
            "Verify",
            (
                "Confirm the kit loads and shows the Recovery Kit home screen.",
                "If it fails to open, re-check the order and re-save the file.",
            ),
            PdfRect(x_mm, 47.5, width_mm, 34.0),
        ),
        (
            "Storage",
            (
                "Keep the QR pages and the bundle file in separate locations.",
                "Store the bundle on a write-protected drive if possible.",
            ),
            PdfRect(x_mm, 85.0, width_mm, 34.0),
        ),
        (
            "Security",
            (
                "Work offline and on a trusted machine.",
                "Delete temporary files after successful recovery.",
            ),
            PdfRect(x_mm, 123.0, width_mm, 32.0),
        ),
    )
    for index, (title, paragraphs, rect) in enumerate(cards):
        plans.extend(_instruction_info_card_plans(surface, prefix, title, paragraphs, rect, index))
    plans.extend(
        _instruction_checklist_plans(
            surface,
            context,
            prefix=prefix,
            rect=PdfRect(x_mm, 159.0, width_mm, 76.0),
        )
    )
    return plans


def _instruction_info_card_plans(
    surface: PdfSurface,
    prefix: str,
    title: str,
    paragraphs: Sequence[str],
    rect: PdfRect,
    index: int,
) -> list[PaintPlan]:
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-info-card-{index}",
            stroke=PdfColor(203, 213, 225),
            fill=_PAPER,
            line_width_mm=0.22,
        ).plan(surface, rect),
        TextBox(
            component_id=f"{prefix}-info-title-{index}",
            text=title.upper(),
            style=_body_style(size_pt=7.4, bold=True, char_spacing_mm=0.16),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(rect.x_mm + 3.3, rect.y_mm + 4.0, rect.width_mm - 6.6, 3.8)),
    ]
    y_mm = rect.y_mm + 12.0
    for paragraph_index, paragraph in enumerate(paragraphs):
        text_plan = TextBox(
            component_id=f"{prefix}-info-body-{index}-{paragraph_index}",
            text=paragraph,
            style=_body_style(size_pt=10.0 if paragraph_index == 0 else 9.3),
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=1.16,
        ).plan(surface, PdfRect(rect.x_mm + 3.3, y_mm, rect.width_mm - 6.6, 12.0))
        plans.append(text_plan)
        y_mm += max(8.4, text_plan.proof.used_rect.height_mm + 1.8)
    return plans


def _instruction_checklist_plans(
    surface: PdfSurface,
    context: _ArchiveContext,
    *,
    prefix: str,
    rect: PdfRect,
) -> list[PaintPlan]:
    checklist_lines = (
        *tuple(context.instruction_lines),
        "Start at the top-left and follow each row.",
        "Recovery completed and data verified.",
    )
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-checklist-card",
            stroke=PdfColor(203, 213, 225),
            fill=_PAPER,
            line_width_mm=0.22,
        ).plan(surface, rect),
        TextBox(
            component_id=f"{prefix}-checklist-icon",
            text=_ICON_VERIFIED_USER,
            style=_symbol_style(size_pt=15.0, color=_INK),
            policy=TextFitPolicy.FAIL,
            line_height_multiplier=1.0,
        ).plan(surface, PdfRect(rect.x_mm + 3.2, rect.y_mm + 4.0, 6.0, 6.0)),
        TextBox(
            component_id=f"{prefix}-checklist-title",
            text=str(
                context.copy.get("checklist_label") or "Security Verification Checklist"
            ).upper(),
            style=_body_style(size_pt=7.3, bold=True, char_spacing_mm=0.14),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(rect.x_mm + 10.5, rect.y_mm + 5.0, rect.width_mm - 14.0, 4.0)),
    ]
    y_mm = rect.y_mm + 15.0
    for line_index, line in enumerate(checklist_lines):
        plans.append(
            TextBox(
                component_id=f"{prefix}-checklist-box-{line_index}",
                text=_ICON_CHECK_BOX,
                style=_symbol_style(size_pt=14.5, color=_INK),
                policy=TextFitPolicy.FAIL,
                line_height_multiplier=1.0,
            ).plan(surface, PdfRect(rect.x_mm + 3.8, y_mm, 6.0, 6.0))
        )
        text_plan = TextBox(
            component_id=f"{prefix}-checklist-line-{line_index}",
            text=line,
            style=_body_style(size_pt=9.4),
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=1.08,
        ).plan(surface, PdfRect(rect.x_mm + 12.0, y_mm, rect.width_mm - 16.0, 11.0))
        plans.append(text_plan)
        y_mm += max(8.0, text_plan.proof.used_rect.height_mm + 1.7)
    return plans


def _instruction_footer_plans(
    surface: PdfSurface,
    context: _ArchiveContext,
    *,
    prefix: str,
    page_label: str,
    rect: PdfRect,
) -> list[PaintPlan]:
    page_width_mm = 34.0
    side_width_mm = (rect.width_mm - page_width_mm - 8.0) / 2.0
    return [
        Rule(
            component_id=f"{prefix}-instruction-footer-rule",
            color=PdfColor(203, 213, 225),
        ).plan(surface, PdfRect(rect.x_mm, rect.y_mm, rect.width_mm, 0.25)),
        TextBox(
            component_id=f"{prefix}-instruction-footer-kind",
            text="RECOVERY KIT: OFFLINE HTML BUNDLE",
            style=_body_style(size_pt=7.4, color=_INK, char_spacing_mm=0.16),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(rect.x_mm, rect.y_mm + 5.0, side_width_mm, 4.0)),
        TextBox(
            component_id=f"{prefix}-instruction-footer-page",
            text=page_label,
            style=_mono_style(size_pt=6.5, color=_MUTED, char_spacing_mm=0.1),
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.CENTER,
            min_size_pt=6.0,
        ).plan(
            surface,
            PdfRect(
                rect.x_mm + side_width_mm + 4.0,
                rect.y_mm + 5.0,
                page_width_mm,
                4.0,
            ),
        ),
        TextBox(
            component_id=f"{prefix}-instruction-footer-doc-id",
            text=f"DOCUMENT ID: {context.doc_id}",
            style=_mono_style(size_pt=6.5, color=_INK, char_spacing_mm=0.1),
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.RIGHT,
            min_size_pt=6.0,
        ).plan(
            surface,
            PdfRect(
                rect.right_mm - side_width_mm,
                rect.y_mm + 5.0,
                side_width_mm,
                4.0,
            ),
        ),
    ]


def _footer_plans(
    surface: PdfSurface,
    context: _ArchiveContext,
    *,
    prefix: str,
    page_label: str,
    page_rect: PdfRect,
) -> list[PaintPlan]:
    footer_rule_y_mm = page_rect.height_mm - _FOOTER_BOTTOM_INSET_MM
    footer_dot_y_mm = footer_rule_y_mm + 2.4
    footer_text_y_mm = footer_rule_y_mm + 2.2
    return [
        Rule(
            component_id=f"{prefix}-footer-rule",
            color=_RULE_DARK,
        ).plan(
            surface,
            PdfRect(
                _CONTENT_X_MM,
                footer_rule_y_mm,
                page_rect.width_mm - 2 * _CONTENT_X_MM,
                0.25,
            ),
        ),
        Ellipse(
            component_id=f"{prefix}-footer-dot",
            fill=_ACCENT,
            line_width_mm=0.18,
        ).plan(surface, PdfRect(_CONTENT_X_MM, footer_dot_y_mm, 1.8, 1.8)),
        TextBox(
            component_id=f"{prefix}-footer-left",
            text=context.footer_left.upper(),
            style=_mono_style(size_pt=6.1, color=_MUTED_SOFT, char_spacing_mm=0.12),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(_CONTENT_X_MM + 3.2, footer_text_y_mm, 70.0, 3.5)),
        TextBox(
            component_id=f"{prefix}-footer-page",
            text=page_label.upper().replace("PAGE", "PAGE"),
            style=_mono_style(size_pt=6.0, color=_MUTED, char_spacing_mm=0.12),
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.RIGHT,
            min_size_pt=6.0,
        ).plan(
            surface,
            PdfRect(page_rect.right_mm - _CONTENT_X_MM - 46.0, footer_text_y_mm, 46.0, 3.5),
        ),
    ]


def _display_style(
    *,
    size_pt: float,
    bold: bool = False,
    color: PdfColor = _INK,
    char_spacing_mm: float = 0.0,
) -> TextStyle:
    return TextStyle(
        family="Helvetica",
        size_pt=size_pt,
        style="B" if bold else "",
        color=color,
        char_spacing_mm=char_spacing_mm,
    )


def _body_style(
    *,
    size_pt: float,
    bold: bool = False,
    color: PdfColor = _INK,
    char_spacing_mm: float = 0.0,
) -> TextStyle:
    return TextStyle(
        family="Helvetica",
        size_pt=size_pt,
        style="B" if bold else "",
        color=color,
        char_spacing_mm=char_spacing_mm,
    )


def _mono_style(
    *,
    size_pt: float,
    color: PdfColor,
    bold: bool = False,
    char_spacing_mm: float = 0.0,
) -> TextStyle:
    return TextStyle(
        family="Courier",
        size_pt=size_pt,
        style="B" if bold else "",
        color=color,
        char_spacing_mm=char_spacing_mm,
    )


def _symbol_style(*, size_pt: float, color: PdfColor) -> TextStyle:
    return TextStyle(family=MATERIAL_SYMBOLS_FAMILY, size_pt=size_pt, color=color)


__all__ = [
    "ArchiveDirectPlan",
    "build_archive_kit_direct_plan",
    "build_archive_main_direct_plan",
    "build_archive_recovery_direct_plan",
    "build_archive_shard_direct_plan",
    "build_archive_signing_key_shard_direct_plan",
    "render_archive_kit_direct_pdf",
    "render_archive_main_direct_pdf",
    "render_archive_recovery_direct_pdf",
    "render_archive_shard_direct_pdf",
    "render_archive_signing_key_shard_direct_pdf",
]
