"""Maritime design rendering through direct PDF primitives."""

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
from ethernity.render.direct_pdf.components import ImageBox, Panel, Rule, TextAlign, TextBox
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
    StructuredDirectPlan as MaritimeDirectPlan,
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
_INK = PdfColor(12, 34, 48)
_INK_MUTED = PdfColor(49, 73, 90)
_INK_SOFT = PdfColor(90, 115, 132)
_STAMP = PdfColor(31, 94, 115)
_RAIL = PdfColor(12, 43, 60)
_PAPER = PdfColor(242, 246, 247)
_SURFACE = PdfColor(247, 251, 252)
_SURFACE_BORDER = PdfColor(183, 196, 201)
_RULE = PdfColor(193, 206, 210)
_RULE_STRONG = PdfColor(134, 154, 163)
_NOTE = PdfColor(233, 240, 242)
_TAB = PdfColor(199, 221, 224)
_WHITE = PdfColor(255, 255, 255)
_QR_COLUMNS = 3
_QR_ROWS_PER_PAGE = 3
_QR_CARD_SIZE_MM = 58.0
_QR_CARD_GAP_MM = 3.0
_QR_IMAGE_SIZE_MM = 55.8
_QR_LABEL_BAND_HEIGHT_MM = 5.2
_MIN_QR_CARD_SIZE_MM = 48.0
_MIN_QR_IMAGE_SIZE_MM = 42.0
_FALLBACK_GROUP_SIZE = 4
_FALLBACK_ROW_HEIGHT_MM = 4.2
_RECOVERY_FALLBACK_BODY_SIZE_PT = 8.5
_RECOVERY_FALLBACK_NUMBER_SIZE_PT = 6.5
_RECOVERY_FALLBACK_NUMBER_CHAR_SPACING_MM = 0.08
_RECOVERY_FALLBACK_LEFT_INSET_MM = 4.0
_RECOVERY_FALLBACK_RIGHT_INSET_MM = 4.0
_RECOVERY_FALLBACK_NUMBER_GAP_MM = 4.0
_RECOVERY_FALLBACK_NUMBER_MIN_WIDTH_MM = 6.0
_RECOVERY_FALLBACK_NUMBER_PADDING_MM = 0.4
_RECOVERY_FALLBACK_LINE_SAFETY_MM = 0.2
_SHARD_FALLBACK_COLUMNS = 2
_SHARD_FALLBACK_COLUMN_GAP_MM = 4.0
_SHARD_FALLBACK_ROW_HEIGHT_MM = 2.85
_SHARD_FALLBACK_HEIGHT_MM = 112.0
_SHARD_FALLBACK_LINE_SAFETY_MM = 0.2
_CONTENT_BOTTOM_INSET_MM = 7.0
_INSTRUCTION_LINE_GAP_MM = 0.6
_META_VALUE_WIDTH_MM = 72.0
_PASSPHRASE_META_VALUE_WIDTH_MM = 84.0
_META_LABEL_MIN_WIDTH_MM = 24.0
_META_LABEL_VALUE_GAP_MM = 5.0
_META_LABEL_WIDTH_SAFETY_MM = 0.4
_META_STAMP_CLEARANCE_MM = 5.0
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
    section_accent=_STAMP,
    section_fill=PdfColor(235, 244, 246),
)


@dataclass(frozen=True)
class _HeaderLayout:
    plans: tuple[PaintPlan, ...]
    content_start_y_mm: float


class _HeaderMetaKind(str, Enum):
    STANDARD = "standard"
    PASSPHRASE = "passphrase"


@dataclass(frozen=True)
class _HeaderMetaRow:
    label: str
    value: str
    kind: _HeaderMetaKind = _HeaderMetaKind.STANDARD
    guidance: str = ""


@dataclass(frozen=True)
class _MaritimeShardFallbackLayout:
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
        raise ValueError("Maritime body constraints require header and content plans")
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


def render_maritime_main_direct_pdf(inputs: RenderInputs) -> RenderResult:
    """Render a Maritime main document directly to PDF."""

    return _render_maritime_plan(inputs, build_maritime_main_direct_plan)


def render_maritime_recovery_direct_pdf(inputs: RenderInputs) -> RenderResult:
    """Render a Maritime recovery document directly to PDF."""

    return _render_maritime_plan(inputs, build_maritime_recovery_direct_plan)


def render_maritime_shard_direct_pdf(inputs: RenderInputs) -> RenderResult:
    """Render a Maritime shard document directly to PDF."""

    return _render_maritime_plan(inputs, build_maritime_shard_direct_plan)


