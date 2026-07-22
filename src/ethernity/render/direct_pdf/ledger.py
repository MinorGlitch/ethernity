"""Ledger design rendering through direct PDF primitives."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import Enum

from ethernity.encoding.zbase32 import ZBASE32_ALPHABET
from ethernity.qr.codec import QrConfig
from ethernity.render.direct_pdf.classic_common import (
    ClassicInstructionStyle,
    ClassicLayout,
    ClassicPageStyle,
    ClassicQrGridStyle,
    body_text_style,
    build_group_clearance_constraint,
    build_instruction_bullets_section,
    build_instruction_checklist,
    build_instruction_steps_section,
    build_page_background,
    group_fallback_visual_blocks,
    monospace_text_style,
    resolve_classic_layout,
    resolve_qr_grid,
    title_text_style,
)
from ethernity.render.direct_pdf.components import (
    ImageBox,
    Panel,
    Rule,
    TextAlign,
    TextBox,
)
from ethernity.render.direct_pdf.fallback_layout import (
    FallbackPage,
    FallbackPageEntry,
    FallbackSectionLines,
    FallbackTitleEntry,
    ResponsiveFallbackPageProfile,
    ResponsiveFallbackSpec,
    build_fallback_proof,
    fallback_capacity,
    fallback_entries,
    fallback_sections,
    measured_fallback_number_width,
    paginate_fallback_entries,
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
    QrPage,
    QrPayloadItem,
    StructuredContext,
    StructuredDirectPlan as LedgerDirectPlan,
    StructuredPlanBuilder,
    build_artifact_proof,
    build_structured_context,
    component_prefix,
    paginate_qr_items,
    positive_int,
    qr_image,
    qr_payload_items,
    render_structured_plan,
    resolved_qr_payloads,
    resolved_single_qr_payload,
    validate_qr_inputs,
    validate_recovery_inputs,
    validate_single_qr_fallback_inputs,
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
from ethernity.render.recovery_meta import RecoveryMeta, recovery_passphrase_display
from ethernity.render.types import RenderInputs, RenderResult

_MARGIN_MM = 14.0
_INK = PdfColor(11, 26, 38)
_INK_SOFT = PdfColor(81, 98, 114)
_INK_LABEL = PdfColor(59, 78, 92)
_INK_MUTED = PdfColor(47, 67, 82)
_INK_BODY = PdfColor(26, 39, 51)
_ACCENT = PdfColor(43, 63, 70)
_SURFACE_BORDER = PdfColor(187, 174, 156)
_PAPER = PdfColor(251, 246, 239)
_WHITE = PdfColor(255, 255, 255)
_SURFACE = PdfColor(247, 241, 231)
_RULE = PdfColor(210, 196, 179)
_RULE_STRONG = PdfColor(159, 139, 114)
_NOTE = PdfColor(239, 228, 212)
_TAB = PdfColor(228, 211, 190)
_INSTRUCTIONS_FILL = PdfColor(248, 243, 235)
_QR_COLUMNS = 3
_QR_ROWS_PER_PAGE = 3
_QR_CARD_SIZE_MM = 58.0
_QR_CARD_GAP_MM = 3.0
_QR_IMAGE_SIZE_MM = 56.2
_QR_LABEL_BAND_HEIGHT_MM = 5.2
_MIN_QR_CARD_SIZE_MM = 48.0
_MIN_QR_IMAGE_SIZE_MM = 42.0
_KIT_QR_ROWS_PER_PAGE = 3
_FALLBACK_GROUP_SIZE = 4
_FALLBACK_ROW_HEIGHT_MM = 4.2
_RECOVERY_FALLBACK_BODY_SIZE_PT = 8.5
_RECOVERY_FALLBACK_NUMBER_SIZE_PT = 6.6
_RECOVERY_FALLBACK_NUMBER_CHAR_SPACING_MM = 0.08
_RECOVERY_FALLBACK_LEFT_INSET_MM = 3.4
_RECOVERY_FALLBACK_RIGHT_INSET_MM = 4.0
_RECOVERY_FALLBACK_NUMBER_GAP_MM = 2.6
_RECOVERY_FALLBACK_NUMBER_MIN_WIDTH_MM = 7.0
_RECOVERY_FALLBACK_NUMBER_PADDING_MM = 0.4
_RECOVERY_FALLBACK_LINE_SAFETY_MM = 0.2
_SHARD_FALLBACK_COLUMNS = 2
_SHARD_FALLBACK_COLUMN_GAP_MM = 4.0
_SHARD_FALLBACK_ROW_HEIGHT_MM = 2.9
_SHARD_FALLBACK_HEIGHT_MM = 116.0
_SHARD_FALLBACK_LINE_SAFETY_MM = 0.2
_CONTENT_BOTTOM_INSET_MM = 7.0
_META_WIDTH_MM = 72.0
_PASSPHRASE_META_WIDTH_MM = 81.0
_PAGE_STYLE = ClassicPageStyle(
    margin_mm=_MARGIN_MM,
    content_bottom_inset_mm=_CONTENT_BOTTOM_INSET_MM,
)
_QR_GRID_STYLE = ClassicQrGridStyle(
    max_columns=_QR_COLUMNS,
    preferred_card_size_mm=_QR_CARD_SIZE_MM,
    minimum_card_size_mm=_MIN_QR_CARD_SIZE_MM,
    gap_mm=_QR_CARD_GAP_MM,
)
_INSTRUCTION_STYLE = ClassicInstructionStyle(
    ink=_INK,
    rule=_RULE,
    strong_rule=_RULE_STRONG,
    tab=_TAB,
    white=_WHITE,
    section_accent=_ACCENT,
    section_fill=PdfColor(239, 234, 224),
)


@dataclass(frozen=True)
class _HeaderLayout:
    plans: tuple[PaintPlan, ...]
    after_divider_y_mm: float


class _HeaderMetaKind(str, Enum):
    STANDARD = "standard"
    PASSPHRASE = "passphrase"
    CREATED = "created"


@dataclass(frozen=True)
class _HeaderMetaRow:
    label: str
    value: str
    kind: _HeaderMetaKind = _HeaderMetaKind.STANDARD
    guidance: str = ""


@dataclass(frozen=True)
class _LedgerShardFallbackLayout:
    columns: int
    row_height_mm: float
    line_length: int
    body_font_size_pt: float
    title_font_size_pt: float


def _body_zone_constraints(
    *,
    prefix: str,
    header_plans: Sequence[PaintPlan],
    content_plans: Sequence[PaintPlan],
    layout: ClassicLayout,
    header_clearance_mm: float = 2.0,
    footer_clearance_mm: float = 3.0,
) -> tuple[SeparationConstraint, ...]:
    if not header_plans or not content_plans:
        raise ValueError("Ledger body constraints require header and content plans")
    header_group = ComponentGroup(
        group_id=f"{prefix}-header-content",
        component_ids=tuple(plan.component_id for plan in header_plans),
    )
    group = ComponentGroup(
        group_id=f"{prefix}-body-content",
        component_ids=tuple(plan.component_id for plan in content_plans),
    )
    return (
        SeparationConstraint(
            constraint_id=f"{prefix}-header-clearance",
            first=header_group,
            second=group,
            minimum_clearance_mm=header_clearance_mm,
        ),
        SeparationConstraint(
            constraint_id=f"{prefix}-footer-clearance",
            first=group,
            second=LayoutRegion(
                region_id=f"{prefix}-footer-zone",
                rect=layout.regions.footer,
            ),
            minimum_clearance_mm=footer_clearance_mm,
        ),
    )


def render_ledger_main_direct_pdf(inputs: RenderInputs) -> RenderResult:
    """Render a Ledger main document directly to PDF."""

    return _render_ledger_plan(inputs, build_ledger_main_direct_plan)


def render_ledger_recovery_direct_pdf(inputs: RenderInputs) -> RenderResult:
    """Render a Ledger recovery document directly to PDF."""

    return _render_ledger_plan(inputs, build_ledger_recovery_direct_plan)


def render_ledger_shard_direct_pdf(inputs: RenderInputs) -> RenderResult:
    """Render a Ledger shard document directly to PDF."""

    return _render_ledger_plan(inputs, build_ledger_shard_direct_plan)


def render_ledger_signing_key_shard_direct_pdf(inputs: RenderInputs) -> RenderResult:
    """Render a Ledger signing-key shard document directly to PDF."""

    return _render_ledger_plan(inputs, build_ledger_signing_key_shard_direct_plan)


def render_ledger_kit_direct_pdf(inputs: RenderInputs) -> RenderResult:
    """Render a Ledger recovery-kit document directly to PDF."""

    return _render_ledger_plan(inputs, build_ledger_kit_direct_plan)


def _render_ledger_plan(inputs: RenderInputs, builder: StructuredPlanBuilder) -> RenderResult:
    return render_structured_plan(inputs, style_name="ledger", builder=builder)


def build_ledger_main_direct_plan(surface: PdfSurface, inputs: RenderInputs) -> LedgerDirectPlan:
    """Build measured Ledger main-document pages and proof."""

    layout = resolve_classic_layout(inputs, style=_PAGE_STYLE)
    validate_qr_inputs(
        inputs,
        expected_doc_type=DOC_TYPE_MAIN,
    )
    payloads = resolved_qr_payloads(inputs)
    items = qr_payload_items(payloads, config=inputs.qr_config or QrConfig())
    context = build_structured_context(inputs, doc_type=DOC_TYPE_MAIN)
    first_page_grid = resolve_qr_grid(
        layout,
        top_mm=_qr_page_top_mm(surface, context, layout, include_instructions=True),
        preferred_rows=_QR_ROWS_PER_PAGE,
        style=_QR_GRID_STYLE,
    )
    continuation_grid = resolve_qr_grid(
        layout,
        top_mm=_qr_page_top_mm(surface, context, layout, include_instructions=False),
        preferred_rows=_QR_ROWS_PER_PAGE,
        style=_QR_GRID_STYLE,
    )
    qr_pages = paginate_qr_items(
        items,
        capacity=continuation_grid.capacity,
        first_page_capacity=first_page_grid.capacity,
    )
    page_plans = tuple(
        _build_qr_page(
            surface,
            context,
            qr_page,
            layout=layout,
            grid=first_page_grid if qr_page.page_number == 1 else continuation_grid,
            component_base="ledger-main",
            total_pages=len(qr_pages),
            include_instructions=qr_page.page_number == 1,
            label_prefix="Segment",
            label_total=len(items),
        )
        for qr_page in qr_pages
    )
    artifact_proof = build_artifact_proof(
        inputs,
        qr_payloads=payloads,
        encoded_payload_count=len(payloads),
        physical_qr_count=len(items),
        physical_qr_payload_indexes=tuple(item.payload_index for item in items),
        page_count=len(page_plans),
        fallback_proof=None,
    )
    return LedgerDirectPlan(page_plans=page_plans, artifact_proof=artifact_proof)


def build_ledger_recovery_direct_plan(
    surface: PdfSurface,
    inputs: RenderInputs,
) -> LedgerDirectPlan:
    """Build measured Ledger recovery-document pages and proof."""

    layout = resolve_classic_layout(inputs, style=_PAGE_STYLE)
    validate_recovery_inputs(inputs)
    recovery_meta = inputs.recovery_meta or RecoveryMeta()
    context = build_structured_context(inputs, doc_type=DOC_TYPE_RECOVERY)
    passphrase_pagination = _paginate_ledger_passphrase(surface, recovery_meta, layout=layout)
    fallback_area = _recovery_fallback_area(
        surface,
        context,
        passphrase_pagination.inline_meta,
        layout,
    )
    overflow_meta = replace(
        passphrase_pagination.inline_meta,
        passphrase=None,
        passphrase_lines=(),
        passphrase_instructions="",
    )
    continuation_fallback_area = (
        _recovery_fallback_area(surface, context, overflow_meta, layout)
        if passphrase_pagination.continuation_pages
        else fallback_area
    )
    fallback_spec = ResponsiveFallbackSpec(
        group_size=_FALLBACK_GROUP_SIZE,
        row_height_mm=_FALLBACK_ROW_HEIGHT_MM,
        body_style=monospace_text_style(
            size_pt=_RECOVERY_FALLBACK_BODY_SIZE_PT,
            color=_INK,
        ),
        number_style=monospace_text_style(
            size_pt=_RECOVERY_FALLBACK_NUMBER_SIZE_PT,
            color=_INK_SOFT,
            char_spacing_mm=_RECOVERY_FALLBACK_NUMBER_CHAR_SPACING_MM,
        ),
        content_left_inset_mm=_RECOVERY_FALLBACK_LEFT_INSET_MM,
        content_right_inset_mm=_RECOVERY_FALLBACK_RIGHT_INSET_MM,
        vertical_reserved_mm=0.0,
        number_gap_mm=_RECOVERY_FALLBACK_NUMBER_GAP_MM,
        number_minimum_width_mm=_RECOVERY_FALLBACK_NUMBER_MIN_WIDTH_MM,
        number_padding_mm=_RECOVERY_FALLBACK_NUMBER_PADDING_MM,
        safety_mm=_RECOVERY_FALLBACK_LINE_SAFETY_MM,
    )
    fallback_pagination = resolve_responsive_fallback_pagination(
        surface,
        inputs.fallback_sections or (),
        first_profile=ResponsiveFallbackPageProfile(
            area=fallback_area,
            spec=fallback_spec,
        ),
        continuation_profile=ResponsiveFallbackPageProfile(
            area=continuation_fallback_area,
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
            layout=layout,
            fallback_area=(
                fallback_area
                if fallback_page.page_number == 1 or not passphrase_pagination.continuation_pages
                else continuation_fallback_area
            ),
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
    fallback_proof = build_fallback_proof(inputs, sections, fallback_pages)
    artifact_proof = build_artifact_proof(
        inputs,
        qr_payloads=(),
        encoded_payload_count=len(inputs.qr_payloads or inputs.frames),
        physical_qr_count=0,
        physical_qr_payload_indexes=(),
        page_count=len(page_plans),
        fallback_proof=fallback_proof,
    )
    return LedgerDirectPlan(
        page_plans=page_plans,
        artifact_proof=artifact_proof,
        fallback_proof=fallback_proof,
    )


def _paginate_ledger_passphrase(
    surface: PdfSurface,
    recovery_meta: RecoveryMeta,
    *,
    layout: ClassicLayout,
) -> RecoveryPassphrasePagination:
    style = monospace_text_style(size_pt=6.7, color=_INK, char_spacing_mm=0.05)
    guidance_style = body_text_style(size_pt=6.0, color=_INK_MUTED)
    value_rect = _passphrase_continuation_value_rect(layout)
    return paginate_recovery_passphrase(
        surface,
        recovery_meta,
        style=style,
        guidance_style=guidance_style,
        max_width_mm=_PASSPHRASE_META_WIDTH_MM - 4.0,
        inline_height_mm=4.0 * surface.line_height(style, multiplier=1.12),
        continuation_height_mm=value_rect.height_mm,
        line_height_multiplier=1.12,
    )


def _passphrase_continuation_value_rect(layout: ClassicLayout) -> PdfRect:
    top_mm = layout.safe_rect.y_mm + 57.0
    bottom_mm = layout.content_rect.bottom_mm - 4.0
    if bottom_mm <= top_mm:
        raise ValueError("Ledger page has zero-capacity passphrase continuation area")
    width_mm = _PASSPHRASE_META_WIDTH_MM - 4.0
    return PdfRect(
        layout.safe_rect.x_mm + (layout.safe_rect.width_mm - width_mm) / 2.0,
        top_mm,
        width_mm,
        bottom_mm - top_mm,
    )


def build_ledger_shard_direct_plan(surface: PdfSurface, inputs: RenderInputs) -> LedgerDirectPlan:
    """Build measured Ledger shard-document pages and proof."""

    return _build_ledger_single_qr_fallback_plan(
        surface,
        inputs,
        expected_doc_type=DOC_TYPE_SHARD,
    )


def build_ledger_signing_key_shard_direct_plan(
    surface: PdfSurface,
    inputs: RenderInputs,
) -> LedgerDirectPlan:
    """Build measured Ledger signing-key shard pages and proof."""

    return _build_ledger_single_qr_fallback_plan(
        surface,
        inputs,
        expected_doc_type=DOC_TYPE_SIGNING_KEY_SHARD,
    )


def build_ledger_kit_direct_plan(surface: PdfSurface, inputs: RenderInputs) -> LedgerDirectPlan:
    """Build measured Ledger recovery-kit pages and proof."""

    layout = resolve_classic_layout(inputs, style=_PAGE_STYLE)
    validate_qr_inputs(
        inputs,
        expected_doc_type=DOC_TYPE_KIT,
    )
    payloads = resolved_qr_payloads(inputs)
    items = qr_payload_items(payloads, config=inputs.qr_config or QrConfig())
    context = build_structured_context(inputs, doc_type=DOC_TYPE_KIT)
    grid = resolve_qr_grid(
        layout,
        top_mm=_qr_page_top_mm(surface, context, layout, include_instructions=False),
        preferred_rows=_KIT_QR_ROWS_PER_PAGE,
        style=_QR_GRID_STYLE,
    )
    qr_pages = paginate_qr_items(items, capacity=grid.capacity)
    total_pages = len(qr_pages) + 1
    page_plans = tuple(
        _build_qr_page(
            surface,
            context,
            qr_page,
            layout=layout,
            grid=grid,
            component_base="ledger-kit",
            total_pages=total_pages,
            include_instructions=False,
            label_prefix="Part",
            label_total=len(items),
        )
        for qr_page in qr_pages
    )
    page_plans = (
        *page_plans,
        _build_kit_instruction_page(
            surface,
            context,
            layout=layout,
            page_number=total_pages,
            total_pages=total_pages,
        ),
    )
    artifact_proof = build_artifact_proof(
        inputs,
        qr_payloads=payloads,
        encoded_payload_count=len(payloads),
        physical_qr_count=len(items),
        physical_qr_payload_indexes=tuple(item.payload_index for item in items),
        page_count=len(page_plans),
        fallback_proof=None,
    )
    return LedgerDirectPlan(page_plans=page_plans, artifact_proof=artifact_proof)


def _build_ledger_single_qr_fallback_plan(
    surface: PdfSurface,
    inputs: RenderInputs,
    *,
    expected_doc_type: str,
) -> LedgerDirectPlan:
    layout = resolve_classic_layout(inputs, style=_PAGE_STYLE)
    validate_single_qr_fallback_inputs(
        inputs,
        expected_doc_type=expected_doc_type,
    )
    payload = resolved_single_qr_payload(inputs)
    rendered_qr = qr_image(payload, config=inputs.qr_config or QrConfig())
    context = build_structured_context(inputs, doc_type=expected_doc_type)
    qr_rect, fallback_area = _shard_content_areas(surface, context, layout)
    fallback_layout, sections = _resolve_ledger_shard_fallback(
        surface,
        inputs,
        area=fallback_area,
    )
    fallback_pages = paginate_fallback_entries(
        fallback_entries(sections),
        capacity=_shard_fallback_capacity(fallback_area, layout=fallback_layout),
    )
    page_plans = tuple(
        _build_shard_page(
            surface,
            context,
            fallback_page,
            layout=layout,
            qr_image_bytes=rendered_qr,
            qr_rect=qr_rect,
            fallback_area=fallback_area,
            fallback_layout=fallback_layout,
            total_pages=len(fallback_pages),
        )
        for fallback_page in fallback_pages
    )
    fallback_proof = build_fallback_proof(inputs, sections, fallback_pages)
    artifact_proof = build_artifact_proof(
        inputs,
        qr_payloads=(payload,),
        encoded_payload_count=1,
        physical_qr_count=len(page_plans),
        physical_qr_payload_indexes=tuple(0 for _ in page_plans),
        page_count=len(page_plans),
        fallback_proof=fallback_proof,
    )
    return LedgerDirectPlan(
        page_plans=page_plans,
        artifact_proof=artifact_proof,
        fallback_proof=fallback_proof,
    )


def _qr_page_top_mm(
    surface: PdfSurface,
    context: StructuredContext,
    layout: ClassicLayout,
    *,
    include_instructions: bool,
) -> float:
    header = _header_layout(
        surface,
        context,
        layout=layout,
        prefix="ledger-measure",
        page_label="Page 1 / 1",
    )
    if not include_instructions:
        return header.after_divider_y_mm + 4.0
    return header.after_divider_y_mm + _instructions_height(context) + 6.8


def _recovery_fallback_area(
    surface: PdfSurface,
    context: StructuredContext,
    recovery_meta: RecoveryMeta,
    layout: ClassicLayout,
) -> PdfRect:
    header = _header_layout(
        surface,
        context,
        layout=layout,
        prefix="ledger-recovery-measure",
        page_label="Page 1 / 1",
        rows=_recovery_meta_rows(context, recovery_meta),
    )
    instructions = PdfRect(
        layout.safe_rect.x_mm,
        header.after_divider_y_mm + 2.4,
        layout.safe_rect.width_mm,
        17.0,
    )
    top_mm = max(layout.safe_rect.y_mm + 66.0, instructions.bottom_mm + 2.0)
    height_mm = layout.content_rect.bottom_mm - top_mm
    area = PdfRect(layout.safe_rect.x_mm, top_mm, layout.safe_rect.width_mm, height_mm)
    fallback_capacity(area, row_height_mm=_FALLBACK_ROW_HEIGHT_MM)
    return area


def _shard_content_areas(
    surface: PdfSurface,
    context: StructuredContext,
    layout: ClassicLayout,
) -> tuple[PdfRect, PdfRect]:
    header = _header_layout(
        surface,
        context,
        layout=layout,
        prefix="ledger-shard-measure",
        page_label="Page 1 / 1",
        rows=(
            _HeaderMetaRow(
                "Shard",
                f"{positive_int(context.values.get('shard_index'), default=1)} / "
                f"{positive_int(context.values.get('shard_total'), default=1)}",
            ),
            _HeaderMetaRow(
                "Created (UTC)",
                context.created_timestamp_utc,
                _HeaderMetaKind.CREATED,
            ),
        ),
    )
    instructions = PdfRect(
        layout.safe_rect.x_mm,
        header.after_divider_y_mm + 2.4,
        layout.safe_rect.width_mm,
        17.5,
    )
    qr_top_mm = instructions.bottom_mm + 5.5
    fallback_height_mm = _SHARD_FALLBACK_HEIGHT_MM
    fallback_area = PdfRect(
        layout.safe_rect.x_mm,
        layout.content_rect.bottom_mm - fallback_height_mm,
        layout.safe_rect.width_mm,
        fallback_height_mm,
    )
    qr_grid = resolve_grid(
        PdfRect(
            layout.safe_rect.x_mm,
            qr_top_mm,
            layout.safe_rect.width_mm,
            fallback_area.y_mm - 8.0 - qr_top_mm,
        ),
        GridPolicy(
            max_columns=1,
            max_rows=1,
            preferred_item_width_mm=_QR_CARD_SIZE_MM,
            preferred_item_height_mm=_QR_CARD_SIZE_MM,
            minimum_item_width_mm=_MIN_QR_CARD_SIZE_MM,
            minimum_item_height_mm=_MIN_QR_CARD_SIZE_MM,
            preserve_item_aspect_ratio=True,
            horizontal_distribution="center",
            vertical_distribution="start",
        ),
    )
    qr_rect = qr_grid.item_rects(1)[0]
    return qr_rect, fallback_area


def _build_qr_page(
    surface: PdfSurface,
    context: StructuredContext,
    qr_page: QrPage,
    *,
    layout: ClassicLayout,
    grid: ResolvedGrid,
    component_base: str,
    total_pages: int,
    include_instructions: bool,
    label_prefix: str,
    label_total: int,
) -> DirectPdfPagePlan:
    prefix = component_prefix(component_base, qr_page.page_number)
    page_label = f"Page {qr_page.page_number} / {total_pages}"
    plans: list[PaintPlan] = []
    plans.extend(build_page_background(surface, layout=layout, prefix=prefix, fill=_PAPER))
    header = _header_layout(
        surface,
        context,
        layout=layout,
        prefix=prefix,
        page_label=page_label,
    )
    header_plans = list(header.plans)
    plans.extend(header_plans)
    if include_instructions:
        instructions_height = _instructions_height(context)
        instruction_plans = _instructions_plans(
            surface,
            context,
            prefix=prefix,
            rect=PdfRect(
                layout.safe_rect.x_mm,
                header.after_divider_y_mm + 2.4,
                layout.safe_rect.width_mm,
                instructions_height,
            ),
        )
        header_plans.extend(instruction_plans)
        plans.extend(instruction_plans)
    qr_plans = _qr_grid_plans(
        surface,
        qr_page,
        grid=grid,
        prefix=prefix,
        label_prefix=label_prefix,
        label_total=label_total,
    )
    plans.extend(qr_plans)
    return build_page_plan(
        page_number=qr_page.page_number,
        rect=layout.page.rect,
        plans=plans,
        separation_constraints=_body_zone_constraints(
            prefix=prefix,
            header_plans=header_plans,
            content_plans=qr_plans,
            layout=layout,
        ),
    )


def _build_recovery_page(
    surface: PdfSurface,
    context: StructuredContext,
    recovery_meta: RecoveryMeta,
    fallback_page: FallbackPage,
    *,
    layout: ClassicLayout,
    fallback_area: PdfRect,
    total_pages: int,
) -> DirectPdfPagePlan:
    prefix = component_prefix("ledger-recovery", fallback_page.page_number)
    page_label = f"Page {fallback_page.page_number} / {total_pages}"
    plans: list[PaintPlan] = []
    plans.extend(build_page_background(surface, layout=layout, prefix=prefix, fill=_PAPER))
    header = _header_layout(
        surface,
        context,
        layout=layout,
        prefix=prefix,
        page_label=page_label,
        rows=_recovery_meta_rows(context, recovery_meta),
    )
    header_plans = list(header.plans)
    instruction_plans = _instructions_plans(
        surface,
        context,
        prefix=prefix,
        rect=PdfRect(
            layout.safe_rect.x_mm,
            header.after_divider_y_mm + 2.4,
            layout.safe_rect.width_mm,
            17.0,
        ),
    )
    header_plans.extend(instruction_plans)
    plans.extend(header_plans)
    fallback_plans = _fallback_block_plans(
        surface,
        fallback_page,
        prefix=prefix,
        area=fallback_area,
    )
    plans.extend(fallback_plans)
    return build_page_plan(
        page_number=fallback_page.page_number,
        rect=layout.page.rect,
        plans=plans,
        separation_constraints=_body_zone_constraints(
            prefix=prefix,
            header_plans=header_plans,
            content_plans=fallback_plans,
            layout=layout,
        ),
    )


def _build_passphrase_continuation_page(
    surface: PdfSurface,
    context: StructuredContext,
    *,
    layout: ClassicLayout,
    continuation_page: RecoveryPassphraseContinuationPage,
    page_number: int,
    total_pages: int,
) -> DirectPdfPagePlan:
    prefix = component_prefix("ledger-recovery", page_number)
    page_label = f"Page {page_number} / {total_pages}"
    plans: list[PaintPlan] = []
    plans.extend(build_page_background(surface, layout=layout, prefix=prefix, fill=_PAPER))
    header = _header_layout(
        surface,
        context,
        layout=layout,
        prefix=prefix,
        page_label=page_label,
    )
    header_plans = list(header.plans)
    plans.extend(header_plans)
    value_rect = _passphrase_continuation_value_rect(layout)
    panel_rect = PdfRect(
        value_rect.x_mm - 2.0,
        value_rect.y_mm - 2.0,
        value_rect.width_mm + 4.0,
        value_rect.height_mm + 4.0,
    )
    content_plans: list[PaintPlan] = [
        TextBox(
            component_id=f"{prefix}-passphrase-continuation-title",
            text=(
                "PASSPHRASE CONTINUATION "
                f"{continuation_page.page_index} / {continuation_page.total_pages}"
            ),
            style=title_text_style(
                size_pt=11.0,
                color=_ACCENT,
                char_spacing_mm=0.18,
            ),
            policy=TextFitPolicy.FAIL,
        ).plan(
            surface,
            PdfRect(
                layout.safe_rect.x_mm,
                header.after_divider_y_mm + 4.0,
                layout.safe_rect.width_mm,
                5.0,
            ),
        ),
        TextBox(
            component_id=f"{prefix}-passphrase-continuation-instructions",
            text=continuation_page.instructions,
            style=body_text_style(size_pt=7.8, color=_INK_BODY),
            policy=TextFitPolicy.WRAP,
        ).plan(
            surface,
            PdfRect(
                layout.safe_rect.x_mm,
                header.after_divider_y_mm + 11.0,
                layout.safe_rect.width_mm,
                15.0,
            ),
        ),
        Panel(
            component_id=f"{prefix}-passphrase-continuation-panel",
            stroke=_SURFACE_BORDER,
            fill=_WHITE,
            line_width_mm=0.3,
        ).plan(surface, panel_rect),
        TextBox(
            component_id=f"{prefix}-passphrase-continuation-value",
            text=continuation_page.text,
            style=monospace_text_style(size_pt=6.7, color=_INK, char_spacing_mm=0.05),
            policy=TextFitPolicy.FAIL,
            line_height_multiplier=1.12,
        ).plan(surface, value_rect),
    ]
    plans.extend(content_plans)
    return build_page_plan(
        page_number=page_number,
        rect=layout.page.rect,
        plans=plans,
        separation_constraints=_body_zone_constraints(
            prefix=prefix,
            header_plans=header_plans,
            content_plans=content_plans,
            layout=layout,
        ),
    )


def _build_shard_page(
    surface: PdfSurface,
    context: StructuredContext,
    fallback_page: FallbackPage,
    *,
    layout: ClassicLayout,
    qr_image_bytes: bytes,
    qr_rect: PdfRect,
    fallback_area: PdfRect,
    fallback_layout: _LedgerShardFallbackLayout,
    total_pages: int,
) -> DirectPdfPagePlan:
    normalized_doc_type = context.doc_type.strip().lower()
    component_base = (
        "ledger-signing-key-shard"
        if normalized_doc_type == DOC_TYPE_SIGNING_KEY_SHARD
        else "ledger-shard"
    )
    prefix = component_prefix(component_base, fallback_page.page_number)
    page_label = f"Page {fallback_page.page_number} / {total_pages}"
    shard_index = positive_int(context.values.get("shard_index"), default=1)
    shard_total = positive_int(context.values.get("shard_total"), default=1)
    plans: list[PaintPlan] = []
    plans.extend(build_page_background(surface, layout=layout, prefix=prefix, fill=_PAPER))
    header = _header_layout(
        surface,
        context,
        layout=layout,
        prefix=prefix,
        page_label=page_label,
        rows=(
            _HeaderMetaRow("Shard", f"{shard_index} / {shard_total}"),
            _HeaderMetaRow(
                "Created (UTC)",
                context.created_timestamp_utc,
                _HeaderMetaKind.CREATED,
            ),
        ),
    )
    header_plans = list(header.plans)
    instruction_plans = _instructions_plans(
        surface,
        context,
        prefix=prefix,
        rect=PdfRect(
            layout.safe_rect.x_mm,
            header.after_divider_y_mm + 2.4,
            layout.safe_rect.width_mm,
            17.5,
        ),
    )
    header_plans.extend(instruction_plans)
    plans.extend(header_plans)
    qr_plans = _single_qr_plans(
        surface,
        qr_image_bytes=qr_image_bytes,
        prefix=prefix,
        rect=qr_rect,
    )
    fallback_plans = _shard_fallback_block_plans(
        surface,
        fallback_page,
        prefix=prefix,
        area=fallback_area,
        layout=fallback_layout,
    )
    plans.extend(qr_plans)
    plans.extend(fallback_plans)
    return build_page_plan(
        page_number=fallback_page.page_number,
        rect=layout.page.rect,
        plans=plans,
        separation_constraints=(
            *_body_zone_constraints(
                prefix=prefix,
                header_plans=header_plans,
                content_plans=(*qr_plans, *fallback_plans),
                layout=layout,
            ),
            build_group_clearance_constraint(
                prefix=prefix,
                first_group_id="qr-content",
                first_plans=qr_plans,
                second_group_id="fallback-content",
                second_plans=fallback_plans,
                clearance_mm=8.0,
            ),
        ),
    )


def _build_kit_instruction_page(
    surface: PdfSurface,
    context: StructuredContext,
    *,
    layout: ClassicLayout,
    page_number: int,
    total_pages: int,
) -> DirectPdfPagePlan:
    prefix = component_prefix("ledger-kit", page_number)
    plans: list[PaintPlan] = []
    plans.extend(build_page_background(surface, layout=layout, prefix=prefix, fill=_PAPER))
    insert_plans = _instruction_insert_plans(
        surface,
        context,
        prefix=prefix,
        rect=layout.safe_rect,
        page_label=f"Page {page_number} / {total_pages}",
    )
    plans.extend(insert_plans)
    body_plans = tuple(
        plan
        for plan in insert_plans
        if "-insert-footer-" not in plan.component_id
        and not plan.component_id.endswith(("-insert-shell", "-insert-inner-rule"))
    )
    footer_plans = tuple(plan for plan in insert_plans if "-insert-footer-" in plan.component_id)
    return build_page_plan(
        page_number=page_number,
        rect=layout.page.rect,
        plans=plans,
        separation_constraints=(
            build_group_clearance_constraint(
                prefix=prefix,
                first_group_id="insert-body",
                first_plans=body_plans,
                second_group_id="insert-footer",
                second_plans=footer_plans,
                clearance_mm=3.0,
            ),
        ),
    )


def _header_layout(
    surface: PdfSurface,
    context: StructuredContext,
    *,
    layout: ClassicLayout,
    prefix: str,
    page_label: str,
    rows: Sequence[_HeaderMetaRow] = (),
) -> _HeaderLayout:
    meta_rows = (
        _HeaderMetaRow("Page", page_label),
        _HeaderMetaRow("Document ID", context.doc_id),
        *rows,
    )
    if not rows or rows[-1].kind is not _HeaderMetaKind.CREATED:
        meta_rows = (
            *meta_rows,
            _HeaderMetaRow(
                "Created (UTC)",
                context.created_timestamp_utc,
                _HeaderMetaKind.CREATED,
            ),
        )

    safe_rect = layout.safe_rect
    meta_w = (
        _PASSPHRASE_META_WIDTH_MM
        if any(row.kind is _HeaderMetaKind.PASSPHRASE for row in rows)
        else _META_WIDTH_MM
    )
    meta_x = safe_rect.right_mm - meta_w
    title_width = meta_x - safe_rect.x_mm - 11.0
    if title_width <= 0:
        raise ValueError("Ledger page safe area cannot fit the header columns")
    plans: list[PaintPlan] = [
        TextBox(
            component_id=f"{prefix}-title",
            text=str(context.copy.get("title") or "Document").upper(),
            style=title_text_style(size_pt=18.0, color=_INK, char_spacing_mm=0.18),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=13.0,
        ).plan(surface, PdfRect(safe_rect.x_mm, 14.4, title_width, 8.5)),
        TextBox(
            component_id=f"{prefix}-subtitle",
            text=str(context.copy.get("subtitle") or "").upper(),
            style=body_text_style(size_pt=9.0, color=_INK_MUTED, char_spacing_mm=0.16),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.6,
        ).plan(surface, PdfRect(safe_rect.x_mm, 24.6, title_width + 2.0, 4.5)),
    ]
    row_gap = 1.2
    meta_y = 14.0
    cursor_y = meta_y
    for index, row in enumerate(meta_rows):
        label = row.label
        value = row.value
        is_primary = index == 0
        is_passphrase = row.kind is _HeaderMetaKind.PASSPHRASE
        if is_primary:
            text = value.upper()
        else:
            text = f"{label}: {value}"
        text_style = (
            monospace_text_style(
                size_pt=7.0,
                bold=True,
                color=_ACCENT,
                char_spacing_mm=0.1,
            )
            if is_primary
            else monospace_text_style(size_pt=6.7, color=_INK, char_spacing_mm=0.05)
        )
        label_style = monospace_text_style(size_pt=6.2, bold=True, color=_INK_LABEL)
        guidance_style = body_text_style(size_pt=6.0, color=_INK_MUTED)
        label_height_mm = 0.0
        guidance_height_mm = 0.0
        if is_passphrase:
            label_height_mm = surface.line_height(label_style, multiplier=1.0)
            if row.guidance:
                guidance_height_mm = (
                    fit_text_to_width(
                        surface,
                        row.guidance,
                        guidance_style,
                        max_width_mm=meta_w - 4.0,
                        policy=TextFitPolicy.WRAP,
                        line_height_multiplier=1.1,
                    ).height_mm
                    + 0.8
                )
            value_fit = fit_text_to_width(
                surface,
                value,
                text_style,
                max_width_mm=meta_w - 4.0,
                policy=TextFitPolicy.WRAP,
                line_height_multiplier=1.12,
            )
            row_h = max(
                5.5,
                1.0 + label_height_mm + guidance_height_mm + value_fit.height_mm + 1.0,
            )
        else:
            row_h = _meta_row_height(
                surface,
                text,
                style=text_style,
                max_width_mm=meta_w - 4.0,
            )
        plans.append(
            Panel(
                component_id=f"{prefix}-meta-box-{index}",
                stroke=_ACCENT if is_primary else _SURFACE_BORDER,
                fill=_WHITE,
                line_width_mm=0.35,
            ).plan(surface, PdfRect(meta_x, cursor_y, meta_w, row_h))
        )
        if is_passphrase:
            content_y_mm = cursor_y + 1.0
            plans.append(
                TextBox(
                    component_id=f"{prefix}-meta-passphrase-label-{index}",
                    text=label,
                    style=label_style,
                    policy=TextFitPolicy.FAIL,
                    align=TextAlign.RIGHT,
                    line_height_multiplier=1.0,
                ).plan(
                    surface,
                    PdfRect(meta_x + 2.0, content_y_mm, meta_w - 4.0, label_height_mm),
                )
            )
            content_y_mm += label_height_mm
            if row.guidance:
                plans.append(
                    TextBox(
                        component_id=f"{prefix}-meta-guidance-{index}",
                        text=row.guidance,
                        style=guidance_style,
                        policy=TextFitPolicy.WRAP,
                        align=TextAlign.RIGHT,
                        line_height_multiplier=1.1,
                    ).plan(
                        surface,
                        PdfRect(
                            meta_x + 2.0,
                            content_y_mm,
                            meta_w - 4.0,
                            guidance_height_mm - 0.8,
                        ),
                    )
                )
                content_y_mm += guidance_height_mm
            plans.append(
                TextBox(
                    component_id=f"{prefix}-meta-text-{index}",
                    text=value,
                    style=text_style,
                    policy=TextFitPolicy.WRAP,
                    align=TextAlign.RIGHT,
                    line_height_multiplier=1.12,
                ).plan(
                    surface,
                    PdfRect(
                        meta_x + 2.0,
                        content_y_mm,
                        meta_w - 4.0,
                        cursor_y + row_h - 0.8 - content_y_mm,
                    ),
                )
            )
        else:
            plans.append(
                TextBox(
                    component_id=f"{prefix}-meta-text-{index}",
                    text=text,
                    style=text_style,
                    policy=TextFitPolicy.SHRINK if is_primary else TextFitPolicy.WRAP,
                    align=TextAlign.RIGHT,
                    min_size_pt=6.0,
                    line_height_multiplier=1.12,
                ).plan(
                    surface,
                    PdfRect(meta_x + 2.0, cursor_y + 1.0, meta_w - 4.0, row_h - 1.8),
                )
            )
        cursor_y += row_h + row_gap

    meta_bottom = cursor_y - row_gap
    divider_y = max(33.5, meta_bottom + 2.4)
    plans.append(
        Rule(component_id=f"{prefix}-divider", color=_ACCENT).plan(
            surface,
            PdfRect(safe_rect.x_mm, divider_y, safe_rect.width_mm, 0.6),
        )
    )
    return _HeaderLayout(plans=tuple(plans), after_divider_y_mm=divider_y + 0.6)


def _meta_row_height(
    surface: PdfSurface,
    text: str,
    *,
    style: TextStyle,
    max_width_mm: float,
) -> float:
    fit = fit_text_to_width(
        surface,
        text,
        style,
        max_width_mm=max_width_mm,
        policy=TextFitPolicy.WRAP,
        line_height_multiplier=1.12,
    )
    return max(5.5, fit.height_mm + 1.8)


def _recovery_meta_rows(
    context: StructuredContext,
    recovery_meta: RecoveryMeta,
) -> tuple[_HeaderMetaRow, ...]:
    rows: list[_HeaderMetaRow] = []
    if recovery_meta.quorum_value:
        rows.append(
            _HeaderMetaRow(
                recovery_meta.quorum_label or "Shard Quorum",
                recovery_meta.quorum_value,
            )
        )
    if recovery_meta.signing_pub_lines:
        rows.append(_HeaderMetaRow("Signing Pub Key", " ".join(recovery_meta.signing_pub_lines)))
    passphrase = recovery_passphrase_display(recovery_meta)
    if passphrase.value_lines:
        rows.append(
            _HeaderMetaRow(
                passphrase.label,
                "\n".join(passphrase.value_lines),
                _HeaderMetaKind.PASSPHRASE,
                passphrase.guidance,
            )
        )
    rows.append(
        _HeaderMetaRow(
            "Created (UTC)",
            context.created_timestamp_utc,
            _HeaderMetaKind.CREATED,
        )
    )
    return tuple(rows)


def _instructions_height(context: StructuredContext) -> float:
    return max(14.5, 7.0 + len(context.instruction_lines) * 4.3)


def _instructions_plans(
    surface: PdfSurface,
    context: StructuredContext,
    *,
    prefix: str,
    rect: PdfRect,
) -> list[PaintPlan]:
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-instructions-shell",
            stroke=_SURFACE_BORDER,
            fill=_INSTRUCTIONS_FILL,
            line_width_mm=0.35,
        ).plan(surface, rect),
        Rule(component_id=f"{prefix}-instructions-rail", color=_ACCENT).plan(
            surface,
            PdfRect(rect.x_mm, rect.y_mm, 1.2, rect.height_mm),
        ),
        TextBox(
            component_id=f"{prefix}-instructions-label",
            text=context.instructions_label.upper(),
            style=title_text_style(
                size_pt=7.0,
                color=_INK_LABEL,
                char_spacing_mm=0.22,
            ),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(rect.x_mm + 3.0, rect.y_mm + 2.0, 26.5, 4.2)),
    ]
    y_mm = rect.y_mm + 2.0
    for index, line in enumerate(context.instruction_lines):
        plans.append(
            TextBox(
                component_id=f"{prefix}-instruction-line-{index}",
                text=line,
                style=body_text_style(size_pt=8.7, color=_INK_BODY),
                policy=TextFitPolicy.WRAP,
                line_height_multiplier=1.16,
            ).plan(surface, PdfRect(rect.x_mm + 35.0, y_mm, rect.width_mm - 39.0, 4.5))
        )
        y_mm += 4.3
    return plans


def _qr_grid_plans(
    surface: PdfSurface,
    qr_page: QrPage,
    *,
    grid: ResolvedGrid,
    prefix: str,
    label_prefix: str,
    label_total: int,
) -> list[PaintPlan]:
    plans: list[PaintPlan] = []
    rects = grid.item_rects(len(qr_page.items))
    for item, rect in zip(qr_page.items, rects, strict=True):
        plans.extend(
            _qr_card_plans(
                surface,
                item,
                prefix=prefix,
                rect=rect,
                label_prefix=label_prefix,
                label_total=label_total,
            )
        )
    return plans


def _single_qr_plans(
    surface: PdfSurface,
    *,
    qr_image_bytes: bytes,
    prefix: str,
    rect: PdfRect,
) -> list[PaintPlan]:
    return _qr_card_plans(
        surface,
        QrPayloadItem(payload_index=0, payload=b"", image=qr_image_bytes),
        prefix=prefix,
        rect=rect,
        label_prefix=None,
        label_total=None,
    )


def _qr_card_plans(
    surface: PdfSurface,
    item: QrPayloadItem,
    *,
    prefix: str,
    rect: PdfRect,
    label_prefix: str | None,
    label_total: int | None,
) -> list[PaintPlan]:
    label_height = _QR_LABEL_BAND_HEIGHT_MM if label_prefix else 0.0
    image_area_height = rect.height_mm - label_height
    image_size = min(_QR_IMAGE_SIZE_MM, rect.width_mm - 1.2, image_area_height - 1.2)
    if image_size < _MIN_QR_IMAGE_SIZE_MM:
        raise ValueError("Ledger QR card cannot preserve the readable QR image minimum")
    image_rect = PdfRect(
        rect.x_mm + (rect.width_mm - image_size) / 2.0,
        rect.y_mm + label_height + (image_area_height - image_size) / 2.0,
        image_size,
        image_size,
    )
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-qr-card-{item.payload_index}",
            stroke=_SURFACE_BORDER,
            fill=_WHITE,
            line_width_mm=0.35,
        ).plan(surface, rect),
        ImageBox(
            component_id=f"{prefix}-qr-image-{item.payload_index}",
            image=item.image,
            image_type="PNG",
        ).plan(surface, image_rect),
    ]
    if label_prefix:
        if label_total is None or label_total <= 0:
            raise ValueError("Ledger QR card label total must be positive")
        plans.append(
            TextBox(
                component_id=f"{prefix}-qr-label-{item.payload_index}",
                text=(f"{label_prefix} {item.label_index:02d} / {label_total:02d}").upper(),
                style=monospace_text_style(
                    size_pt=6.7,
                    bold=True,
                    color=_ACCENT,
                    char_spacing_mm=0.08,
                ),
                policy=TextFitPolicy.SHRINK,
                align=TextAlign.CENTER,
                min_size_pt=6.0,
            ).plan(
                surface,
                PdfRect(rect.x_mm + 2.0, rect.y_mm + 1.0, rect.width_mm - 4.0, 3.4),
            )
        )
    return plans


def _fallback_block_plans(
    surface: PdfSurface,
    fallback_page: FallbackPage,
    *,
    prefix: str,
    area: PdfRect,
) -> list[PaintPlan]:
    number_style = monospace_text_style(
        size_pt=_RECOVERY_FALLBACK_NUMBER_SIZE_PT,
        color=_INK_SOFT,
        char_spacing_mm=_RECOVERY_FALLBACK_NUMBER_CHAR_SPACING_MM,
    )
    number_width_mm = measured_fallback_number_width(
        surface,
        fallback_page,
        style=number_style,
        minimum_width_mm=_RECOVERY_FALLBACK_NUMBER_MIN_WIDTH_MM,
        padding_mm=_RECOVERY_FALLBACK_NUMBER_PADDING_MM,
    )
    number_x_mm = area.x_mm + _RECOVERY_FALLBACK_LEFT_INSET_MM
    payload_x_mm = number_x_mm + number_width_mm + _RECOVERY_FALLBACK_NUMBER_GAP_MM
    payload_width_mm = area.right_mm - payload_x_mm - _RECOVERY_FALLBACK_RIGHT_INSET_MM
    if payload_width_mm <= 0:
        raise ValueError("Ledger fallback number gutter leaves no payload width")
    plans: list[PaintPlan] = []
    for block_index, block_entries in enumerate(group_fallback_visual_blocks(fallback_page)):
        first_row = block_entries[0].row_index
        last_row = block_entries[-1].row_index
        block_y = area.y_mm + first_row * _FALLBACK_ROW_HEIGHT_MM
        block_h = (last_row - first_row + 1) * _FALLBACK_ROW_HEIGHT_MM
        plans.append(
            Panel(
                component_id=f"{prefix}-fallback-block-{block_index}",
                stroke=_SURFACE_BORDER,
                fill=_WHITE,
                line_width_mm=0.35,
            ).plan(surface, PdfRect(area.x_mm, block_y, area.width_mm, block_h))
        )
        plans.append(
            Rule(component_id=f"{prefix}-fallback-rail-{block_index}", color=_ACCENT).plan(
                surface,
                PdfRect(area.x_mm, block_y, 1.2, block_h),
            )
        )
        for local_index, page_entry in enumerate(block_entries):
            entry = page_entry.entry
            row_y = block_y + 0.3 + local_index * _FALLBACK_ROW_HEIGHT_MM
            if isinstance(entry, FallbackTitleEntry):
                plans.append(
                    TextBox(
                        component_id=f"{prefix}-fallback-title-{entry.section_index}",
                        text=entry.title.upper(),
                        style=title_text_style(
                            size_pt=7.0,
                            color=_INK_MUTED,
                            char_spacing_mm=0.22,
                        ),
                        policy=TextFitPolicy.SHRINK,
                        min_size_pt=6.0,
                    ).plan(surface, PdfRect(area.x_mm + 4.0, row_y, area.width_mm - 8.0, 3.0))
                )
            else:
                if page_entry.display_line_number is None:
                    raise ValueError("fallback payload line is missing its display number")
                plans.append(
                    TextBox(
                        component_id=(
                            f"{prefix}-fallback-number-{entry.section_index}-{entry.line_number}"
                        ),
                        text=f"{page_entry.display_line_number:02d}.",
                        style=number_style,
                        policy=TextFitPolicy.FAIL,
                        align=TextAlign.RIGHT,
                    ).plan(
                        surface,
                        PdfRect(number_x_mm, row_y + 0.2, number_width_mm, 2.8),
                    )
                )
                plans.append(
                    TextBox(
                        component_id=(
                            f"{prefix}-fallback-line-{entry.section_index}-{entry.line_number}"
                        ),
                        text=entry.text,
                        style=monospace_text_style(
                            size_pt=_RECOVERY_FALLBACK_BODY_SIZE_PT,
                            color=_INK,
                        ),
                        policy=TextFitPolicy.SHRINK,
                        min_size_pt=6.0,
                    ).plan(
                        surface,
                        PdfRect(payload_x_mm, row_y, payload_width_mm, 3.8),
                    )
                )
    return plans


def _resolve_ledger_shard_fallback(
    surface: PdfSurface,
    inputs: RenderInputs,
    *,
    area: PdfRect,
) -> tuple[_LedgerShardFallbackLayout, tuple[FallbackSectionLines, ...]]:
    candidates = (
        (1, _FALLBACK_ROW_HEIGHT_MM, 8.5, 7.0),
        (_SHARD_FALLBACK_COLUMNS, _SHARD_FALLBACK_ROW_HEIGHT_MM, 6.0, 6.0),
    )
    for columns, row_height_mm, body_font_size_pt, title_font_size_pt in candidates:
        column_width_mm = _shard_fallback_column_width(area, columns=columns)
        body_style = monospace_text_style(size_pt=body_font_size_pt, color=_INK)
        payload_width_mm = column_width_mm - 1.3 - 6.0 - 0.8 - 1.2
        line_length = measured_grouped_line_length(
            surface,
            style=body_style,
            alphabet=ZBASE32_ALPHABET,
            group_size=_FALLBACK_GROUP_SIZE,
            max_width_mm=payload_width_mm,
            safety_mm=_SHARD_FALLBACK_LINE_SAFETY_MM,
        )
        layout = _LedgerShardFallbackLayout(
            columns=columns,
            row_height_mm=row_height_mm,
            line_length=line_length,
            body_font_size_pt=body_font_size_pt,
            title_font_size_pt=title_font_size_pt,
        )
        sections = fallback_sections(
            inputs.fallback_sections or (),
            group_size=_FALLBACK_GROUP_SIZE,
            line_length=line_length,
        )
        if len(fallback_entries(sections)) <= _shard_fallback_capacity(area, layout=layout):
            return layout, sections
    raise ValueError("Ledger shard fallback payload exceeds the responsive one-page capacity")


def _shard_fallback_column_width(area: PdfRect, *, columns: int) -> float:
    if columns <= 0:
        raise ValueError("Ledger shard fallback columns must be positive")
    column_width_mm = (area.width_mm - (columns - 1) * _SHARD_FALLBACK_COLUMN_GAP_MM) / columns
    if column_width_mm <= 0:
        raise ValueError("Ledger shard fallback columns have no usable width")
    return column_width_mm


def _shard_fallback_capacity(
    area: PdfRect,
    *,
    layout: _LedgerShardFallbackLayout,
) -> int:
    rows_per_column = math.floor(area.height_mm / layout.row_height_mm)
    if rows_per_column <= 0:
        raise ValueError("Ledger shard fallback area must fit at least one row per column")
    return rows_per_column * layout.columns


def _visible_shard_fallback_area(
    fallback_page: FallbackPage,
    *,
    area: PdfRect,
    layout: _LedgerShardFallbackLayout,
) -> PdfRect:
    rows_per_column = math.floor(area.height_mm / layout.row_height_mm)
    if rows_per_column <= 0 or not fallback_page.entries:
        raise ValueError("Ledger shard fallback area has no visible rows")
    visible_rows = min(rows_per_column, len(fallback_page.entries))
    visible_height_mm = visible_rows * layout.row_height_mm
    return PdfRect(
        area.x_mm,
        area.bottom_mm - visible_height_mm,
        area.width_mm,
        visible_height_mm,
    )


def _shard_fallback_block_plans(
    surface: PdfSurface,
    fallback_page: FallbackPage,
    *,
    prefix: str,
    area: PdfRect,
    layout: _LedgerShardFallbackLayout,
) -> list[PaintPlan]:
    rows_per_column = math.floor(area.height_mm / layout.row_height_mm)
    column_width_mm = _shard_fallback_column_width(area, columns=layout.columns)
    if rows_per_column <= 0 or column_width_mm <= 0:
        raise ValueError("Ledger shard fallback columns have no usable area")
    visible_area = _visible_shard_fallback_area(
        fallback_page,
        area=area,
        layout=layout,
    )

    number_style = monospace_text_style(size_pt=6.5, color=_INK_SOFT, char_spacing_mm=0.04)
    number_width_mm = measured_fallback_number_width(
        surface,
        fallback_page,
        style=number_style,
        minimum_width_mm=6.0,
        padding_mm=0.25,
    )
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-fallback-block-0",
            stroke=_SURFACE_BORDER,
            fill=_WHITE,
            line_width_mm=0.25,
        ).plan(surface, visible_area)
    ]
    for block_index, (column_index, block_entries) in enumerate(
        _shard_fallback_column_blocks(
            fallback_page,
            rows_per_column=rows_per_column,
            columns=layout.columns,
        )
    ):
        column_x_mm = area.x_mm + column_index * (column_width_mm + _SHARD_FALLBACK_COLUMN_GAP_MM)
        first_row = block_entries[0].row_index % rows_per_column
        block_y = visible_area.y_mm + first_row * layout.row_height_mm
        block_h = len(block_entries) * layout.row_height_mm
        plans.append(
            Rule(component_id=f"{prefix}-fallback-rail-{block_index}", color=_ACCENT).plan(
                surface,
                PdfRect(column_x_mm, block_y, 0.8, block_h),
            )
        )
        number_x_mm = column_x_mm + 1.3
        payload_x_mm = number_x_mm + number_width_mm + 0.8
        payload_width_mm = column_x_mm + column_width_mm - payload_x_mm - 1.2
        if payload_width_mm <= 0:
            raise ValueError("Ledger shard fallback number gutter leaves no payload width")
        for page_entry in block_entries:
            entry = page_entry.entry
            local_row = page_entry.row_index % rows_per_column
            row_y = visible_area.y_mm + local_row * layout.row_height_mm
            if isinstance(entry, FallbackTitleEntry):
                plans.append(
                    TextBox(
                        component_id=f"{prefix}-fallback-title-{entry.section_index}",
                        text=entry.title.upper(),
                        style=title_text_style(
                            size_pt=layout.title_font_size_pt,
                            color=_INK_MUTED,
                            char_spacing_mm=0.08,
                        ),
                        policy=TextFitPolicy.SHRINK,
                        min_size_pt=6.0,
                    ).plan(
                        surface,
                        PdfRect(
                            column_x_mm + 2.0,
                            row_y,
                            column_width_mm - 4.0,
                            min(layout.row_height_mm, 3.8),
                        ),
                    )
                )
                continue
            if page_entry.display_line_number is None:
                raise ValueError("fallback payload line is missing its display number")
            plans.extend(
                (
                    TextBox(
                        component_id=(
                            f"{prefix}-fallback-number-{entry.section_index}-{entry.line_number}"
                        ),
                        text=f"{page_entry.display_line_number:02d}.",
                        style=number_style,
                        policy=TextFitPolicy.FAIL,
                        align=TextAlign.RIGHT,
                    ).plan(surface, PdfRect(number_x_mm, row_y, number_width_mm, 2.8)),
                    TextBox(
                        component_id=(
                            f"{prefix}-fallback-line-{entry.section_index}-{entry.line_number}"
                        ),
                        text=entry.text,
                        style=monospace_text_style(
                            size_pt=layout.body_font_size_pt,
                            color=_INK,
                        ),
                        policy=TextFitPolicy.FAIL,
                    ).plan(
                        surface,
                        PdfRect(
                            payload_x_mm,
                            row_y,
                            payload_width_mm,
                            min(layout.row_height_mm, 3.8),
                        ),
                    ),
                )
            )
    return plans


def _shard_fallback_column_blocks(
    fallback_page: FallbackPage,
    *,
    rows_per_column: int,
    columns: int,
) -> tuple[tuple[int, tuple[FallbackPageEntry, ...]], ...]:
    blocks: list[tuple[int, tuple[FallbackPageEntry, ...]]] = []
    current_column = -1
    current: list[FallbackPageEntry] = []
    for page_entry in fallback_page.entries:
        column_index = page_entry.row_index // rows_per_column
        if column_index >= columns:
            raise ValueError("Ledger shard fallback page exceeds its measured column capacity")
        if column_index != current_column or (
            isinstance(page_entry.entry, FallbackTitleEntry) and current
        ):
            if current:
                blocks.append((current_column, tuple(current)))
            current = []
            current_column = column_index
        current.append(page_entry)
    if current:
        blocks.append((current_column, tuple(current)))
    return tuple(blocks)


def _instruction_insert_plans(
    surface: PdfSurface,
    context: StructuredContext,
    *,
    prefix: str,
    rect: PdfRect,
    page_label: str,
) -> list[PaintPlan]:
    inner_x = rect.x_mm + 8.0
    inner_right = rect.right_mm - 8.0
    inner_width = inner_right - inner_x
    right_width = 58.0
    right_x = inner_right - right_width - 6.0
    left_width = right_x - inner_x - 8.0
    footer_rule_y = rect.bottom_mm - 17.0
    checklist_y = rect.y_mm + 155.0
    checklist_height = min(56.0, footer_rule_y - 8.0 - checklist_y)
    if left_width < 80.0 or checklist_height < 44.0:
        raise ValueError("Ledger recovery-kit insert has no usable two-column body")
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-insert-shell",
            stroke=_RULE_STRONG,
            fill=_SURFACE,
            line_width_mm=0.45,
        ).plan(surface, rect),
        Panel(
            component_id=f"{prefix}-insert-inner-rule",
            stroke=_RULE_STRONG,
            fill=None,
            line_width_mm=0.35,
        ).plan(
            surface,
            PdfRect(rect.x_mm + 1.5, rect.y_mm + 1.5, rect.width_mm - 3.0, rect.height_mm - 3.0),
        ),
        TextBox(
            component_id=f"{prefix}-insert-stamp",
            text="INSTRUCTION INSERT",
            style=title_text_style(size_pt=7.0, color=_ACCENT, char_spacing_mm=0.35),
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.CENTER,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(inner_right - 41.0, rect.y_mm + 4.0, 39.0, 5.4)),
        TextBox(
            component_id=f"{prefix}-insert-title",
            text="HOW TO REBUILD THE RECOVERY KIT",
            style=title_text_style(size_pt=15.0, color=_INK, char_spacing_mm=0.26),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=11.0,
        ).plan(surface, PdfRect(inner_x, rect.y_mm + 9.0, inner_width - 25.0, 8.0)),
        TextBox(
            component_id=f"{prefix}-insert-subtitle",
            text="Use this page after scanning the QR pages. Keep everything offline.",
            style=body_text_style(size_pt=9.0, color=_INK_MUTED, char_spacing_mm=0.08),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=7.0,
        ).plan(surface, PdfRect(inner_x, rect.y_mm + 20.0, inner_width - 21.0, 4.5)),
        Rule(component_id=f"{prefix}-insert-hero-rule", color=_RULE_STRONG).plan(
            surface,
            PdfRect(inner_x, rect.y_mm + 28.2, inner_width, 0.55),
        ),
    ]
    plans.extend(
        build_instruction_steps_section(
            surface,
            prefix=prefix,
            title="Scan + Assemble",
            lines=(
                "Scan every QR code left to right, top to bottom.",
                "Save each decoded chunk in order. Do not insert spaces or blank lines.",
                "Concatenate the chunks into one continuous file.",
                "Name the file exactly: recovery_kit.bundle.html",
            ),
            rect=PdfRect(inner_x, rect.y_mm + 37.0, left_width, 64.0),
            index=1,
            style=_INSTRUCTION_STYLE,
        )
    )
    plans.extend(
        build_instruction_steps_section(
            surface,
            prefix=prefix,
            title="Open the Kit",
            lines=(
                "Open recovery_kit.bundle.html in a browser while offline.",
                "If the file is large, wait for it to finish loading.",
                "Follow the on-screen prompts to recover your payload.",
            ),
            rect=PdfRect(inner_x, rect.y_mm + 90.0, left_width, 52.0),
            index=2,
            style=_INSTRUCTION_STYLE,
        )
    )
    plans.extend(
        build_instruction_bullets_section(
            surface,
            prefix=prefix,
            title="Troubleshooting",
            lines=(
                "If the kit does not load, re-check chunk order and re-save the file.",
                "Try another browser if rendering stalls.",
                "Confirm the file size matches the sum of all QR chunks.",
            ),
            rect=PdfRect(inner_x, rect.y_mm + 137.0, left_width, 44.0),
            index=3,
            style=_INSTRUCTION_STYLE,
        )
    )
    plans.extend(
        _instruction_callout_plans(
            surface,
            prefix=prefix,
            rect=PdfRect(right_x, rect.y_mm + 37.0, right_width, 33.0),
            title="Verify",
            lines=(
                "Confirm the kit loads and shows the Recovery Kit home screen.",
                "If it fails to open, re-check the order and re-save the file.",
            ),
            index=1,
        )
    )
    plans.extend(
        _instruction_callout_plans(
            surface,
            prefix=prefix,
            rect=PdfRect(right_x, rect.y_mm + 77.0, right_width, 33.0),
            title="Storage",
            lines=(
                "Keep the QR pages and the bundle file in separate locations.",
                "Store the bundle on a write-protected drive if possible.",
            ),
            index=2,
        )
    )
    plans.extend(
        _instruction_callout_plans(
            surface,
            prefix=prefix,
            rect=PdfRect(right_x, rect.y_mm + 117.0, right_width, 30.0),
            title="Security",
            lines=(
                "Work offline and on a trusted machine.",
                "Delete temporary files after recovery.",
            ),
            index=3,
        )
    )
    plans.extend(
        build_instruction_checklist(
            surface,
            prefix=prefix,
            rect=PdfRect(right_x, checklist_y, right_width, checklist_height),
            style=_INSTRUCTION_STYLE,
        )
    )
    plans.extend(
        _instruction_insert_footer(
            surface,
            context,
            prefix=prefix,
            rect=rect,
            page_label=page_label,
        )
    )
    return plans


def _instruction_callout_plans(
    surface: PdfSurface,
    *,
    prefix: str,
    rect: PdfRect,
    title: str,
    lines: Sequence[str],
    index: int,
) -> list[PaintPlan]:
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-callout-{index}",
            stroke=_RULE,
            fill=_NOTE,
            line_width_mm=0.35,
        ).plan(surface, rect),
        TextBox(
            component_id=f"{prefix}-callout-title-{index}",
            text=title.upper(),
            style=title_text_style(size_pt=8.0, color=_ACCENT, char_spacing_mm=0.24),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(rect.x_mm + 3.0, rect.y_mm + 3.0, rect.width_mm - 6.0, 3.5)),
    ]
    y_mm = rect.y_mm + 10.0
    for line_index, line in enumerate(lines):
        text_plan = TextBox(
            component_id=f"{prefix}-callout-line-{index}-{line_index}",
            text=line,
            style=body_text_style(size_pt=8.4, color=_INK),
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=1.2,
        ).plan(surface, PdfRect(rect.x_mm + 3.0, y_mm, rect.width_mm - 6.0, 10.0))
        plans.append(text_plan)
        y_mm += max(7.2, text_plan.proof.used_rect.height_mm + 1.6)
    return plans


def _instruction_insert_footer(
    surface: PdfSurface,
    context: StructuredContext,
    *,
    prefix: str,
    rect: PdfRect,
    page_label: str,
) -> list[PaintPlan]:
    inner_x = rect.x_mm + 8.0
    inner_width = rect.width_mm - 16.0
    rule_y = rect.bottom_mm - 17.0
    text_y = rule_y + 5.2
    kind_width = inner_width * 0.42
    page_width = 28.0
    doc_x = inner_x + kind_width + page_width
    doc_width = inner_width - kind_width - page_width
    return [
        Rule(component_id=f"{prefix}-insert-footer-rule", color=_RULE_STRONG).plan(
            surface,
            PdfRect(inner_x, rule_y, inner_width, 0.55),
        ),
        TextBox(
            component_id=f"{prefix}-insert-footer-kind",
            text="RECOVERY KIT: OFFLINE HTML BUNDLE",
            style=body_text_style(size_pt=8.0, color=_INK_MUTED, char_spacing_mm=0.2),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(inner_x, text_y, kind_width, 4.2)),
        TextBox(
            component_id=f"{prefix}-insert-footer-page",
            text=page_label,
            style=monospace_text_style(
                size_pt=7.0,
                bold=True,
                color=_ACCENT,
                char_spacing_mm=0.06,
            ),
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.CENTER,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(inner_x + kind_width, text_y, page_width, 4.2)),
        TextBox(
            component_id=f"{prefix}-insert-footer-doc",
            text=f"Document ID: {context.doc_id}",
            style=monospace_text_style(
                size_pt=7.0,
                color=_INK,
                char_spacing_mm=0.06,
            ),
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.RIGHT,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(doc_x, text_y, doc_width, 4.2)),
    ]


__all__ = [
    "LedgerDirectPlan",
    "build_ledger_kit_direct_plan",
    "build_ledger_main_direct_plan",
    "build_ledger_recovery_direct_plan",
    "build_ledger_shard_direct_plan",
    "build_ledger_signing_key_shard_direct_plan",
    "render_ledger_kit_direct_pdf",
    "render_ledger_main_direct_pdf",
    "render_ledger_recovery_direct_pdf",
    "render_ledger_shard_direct_pdf",
    "render_ledger_signing_key_shard_direct_pdf",
]