def render_maritime_signing_key_shard_direct_pdf(inputs: RenderInputs) -> RenderResult:
    """Render a Maritime signing-key shard document directly to PDF."""

    return _render_maritime_plan(inputs, build_maritime_signing_key_shard_direct_plan)


def render_maritime_kit_direct_pdf(inputs: RenderInputs) -> RenderResult:
    """Render a Maritime recovery-kit document directly to PDF."""

    return _render_maritime_plan(inputs, build_maritime_kit_direct_plan)


def _render_maritime_plan(inputs: RenderInputs, builder: StructuredPlanBuilder) -> RenderResult:
    return render_structured_plan(inputs, style_name="maritime", builder=builder)


def build_maritime_main_direct_plan(
    surface: PdfSurface,
    inputs: RenderInputs,
) -> MaritimeDirectPlan:
    """Build measured Maritime main-document pages and proof."""

    layout = resolve_classic_layout(inputs, style=_PAGE_STYLE)
    validate_qr_inputs(
        inputs,
        expected_doc_type=DOC_TYPE_MAIN,
    )
    payloads = resolved_qr_payloads(inputs)
    items = qr_payload_items(payloads, config=inputs.qr_config or QrConfig())
    context = build_structured_context(inputs, doc_type=DOC_TYPE_MAIN)
    grid = resolve_qr_grid(
        layout,
        top_mm=_qr_page_top_mm(
            surface,
            context,
            layout,
            include_subtitle=False,
            include_instructions=True,
        ),
        preferred_rows=_QR_ROWS_PER_PAGE,
        style=_QR_GRID_STYLE,
    )
    qr_pages = paginate_qr_items(items, capacity=grid.capacity)
    page_plans = tuple(
        _build_qr_page(
            surface,
            context,
            qr_page,
            layout=layout,
            grid=grid,
            component_base="maritime-main",
            total_pages=len(qr_pages),
            include_subtitle=False,
            include_instructions=True,
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
    return MaritimeDirectPlan(page_plans=page_plans, artifact_proof=artifact_proof)


def build_maritime_recovery_direct_plan(
    surface: PdfSurface,
    inputs: RenderInputs,
) -> MaritimeDirectPlan:
    """Build measured Maritime recovery-document pages and proof."""

    layout = resolve_classic_layout(inputs, style=_PAGE_STYLE)
    validate_recovery_inputs(inputs)
    recovery_meta = inputs.recovery_meta or RecoveryMeta()
    context = build_structured_context(inputs, doc_type=DOC_TYPE_RECOVERY)
    passphrase_pagination = _paginate_maritime_passphrase(
        surface,
        recovery_meta,
        layout=layout,
    )
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
    return MaritimeDirectPlan(
        page_plans=page_plans,
        artifact_proof=artifact_proof,
        fallback_proof=fallback_proof,
    )


def _paginate_maritime_passphrase(
    surface: PdfSurface,
    recovery_meta: RecoveryMeta,
    *,
    layout: ClassicLayout,
) -> RecoveryPassphrasePagination:
    style = monospace_text_style(size_pt=7.2, color=_INK, char_spacing_mm=0.08)
    guidance_style = body_text_style(size_pt=6.0, color=_INK_MUTED)
    value_rect = _passphrase_continuation_value_rect(layout)
    return paginate_recovery_passphrase(
        surface,
        recovery_meta,
        style=style,
        guidance_style=guidance_style,
        max_width_mm=_PASSPHRASE_META_VALUE_WIDTH_MM,
        inline_height_mm=4.0 * surface.line_height(style, multiplier=1.1),
        continuation_height_mm=value_rect.height_mm,
        line_height_multiplier=1.1,
    )


def _passphrase_continuation_value_rect(layout: ClassicLayout) -> PdfRect:
    top_mm = layout.safe_rect.y_mm + 65.0
    bottom_mm = layout.content_rect.bottom_mm - 4.0
    if bottom_mm <= top_mm:
        raise ValueError("Maritime page has zero-capacity passphrase continuation area")
    width_mm = _PASSPHRASE_META_VALUE_WIDTH_MM
    return PdfRect(
        layout.safe_rect.x_mm + (layout.safe_rect.width_mm - width_mm) / 2.0,
        top_mm,
        width_mm,
        bottom_mm - top_mm,
    )


def build_maritime_shard_direct_plan(
    surface: PdfSurface,
    inputs: RenderInputs,
) -> MaritimeDirectPlan:
    """Build measured Maritime shard-document pages and proof."""

    return _build_maritime_single_qr_fallback_plan(
        surface,
        inputs,
        expected_doc_type=DOC_TYPE_SHARD,
    )


def build_maritime_signing_key_shard_direct_plan(
    surface: PdfSurface,
    inputs: RenderInputs,
) -> MaritimeDirectPlan:
    """Build measured Maritime signing-key shard pages and proof."""

    return _build_maritime_single_qr_fallback_plan(
        surface,
        inputs,
        expected_doc_type=DOC_TYPE_SIGNING_KEY_SHARD,
    )


def build_maritime_kit_direct_plan(
    surface: PdfSurface,
    inputs: RenderInputs,
) -> MaritimeDirectPlan:
    """Build measured Maritime recovery-kit pages and proof."""

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
        top_mm=_qr_page_top_mm(
            surface,
            context,
            layout,
            include_subtitle=False,
            include_instructions=False,
        ),
        preferred_rows=_QR_ROWS_PER_PAGE,
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
            component_base="maritime-kit",
            total_pages=total_pages,
            include_subtitle=False,
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
    return MaritimeDirectPlan(page_plans=page_plans, artifact_proof=artifact_proof)


def _build_maritime_single_qr_fallback_plan(
    surface: PdfSurface,
    inputs: RenderInputs,
    *,
    expected_doc_type: str,
) -> MaritimeDirectPlan:
    layout = resolve_classic_layout(inputs, style=_PAGE_STYLE)
    validate_single_qr_fallback_inputs(
        inputs,
        expected_doc_type=expected_doc_type,
    )
    payload = resolved_single_qr_payload(inputs)
    rendered_qr = qr_image(payload, config=inputs.qr_config or QrConfig())
    context = build_structured_context(inputs, doc_type=expected_doc_type)
    qr_rect, fallback_area = _shard_content_areas(surface, context, layout)
    fallback_layout, sections = _resolve_maritime_shard_fallback(
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
    return MaritimeDirectPlan(
        page_plans=page_plans,
        artifact_proof=artifact_proof,
        fallback_proof=fallback_proof,
    )


def _qr_page_top_mm(
    surface: PdfSurface,
    context: StructuredContext,
    layout: ClassicLayout,
    *,
    include_subtitle: bool,
    include_instructions: bool,
) -> float:
    header = _header_layout(
        surface,
        context,
        layout=layout,
        prefix="maritime-measure",
        page_label="Page 1 / 1",
        include_subtitle=include_subtitle,
    )
    if not include_instructions:
        return header.content_start_y_mm + 6.0
    instruction_rect = PdfRect(
        layout.safe_rect.x_mm,
        header.content_start_y_mm + 3.0,
        layout.safe_rect.width_mm,
        15.5,
    )
    return instruction_rect.bottom_mm + 4.5


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
        prefix="maritime-recovery-measure",
        page_label="Page 1 / 1",
        include_subtitle=True,
        rows=_recovery_meta_rows(recovery_meta),
    )
    instructions = PdfRect(
        layout.safe_rect.x_mm,
        header.content_start_y_mm + 1.0,
        layout.safe_rect.width_mm,
        17.0,
    )
    top_mm = max(layout.safe_rect.y_mm + 72.0, instructions.bottom_mm + 2.0)
    area = PdfRect(
        layout.safe_rect.x_mm,
        top_mm,
        layout.safe_rect.width_mm,
        layout.content_rect.bottom_mm - top_mm,
    )
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
        prefix="maritime-shard-measure",
        page_label="Page 1 / 1",
        include_subtitle=True,
        rows=(
            _HeaderMetaRow(
                "Shard",
                f"{positive_int(context.values.get('shard_index'), default=1)} / "
                f"{positive_int(context.values.get('shard_total'), default=1)}",
            ),
        ),
    )
    instructions = PdfRect(
        layout.safe_rect.x_mm,
        header.content_start_y_mm + 8.0,
        layout.safe_rect.width_mm,
        18.0,
    )
    qr_top_mm = instructions.bottom_mm + 4.0
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
            fallback_area.y_mm - 10.0 - qr_top_mm,
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
    return qr_grid.item_rects(1)[0], fallback_area


def _build_qr_page(
    surface: PdfSurface,
    context: StructuredContext,
    qr_page: QrPage,
    *,
    layout: ClassicLayout,
    grid: ResolvedGrid,
    component_base: str,
    total_pages: int,
    include_subtitle: bool,
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
        include_subtitle=include_subtitle,
    )
    header_plans = list(header.plans)
    plans.extend(header_plans)
    if include_instructions:
        instruction_rect = PdfRect(
            layout.safe_rect.x_mm,
            header.content_start_y_mm + 3.0,
            layout.safe_rect.width_mm,
            15.5,
        )
        instruction_plans = _instructions_plans(
            surface,
            context,
            prefix=prefix,
            rect=instruction_rect,
        )
        header_plans.extend(instruction_plans)
        plans.extend(instruction_plans)
    qr_plans = _qr_field_plans(
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
    prefix = component_prefix("maritime-recovery", fallback_page.page_number)
    page_label = f"Page {fallback_page.page_number} / {total_pages}"
    plans: list[PaintPlan] = []
    plans.extend(build_page_background(surface, layout=layout, prefix=prefix, fill=_PAPER))
    header = _header_layout(
        surface,
        context,
        layout=layout,
        prefix=prefix,
        page_label=page_label,
        include_subtitle=True,
        rows=_recovery_meta_rows(recovery_meta),
    )
    header_plans = list(header.plans)
    instructions = PdfRect(
        layout.safe_rect.x_mm,
        header.content_start_y_mm + 1.0,
        layout.safe_rect.width_mm,
        17.0,
    )
    instruction_plans = _instructions_plans(
        surface,
        context,
        prefix=prefix,
        rect=instructions,
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
    prefix = component_prefix("maritime-recovery", page_number)
    page_label = f"Page {page_number} / {total_pages}"
    plans: list[PaintPlan] = []
    plans.extend(build_page_background(surface, layout=layout, prefix=prefix, fill=_PAPER))
    header = _header_layout(
        surface,
        context,
        layout=layout,
        prefix=prefix,
        page_label=page_label,
        include_subtitle=True,
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
            style=title_text_style(size_pt=10.0, color=_STAMP, char_spacing_mm=0.2),
            policy=TextFitPolicy.FAIL,
        ).plan(
            surface,
            PdfRect(
                layout.safe_rect.x_mm,
                header.content_start_y_mm + 3.0,
                layout.safe_rect.width_mm,
                5.0,
            ),
        ),
        TextBox(
            component_id=f"{prefix}-passphrase-continuation-instructions",
            text=continuation_page.instructions,
            style=body_text_style(size_pt=7.8, color=_INK_MUTED),
            policy=TextFitPolicy.WRAP,
        ).plan(
            surface,
            PdfRect(
                layout.safe_rect.x_mm,
                header.content_start_y_mm + 10.0,
                layout.safe_rect.width_mm,
                16.0,
            ),
        ),
        Panel(
            component_id=f"{prefix}-passphrase-continuation-panel",
            stroke=_SURFACE_BORDER,
            fill=_SURFACE,
            line_width_mm=0.3,
        ).plan(surface, panel_rect),
        TextBox(
            component_id=f"{prefix}-passphrase-continuation-value",
            text=continuation_page.text,
            style=monospace_text_style(size_pt=7.2, color=_INK, char_spacing_mm=0.08),
            policy=TextFitPolicy.FAIL,
            line_height_multiplier=1.1,
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
    fallback_layout: _MaritimeShardFallbackLayout,
    total_pages: int,
) -> DirectPdfPagePlan:
    normalized_doc_type = context.doc_type.strip().lower()
    component_base = (
        "maritime-signing-key-shard"
        if normalized_doc_type == DOC_TYPE_SIGNING_KEY_SHARD
        else "maritime-shard"
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
        include_subtitle=True,
        rows=(_HeaderMetaRow("Shard", f"{shard_index} / {shard_total}"),),
    )
    header_plans = list(header.plans)
    instructions = PdfRect(
        layout.safe_rect.x_mm,
        header.content_start_y_mm + 8.0,
        layout.safe_rect.width_mm,
        18.0,
    )
    instruction_plans = _instructions_plans(
        surface,
        context,
        prefix=prefix,
        rect=instructions,
    )
    header_plans.extend(instruction_plans)
    plans.extend(header_plans)
    qr_plans = _single_qr_field_plans(
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
    prefix = component_prefix("maritime-kit", page_number)
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
    include_subtitle: bool,
    rows: Sequence[_HeaderMetaRow] = (),
) -> _HeaderLayout:
    safe_rect = layout.safe_rect
    stamp_width = 48.0
    stamp_x = safe_rect.right_mm - stamp_width
    title_width = stamp_x - safe_rect.x_mm - 20.0
    if title_width < 80.0:
        raise ValueError("Maritime page safe area cannot fit the header columns")
    plans: list[PaintPlan] = [
        TextBox(
            component_id=f"{prefix}-title",
            text=str(context.copy.get("title") or "Document").upper(),
            style=title_text_style(size_pt=15.5, color=_INK, char_spacing_mm=0.26),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=11.0,
        ).plan(surface, PdfRect(safe_rect.x_mm, safe_rect.y_mm + 0.4, title_width, 7.0)),
    ]
    meta_y = safe_rect.y_mm + 9.0
    if include_subtitle:
        plans.append(
            TextBox(
                component_id=f"{prefix}-subtitle",
                text=str(context.copy.get("subtitle") or "").upper(),
                style=body_text_style(size_pt=8.0, color=_INK_MUTED, char_spacing_mm=0.26),
                policy=TextFitPolicy.SHRINK,
                min_size_pt=6.0,
            ).plan(surface, PdfRect(safe_rect.x_mm, meta_y, title_width - 2.0, 4.0))
        )
        meta_y = safe_rect.y_mm + 18.0

    meta_rows = (
        _HeaderMetaRow("Document ID", context.doc_id),
        *rows,
        _HeaderMetaRow("Page", page_label),
    )
    meta_value_width = (
        _PASSPHRASE_META_VALUE_WIDTH_MM
        if any(row.kind is _HeaderMetaKind.PASSPHRASE for row in rows)
        else _META_VALUE_WIDTH_MM
    )
    label_style = title_text_style(
        size_pt=6.0,
        color=_INK_SOFT,
        char_spacing_mm=0.32,
    )
    meta_right_mm = safe_rect.right_mm if include_subtitle else stamp_x - _META_STAMP_CLEARANCE_MM
    max_label_width_mm = (
        meta_right_mm - safe_rect.x_mm - _META_LABEL_VALUE_GAP_MM - meta_value_width
    )
    if max_label_width_mm <= 0:
        raise ValueError("Maritime page safe area cannot fit the metadata columns")
    measured_label_width_mm = max(
        surface.measure_text_width(row.label.upper(), label_style) for row in meta_rows
    )
    label_width_mm = min(
        max(
            _META_LABEL_MIN_WIDTH_MM,
            measured_label_width_mm + _META_LABEL_WIDTH_SAFETY_MM,
        ),
        max_label_width_mm,
    )
    value_x_mm = safe_rect.x_mm + label_width_mm + _META_LABEL_VALUE_GAP_MM
    cursor_y = meta_y
    for index, row in enumerate(meta_rows):
        label = row.label
        value = row.value
        value_style = monospace_text_style(size_pt=7.2, color=_INK, char_spacing_mm=0.08)
        guidance_height_mm = 0.0
        guidance_style = body_text_style(size_pt=6.0, color=_INK_MUTED)
        if row.guidance:
            guidance_height_mm = (
                fit_text_to_width(
                    surface,
                    row.guidance,
                    guidance_style,
                    max_width_mm=meta_value_width,
                    policy=TextFitPolicy.WRAP,
                    line_height_multiplier=1.1,
                ).height_mm
                + 0.8
            )
        value_fit = fit_text_to_width(
            surface,
            value,
            value_style,
            max_width_mm=meta_value_width,
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=1.1,
        )
        label_fit = fit_text_to_width(
            surface,
            label.upper(),
            label_style,
            max_width_mm=label_width_mm,
            policy=TextFitPolicy.WRAP,
        )
        label_height_mm = max(3.1, label_fit.height_mm + 0.1)
        row_h = max(
            4.0,
            label_height_mm,
            guidance_height_mm + value_fit.height_mm,
        )
        plans.append(
            TextBox(
                component_id=f"{prefix}-meta-label-{index}",
                text=label.upper(),
                style=label_style,
                policy=TextFitPolicy.WRAP,
            ).plan(
                surface,
                PdfRect(
                    safe_rect.x_mm,
                    cursor_y,
                    label_width_mm,
                    label_height_mm,
                ),
            )
        )
        value_y_mm = cursor_y
        if row.guidance:
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
                        value_x_mm,
                        value_y_mm,
                        meta_value_width,
                        guidance_height_mm - 0.8,
                    ),
                )
            )
            value_y_mm += guidance_height_mm
        plans.append(
            TextBox(
                component_id=f"{prefix}-meta-value-{index}",
                text=value,
                style=value_style,
                policy=TextFitPolicy.WRAP,
                min_size_pt=6.0,
                line_height_multiplier=1.1,
            ).plan(
                surface,
                PdfRect(
                    value_x_mm,
                    value_y_mm,
                    meta_value_width,
                    cursor_y + row_h - value_y_mm,
                ),
            )
        )
        cursor_y += row_h + 1.2

    plans.extend(_stamp_plans(surface, context, layout=layout, prefix=prefix))
    minimum_start_y = safe_rect.y_mm + (29.0 if include_subtitle else 20.0)
    return _HeaderLayout(
        plans=tuple(plans),
        content_start_y_mm=max(minimum_start_y, cursor_y + 1.0),
    )


def _stamp_plans(
    surface: PdfSurface,
    context: StructuredContext,
    *,
    layout: ClassicLayout,
    prefix: str,
) -> list[PaintPlan]:
    stamp = PdfRect(layout.safe_rect.right_mm - 48.0, layout.safe_rect.y_mm, 48.0, 18.0)
    return [
        Panel(
            component_id=f"{prefix}-stamp-box",
            stroke=_RULE_STRONG,
            fill=_SURFACE,
            line_width_mm=0.45,
        ).plan(surface, stamp),
        TextBox(
            component_id=f"{prefix}-stamp-label",
            text="CREATED (UTC)",
            style=title_text_style(size_pt=7.0, color=_STAMP, char_spacing_mm=0.24),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(stamp.x_mm + 3.0, stamp.y_mm + 3.0, stamp.width_mm - 6.0, 3.2)),
        TextBox(
            component_id=f"{prefix}-stamp-value",
            text=context.created_timestamp_utc,
            style=title_text_style(size_pt=8.8, color=_INK, char_spacing_mm=0.16),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(stamp.x_mm + 3.0, stamp.y_mm + 8.8, stamp.width_mm - 6.0, 4.5)),
    ]


def _recovery_meta_rows(recovery_meta: RecoveryMeta) -> tuple[_HeaderMetaRow, ...]:
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
    if recovery_meta.passphrase_lines:
        passphrase = recovery_passphrase_display(recovery_meta)
        rows.append(
            _HeaderMetaRow(
                passphrase.label,
                "\n".join(passphrase.value_lines),
                _HeaderMetaKind.PASSPHRASE,
                passphrase.guidance,
            )
        )
    return tuple(rows)


def _meta_row_height(
    surface: PdfSurface,
    value: str,
    *,
    style: TextStyle,
    max_width_mm: float,
) -> float:
    fit = fit_text_to_width(
        surface,
        value,
        style,
        max_width_mm=max_width_mm,
        policy=TextFitPolicy.WRAP,
        line_height_multiplier=1.1,
    )
    return max(3.7, fit.height_mm)


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
            stroke=_RULE_STRONG,
            fill=PdfColor(238, 245, 247),
            line_width_mm=0.35,
        ).plan(surface, rect),
        TextBox(
            component_id=f"{prefix}-instructions-label",
            text=context.instructions_label.upper(),
            style=title_text_style(size_pt=6.5, color=_STAMP, char_spacing_mm=0.32),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(rect.x_mm + 3.0, rect.y_mm + 2.0, 29.0, 3.2)),
    ]
    y_mm = rect.y_mm + 2.0
    for index, line in enumerate(context.instruction_lines):
        text_box = TextBox(
            component_id=f"{prefix}-instruction-line-{index}",
            text=line,
            style=body_text_style(size_pt=8.8, color=_INK),
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=1.16,
        )
        available_rect = PdfRect(
            rect.x_mm + 39.0,
            y_mm,
            rect.width_mm - 43.0,
            rect.bottom_mm - y_mm,
        )
        measured_plan = text_box.plan(surface, available_rect)
        line_rect = PdfRect(
            available_rect.x_mm,
            available_rect.y_mm,
            available_rect.width_mm,
            measured_plan.proof.used_rect.height_mm,
        )
        line_plan = text_box.plan(surface, line_rect)
        plans.append(line_plan)
        y_mm = line_plan.proof.used_rect.bottom_mm
        if index < len(context.instruction_lines) - 1:
            y_mm += _INSTRUCTION_LINE_GAP_MM
    return plans


def _qr_field_plans(
    surface: PdfSurface,
    qr_page: QrPage,
    *,
    grid: ResolvedGrid,
    prefix: str,
    label_prefix: str,
    label_total: int,
) -> list[PaintPlan]:
    rects = grid.item_rects(len(qr_page.items))
    outline = PdfRect(
        min(rect.x_mm for rect in rects) - 2.0,
        min(rect.y_mm for rect in rects) - 2.0,
        max(rect.right_mm for rect in rects) - min(rect.x_mm for rect in rects) + 4.0,
        max(rect.bottom_mm for rect in rects) - min(rect.y_mm for rect in rects) + 4.0,
    )
    plans = _qr_field_background(surface, prefix=prefix, rect=outline)
    for item, rect in zip(qr_page.items, rects, strict=True):
        plans.extend(
            _qr_image_plans(
                surface,
                item,
                prefix=prefix,
                rect=rect,
                label_prefix=label_prefix,
                label_total=label_total,
            )
        )
    return plans


def _single_qr_field_plans(
    surface: PdfSurface,
    *,
    qr_image_bytes: bytes,
    prefix: str,
    rect: PdfRect,
) -> list[PaintPlan]:
    outline = PdfRect(rect.x_mm - 2.0, rect.y_mm - 2.0, rect.width_mm + 4.0, rect.height_mm + 4.0)
    plans = _qr_field_background(surface, prefix=prefix, rect=outline)
    plans.extend(
        _qr_image_plans(
            surface,
            QrPayloadItem(payload_index=0, payload=b"", image=qr_image_bytes),
            prefix=prefix,
            rect=rect,
            label_prefix=None,
            label_total=None,
        )
    )
    return plans


def _qr_field_background(surface: PdfSurface, *, prefix: str, rect: PdfRect) -> list[PaintPlan]:
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-qr-field",
            stroke=_RULE_STRONG,
            fill=_SURFACE,
            line_width_mm=0.45,
        ).plan(surface, rect)
    ]
    grid_step = 22.0
    line_index = 0
    x_mm = rect.x_mm + grid_step
    while x_mm < rect.right_mm:
        plans.append(
            Rule(
                component_id=f"{prefix}-qr-field-v-{line_index}", color=PdfColor(236, 243, 245)
            ).plan(
                surface,
                PdfRect(x_mm, rect.y_mm, 0.18, rect.height_mm),
            )
        )
        x_mm += grid_step
        line_index += 1
    y_mm = rect.y_mm + grid_step
    while y_mm < rect.bottom_mm:
        plans.append(
            Rule(
                component_id=f"{prefix}-qr-field-h-{line_index}", color=PdfColor(236, 243, 245)
            ).plan(
                surface,
                PdfRect(rect.x_mm, y_mm, rect.width_mm, 0.18),
            )
        )
        y_mm += grid_step
        line_index += 1
    return plans


def _qr_image_plans(
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
    image_size = min(_QR_IMAGE_SIZE_MM, rect.width_mm - 1.6, image_area_height - 1.6)
    if image_size < _MIN_QR_IMAGE_SIZE_MM:
        raise ValueError("Maritime QR card cannot preserve the readable QR image minimum")
    image_rect = PdfRect(
        rect.x_mm + (rect.width_mm - image_size) / 2.0,
        rect.y_mm + label_height + (image_area_height - image_size) / 2.0,
        image_size,
        image_size,
    )
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-qr-card-bg-{item.payload_index}",
            fill=_WHITE,
            line_width_mm=0.2,
        ).plan(surface, rect),
        ImageBox(
            component_id=f"{prefix}-qr-image-{item.payload_index}",
            image=item.image,
            image_type="PNG",
        ).plan(surface, image_rect),
    ]
    if label_prefix:
        if label_total is None or label_total <= 0:
            raise ValueError("Maritime QR card label total must be positive")
        plans.append(
            TextBox(
                component_id=f"{prefix}-qr-label-{item.payload_index}",
                text=(f"{label_prefix} {item.label_index:02d} / {label_total:02d}").upper(),
                style=monospace_text_style(
                    size_pt=6.7,
                    bold=True,
                    color=_STAMP,
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
        raise ValueError("Maritime fallback number gutter leaves no payload width")
    plans: list[PaintPlan] = []
    for block_index, block_entries in enumerate(group_fallback_visual_blocks(fallback_page)):
        first_row = block_entries[0].row_index
        last_row = block_entries[-1].row_index
        block_y = area.y_mm + first_row * _FALLBACK_ROW_HEIGHT_MM
        block_h = (last_row - first_row + 1) * _FALLBACK_ROW_HEIGHT_MM
        plans.append(
            Panel(
                component_id=f"{prefix}-fallback-block-{block_index}",
                stroke=_RULE,
                fill=_SURFACE,
                line_width_mm=0.25,
            ).plan(surface, PdfRect(area.x_mm, block_y, area.width_mm, block_h))
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
                            size_pt=6.5,
                            color=_STAMP,
                            char_spacing_mm=0.32,
                        ),
                        policy=TextFitPolicy.SHRINK,
                        min_size_pt=6.0,
                    ).plan(surface, PdfRect(area.x_mm + 5.2, row_y, 48.0, 3.1))
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
                        PdfRect(number_x_mm, row_y + 0.3, number_width_mm, 2.8),
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


def _resolve_maritime_shard_fallback(
    surface: PdfSurface,
    inputs: RenderInputs,
    *,
    area: PdfRect,
) -> tuple[_MaritimeShardFallbackLayout, tuple[FallbackSectionLines, ...]]:
    candidates = (
        (1, _FALLBACK_ROW_HEIGHT_MM, 8.5, 6.5),
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
        layout = _MaritimeShardFallbackLayout(
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
    raise ValueError("Maritime shard fallback payload exceeds the responsive one-page capacity")


def _shard_fallback_column_width(area: PdfRect, *, columns: int) -> float:
    if columns <= 0:
        raise ValueError("Maritime shard fallback columns must be positive")
    column_width_mm = (area.width_mm - (columns - 1) * _SHARD_FALLBACK_COLUMN_GAP_MM) / columns
    if column_width_mm <= 0:
        raise ValueError("Maritime shard fallback columns have no usable width")
    return column_width_mm


def _shard_fallback_capacity(
    area: PdfRect,
    *,
    layout: _MaritimeShardFallbackLayout,
) -> int:
    rows_per_column = math.floor(area.height_mm / layout.row_height_mm)
    if rows_per_column <= 0:
        raise ValueError("Maritime shard fallback area must fit at least one row per column")
    return rows_per_column * layout.columns


def _visible_shard_fallback_area(
    fallback_page: FallbackPage,
    *,
    area: PdfRect,
    layout: _MaritimeShardFallbackLayout,
) -> PdfRect:
    rows_per_column = math.floor(area.height_mm / layout.row_height_mm)
    if rows_per_column <= 0 or not fallback_page.entries:
        raise ValueError("Maritime shard fallback area has no visible rows")
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
    layout: _MaritimeShardFallbackLayout,
) -> list[PaintPlan]:
    rows_per_column = math.floor(area.height_mm / layout.row_height_mm)
    column_width_mm = _shard_fallback_column_width(area, columns=layout.columns)
    if rows_per_column <= 0 or column_width_mm <= 0:
        raise ValueError("Maritime shard fallback columns have no usable area")
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
            stroke=_RULE,
            fill=_SURFACE,
            line_width_mm=0.25,
        ).plan(surface, visible_area)
    ]
    for column_index, block_entries in _shard_fallback_column_blocks(
        fallback_page,
        rows_per_column=rows_per_column,
        columns=layout.columns,
    ):
        column_x_mm = area.x_mm + column_index * (column_width_mm + _SHARD_FALLBACK_COLUMN_GAP_MM)
        number_x_mm = column_x_mm + 1.3
        payload_x_mm = number_x_mm + number_width_mm + 0.8
        payload_width_mm = column_x_mm + column_width_mm - payload_x_mm - 1.2
        if payload_width_mm <= 0:
            raise ValueError("Maritime shard fallback number gutter leaves no payload width")
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
                            color=_STAMP,
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
            raise ValueError("Maritime shard fallback page exceeds its measured column capacity")
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
        raise ValueError("Maritime recovery-kit insert has no usable two-column body")
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
            style=title_text_style(size_pt=7.0, color=_STAMP, char_spacing_mm=0.35),
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
            style=title_text_style(size_pt=8.0, color=_STAMP, char_spacing_mm=0.24),
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
                color=_STAMP,
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
    "MaritimeDirectPlan",
    "build_maritime_kit_direct_plan",
    "build_maritime_main_direct_plan",
    "build_maritime_recovery_direct_plan",
    "build_maritime_shard_direct_plan",
    "build_maritime_signing_key_shard_direct_plan",
    "render_maritime_kit_direct_pdf",
    "render_maritime_main_direct_pdf",
    "render_maritime_recovery_direct_pdf",
    "render_maritime_shard_direct_pdf",
    "render_maritime_signing_key_shard_direct_pdf",
]
