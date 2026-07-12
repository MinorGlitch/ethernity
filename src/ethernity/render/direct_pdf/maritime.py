"""Maritime design rendering through direct PDF primitives."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from ethernity.qr.codec import QrConfig
from ethernity.render.direct_pdf.components import ImageBox, Panel, Rule, TextAlign, TextBox
from ethernity.render.direct_pdf.forge_preview import A4_HEIGHT_MM, A4_WIDTH_MM
from ethernity.render.direct_pdf.page import DirectPdfPagePlan, PaintPlan, build_page_plan
from ethernity.render.direct_pdf.structured_common import (
    FallbackPage,
    FallbackPageEntry,
    FallbackTitleEntry,
    QrPage,
    QrPayloadItem,
    StructuredContext,
    StructuredDirectPlan as MaritimeDirectPlan,
    StructuredPlanBuilder,
    build_artifact_proof,
    build_fallback_proof,
    build_structured_context,
    component_prefix,
    fallback_capacity,
    fallback_entries,
    fallback_sections,
    paginate_fallback_entries,
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
from ethernity.render.direct_pdf.text_fit import TextFitPolicy
from ethernity.render.direct_pdf.types import PdfColor, PdfRect, TextStyle
from ethernity.render.doc_types import (
    DOC_TYPE_KIT,
    DOC_TYPE_MAIN,
    DOC_TYPE_RECOVERY,
    DOC_TYPE_SHARD,
    DOC_TYPE_SIGNING_KEY_SHARD,
)
from ethernity.render.recovery_meta import RecoveryMeta
from ethernity.render.types import RenderInputs, RenderResult

_PAGE_RECT = PdfRect(0.0, 0.0, A4_WIDTH_MM, A4_HEIGHT_MM)
_CONTENT_X_MM = 14.0
_CONTENT_WIDTH_MM = A4_WIDTH_MM - 2 * _CONTENT_X_MM
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
_FALLBACK_GROUP_SIZE = 4
_FALLBACK_LINE_LENGTH = 88
_FALLBACK_ROW_HEIGHT_MM = 4.2


@dataclass(frozen=True)
class _HeaderLayout:
    plans: tuple[PaintPlan, ...]
    content_start_y_mm: float


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

    validate_qr_inputs(inputs, expected_doc_type=DOC_TYPE_MAIN)
    payloads = resolved_qr_payloads(inputs)
    items = qr_payload_items(payloads, config=inputs.qr_config or QrConfig())
    qr_pages = paginate_qr_items(items, capacity=_QR_COLUMNS * _QR_ROWS_PER_PAGE)
    context = build_structured_context(inputs, doc_type=DOC_TYPE_MAIN)
    page_plans = tuple(
        _build_qr_page(
            surface,
            context,
            qr_page,
            component_base="maritime-main",
            total_pages=len(qr_pages),
            include_subtitle=False,
            include_instructions=True,
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

    validate_recovery_inputs(inputs)
    recovery_meta = inputs.recovery_meta or RecoveryMeta()
    context = build_structured_context(inputs, doc_type=DOC_TYPE_RECOVERY)
    sections = fallback_sections(
        inputs.fallback_sections or (),
        group_size=_FALLBACK_GROUP_SIZE,
        line_length=_FALLBACK_LINE_LENGTH,
    )
    fallback_area = PdfRect(14.0, 86.0, 182.0, 190.0)
    fallback_pages = paginate_fallback_entries(
        fallback_entries(sections),
        capacity=fallback_capacity(fallback_area, row_height_mm=_FALLBACK_ROW_HEIGHT_MM),
    )
    page_plans = tuple(
        _build_recovery_page(
            surface,
            context,
            recovery_meta,
            fallback_page,
            total_pages=len(fallback_pages),
        )
        for fallback_page in fallback_pages
    )
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

    validate_qr_inputs(inputs, expected_doc_type=DOC_TYPE_KIT)
    payloads = resolved_qr_payloads(inputs)
    items = qr_payload_items(payloads, config=inputs.qr_config or QrConfig())
    qr_pages = paginate_qr_items(items, capacity=_QR_COLUMNS * _QR_ROWS_PER_PAGE)
    context = build_structured_context(inputs, doc_type=DOC_TYPE_KIT)
    total_pages = len(qr_pages) + 1
    page_plans = tuple(
        _build_qr_page(
            surface,
            context,
            qr_page,
            component_base="maritime-kit",
            total_pages=total_pages,
            include_subtitle=False,
            include_instructions=False,
        )
        for qr_page in qr_pages
    )
    page_plans = (
        *page_plans,
        _build_kit_instruction_page(surface, context, page_number=total_pages),
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
    validate_single_qr_fallback_inputs(inputs, expected_doc_type=expected_doc_type)
    payload = resolved_single_qr_payload(inputs)
    rendered_qr = qr_image(payload, config=inputs.qr_config or QrConfig())
    context = build_structured_context(inputs, doc_type=expected_doc_type)
    sections = fallback_sections(
        inputs.fallback_sections or (),
        group_size=_FALLBACK_GROUP_SIZE,
        line_length=_FALLBACK_LINE_LENGTH,
    )
    fallback_area = PdfRect(14.0, 238.0, 182.0, 38.0)
    fallback_pages = paginate_fallback_entries(
        fallback_entries(sections),
        capacity=fallback_capacity(fallback_area, row_height_mm=_FALLBACK_ROW_HEIGHT_MM),
    )
    page_plans = tuple(
        _build_shard_page(
            surface,
            context,
            fallback_page,
            qr_image_bytes=rendered_qr,
            fallback_area=fallback_area,
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


def _build_qr_page(
    surface: PdfSurface,
    context: StructuredContext,
    qr_page: QrPage,
    *,
    component_base: str,
    total_pages: int,
    include_subtitle: bool,
    include_instructions: bool,
) -> DirectPdfPagePlan:
    prefix = component_prefix(component_base, qr_page.page_number)
    page_label = f"Page {qr_page.page_number} / {total_pages}"
    plans: list[PaintPlan] = []
    plans.extend(_page_background(surface, prefix=prefix))
    header = _header_layout(
        surface,
        context,
        prefix=prefix,
        page_label=page_label,
        include_subtitle=include_subtitle,
    )
    plans.extend(header.plans)
    qr_top = header.content_start_y_mm + 6.0
    if include_instructions:
        instruction_rect = PdfRect(14.0, header.content_start_y_mm + 3.0, 182.0, 15.5)
        plans.extend(_instructions_plans(surface, context, prefix=prefix, rect=instruction_rect))
        qr_top = instruction_rect.y_mm + instruction_rect.height_mm + 4.0
    plans.extend(_qr_field_plans(surface, qr_page, prefix=prefix, top_mm=qr_top))
    return build_page_plan(page_number=qr_page.page_number, rect=_PAGE_RECT, plans=plans)


def _build_recovery_page(
    surface: PdfSurface,
    context: StructuredContext,
    recovery_meta: RecoveryMeta,
    fallback_page: FallbackPage,
    *,
    total_pages: int,
) -> DirectPdfPagePlan:
    prefix = component_prefix("maritime-recovery", fallback_page.page_number)
    page_label = f"Page {fallback_page.page_number} / {total_pages}"
    fallback_area = PdfRect(14.0, 86.0, 182.0, 190.0)
    plans: list[PaintPlan] = []
    plans.extend(_page_background(surface, prefix=prefix))
    header = _header_layout(
        surface,
        context,
        prefix=prefix,
        page_label=page_label,
        include_subtitle=True,
        rows=_recovery_meta_rows(recovery_meta),
    )
    plans.extend(header.plans)
    instructions = PdfRect(14.0, header.content_start_y_mm + 1.0, 182.0, 17.0)
    plans.extend(_instructions_plans(surface, context, prefix=prefix, rect=instructions))
    plans.extend(_fallback_block_plans(surface, fallback_page, prefix=prefix, area=fallback_area))
    return build_page_plan(page_number=fallback_page.page_number, rect=_PAGE_RECT, plans=plans)


def _build_shard_page(
    surface: PdfSurface,
    context: StructuredContext,
    fallback_page: FallbackPage,
    *,
    qr_image_bytes: bytes,
    fallback_area: PdfRect,
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
    plans.extend(_page_background(surface, prefix=prefix))
    header = _header_layout(
        surface,
        context,
        prefix=prefix,
        page_label=page_label,
        include_subtitle=True,
        rows=(("Shard", f"{shard_index} / {shard_total}"),),
    )
    plans.extend(header.plans)
    instructions = PdfRect(14.0, header.content_start_y_mm + 8.0, 182.0, 18.0)
    plans.extend(_instructions_plans(surface, context, prefix=prefix, rect=instructions))
    plans.extend(
        _single_qr_field_plans(
            surface,
            qr_image_bytes=qr_image_bytes,
            prefix=prefix,
            rect=PdfRect(76.0, 128.0, 58.0, 58.0),
        )
    )
    plans.extend(_fallback_block_plans(surface, fallback_page, prefix=prefix, area=fallback_area))
    return build_page_plan(page_number=fallback_page.page_number, rect=_PAGE_RECT, plans=plans)


def _build_kit_instruction_page(
    surface: PdfSurface,
    context: StructuredContext,
    *,
    page_number: int,
) -> DirectPdfPagePlan:
    prefix = component_prefix("maritime-kit", page_number)
    plans: list[PaintPlan] = []
    plans.extend(_page_background(surface, prefix=prefix))
    plans.extend(
        _instruction_insert_plans(
            surface,
            context,
            prefix=prefix,
            rect=PdfRect(14.0, 14.0, 182.0, 269.0),
        )
    )
    return build_page_plan(page_number=page_number, rect=_PAGE_RECT, plans=plans)


def _page_background(surface: PdfSurface, *, prefix: str) -> list[PaintPlan]:
    return [
        Panel(component_id=f"{prefix}-page-bg", fill=_PAPER, line_width_mm=0.2).plan(
            surface, _PAGE_RECT
        )
    ]


def _header_layout(
    surface: PdfSurface,
    context: StructuredContext,
    *,
    prefix: str,
    page_label: str,
    include_subtitle: bool,
    rows: Sequence[tuple[str, str]] = (),
) -> _HeaderLayout:
    plans: list[PaintPlan] = [
        TextBox(
            component_id=f"{prefix}-title",
            text=str(context.copy.get("title") or "Document").upper(),
            style=_title_style(size_pt=15.5, char_spacing_mm=0.26),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=11.0,
        ).plan(surface, PdfRect(14.0, 14.4, 114.0, 7.0)),
    ]
    meta_y = 23.0
    if include_subtitle:
        plans.append(
            TextBox(
                component_id=f"{prefix}-subtitle",
                text=str(context.copy.get("subtitle") or "").upper(),
                style=_body_style(size_pt=8.0, color=_INK_MUTED, char_spacing_mm=0.26),
                policy=TextFitPolicy.SHRINK,
                min_size_pt=6.0,
            ).plan(surface, PdfRect(14.0, 23.0, 112.0, 4.0))
        )
        meta_y = 32.0

    meta_rows = (("Document ID", context.doc_id), *rows, ("Page", page_label))
    cursor_y = meta_y
    for index, (label, value) in enumerate(meta_rows):
        row_h = _meta_row_height(value)
        plans.append(
            TextBox(
                component_id=f"{prefix}-meta-label-{index}",
                text=label.upper(),
                style=_title_style(size_pt=6.0, color=_INK_SOFT, char_spacing_mm=0.32),
                policy=TextFitPolicy.SHRINK,
                min_size_pt=4.8,
            ).plan(surface, PdfRect(14.0, cursor_y, 24.0, 3.1))
        )
        plans.append(
            TextBox(
                component_id=f"{prefix}-meta-value-{index}",
                text=value,
                style=_mono_style(size_pt=7.2, color=_INK, char_spacing_mm=0.08),
                policy=TextFitPolicy.SHRINK if row_h <= 5.0 else TextFitPolicy.WRAP,
                min_size_pt=4.5,
                line_height_multiplier=1.1,
            ).plan(surface, PdfRect(43.0, cursor_y, 72.0, row_h))
        )
        cursor_y += row_h + 1.2

    plans.extend(_stamp_plans(surface, context, prefix=prefix))
    minimum_start_y = 43.0 if include_subtitle else 34.0
    return _HeaderLayout(
        plans=tuple(plans),
        content_start_y_mm=max(minimum_start_y, cursor_y + 1.0),
    )


def _stamp_plans(
    surface: PdfSurface,
    context: StructuredContext,
    *,
    prefix: str,
) -> list[PaintPlan]:
    stamp = PdfRect(148.0, 14.0, 48.0, 18.0)
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
            style=_title_style(size_pt=7.0, color=_STAMP, char_spacing_mm=0.24),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=5.4,
        ).plan(surface, PdfRect(stamp.x_mm + 3.0, stamp.y_mm + 3.0, stamp.width_mm - 6.0, 3.2)),
        TextBox(
            component_id=f"{prefix}-stamp-value",
            text=context.created_timestamp_utc,
            style=_title_style(size_pt=8.8, char_spacing_mm=0.16),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=5.8,
        ).plan(surface, PdfRect(stamp.x_mm + 3.0, stamp.y_mm + 8.8, stamp.width_mm - 6.0, 4.5)),
    ]


def _recovery_meta_rows(recovery_meta: RecoveryMeta) -> tuple[tuple[str, str], ...]:
    rows: list[tuple[str, str]] = []
    if recovery_meta.quorum_value:
        rows.append((recovery_meta.quorum_label or "Shard Quorum", recovery_meta.quorum_value))
    if recovery_meta.signing_pub_lines:
        rows.append(("Signing Pub Key", " ".join(recovery_meta.signing_pub_lines)))
    if recovery_meta.passphrase_lines:
        rows.append(("Passphrase", " ".join(recovery_meta.passphrase_lines)))
    return tuple(rows)


def _meta_row_height(value: str) -> float:
    if len(value) > 86:
        return 8.4
    if len(value) > 56:
        return 6.6
    return 3.7


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
            style=_title_style(size_pt=6.5, color=_STAMP, char_spacing_mm=0.32),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=5.0,
        ).plan(surface, PdfRect(rect.x_mm + 3.0, rect.y_mm + 2.0, 29.0, 3.2)),
    ]
    y_mm = rect.y_mm + 2.0
    for index, line in enumerate(context.instruction_lines):
        plans.append(
            TextBox(
                component_id=f"{prefix}-instruction-line-{index}",
                text=line,
                style=_body_style(size_pt=8.8, color=_INK),
                policy=TextFitPolicy.WRAP,
                line_height_multiplier=1.16,
            ).plan(surface, PdfRect(rect.x_mm + 39.0, y_mm, rect.width_mm - 43.0, 4.6))
        )
        y_mm += 4.5
    return plans


def _qr_field_plans(
    surface: PdfSurface,
    qr_page: QrPage,
    *,
    prefix: str,
    top_mm: float,
) -> list[PaintPlan]:
    grid_width = _QR_COLUMNS * _QR_CARD_SIZE_MM + (_QR_COLUMNS - 1) * _QR_CARD_GAP_MM
    row_count = math.ceil(len(qr_page.items) / _QR_COLUMNS)
    grid_height = row_count * _QR_CARD_SIZE_MM + max(0, row_count - 1) * _QR_CARD_GAP_MM
    start_x = _CONTENT_X_MM + max(0.0, (_CONTENT_WIDTH_MM - grid_width) / 2.0)
    outline = PdfRect(start_x - 2.0, top_mm - 2.0, grid_width + 4.0, grid_height + 4.0)
    plans = _qr_field_background(surface, prefix=prefix, rect=outline)
    for slot_index, item in enumerate(qr_page.items):
        row = math.floor(slot_index / _QR_COLUMNS)
        col = slot_index % _QR_COLUMNS
        rect = PdfRect(
            start_x + col * (_QR_CARD_SIZE_MM + _QR_CARD_GAP_MM),
            top_mm + row * (_QR_CARD_SIZE_MM + _QR_CARD_GAP_MM),
            _QR_CARD_SIZE_MM,
            _QR_CARD_SIZE_MM,
        )
        plans.extend(_qr_image_plans(surface, item, prefix=prefix, rect=rect))
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
) -> list[PaintPlan]:
    image_size = min(_QR_IMAGE_SIZE_MM, rect.width_mm - 1.6, rect.height_mm - 1.6)
    image_rect = PdfRect(
        rect.x_mm + (rect.width_mm - image_size) / 2.0,
        rect.y_mm + (rect.height_mm - image_size) / 2.0,
        image_size,
        image_size,
    )
    return [
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


def _fallback_block_plans(
    surface: PdfSurface,
    fallback_page: FallbackPage,
    *,
    prefix: str,
    area: PdfRect,
) -> list[PaintPlan]:
    plans: list[PaintPlan] = []
    for block_index, block_entries in enumerate(_fallback_visual_blocks(fallback_page)):
        first_row = block_entries[0].row_index
        last_row = block_entries[-1].row_index
        block_y = area.y_mm + first_row * _FALLBACK_ROW_HEIGHT_MM + block_index * 1.6
        block_h = (last_row - first_row + 1) * _FALLBACK_ROW_HEIGHT_MM + 2.2
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
            row_y = block_y + 1.2 + local_index * _FALLBACK_ROW_HEIGHT_MM
            if isinstance(entry, FallbackTitleEntry):
                plans.append(
                    TextBox(
                        component_id=f"{prefix}-fallback-title-{entry.section_index}",
                        text=entry.title.upper(),
                        style=_title_style(size_pt=6.5, color=_STAMP, char_spacing_mm=0.32),
                        policy=TextFitPolicy.SHRINK,
                        min_size_pt=5.0,
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
                        style=_mono_style(size_pt=5.8, color=_INK_SOFT, char_spacing_mm=0.08),
                        policy=TextFitPolicy.FAIL,
                        align=TextAlign.RIGHT,
                    ).plan(surface, PdfRect(area.x_mm + 4.0, row_y + 0.3, 6.0, 2.5))
                )
                plans.append(
                    TextBox(
                        component_id=(
                            f"{prefix}-fallback-line-{entry.section_index}-{entry.line_number}"
                        ),
                        text=entry.text,
                        style=_mono_style(size_pt=8.5, color=_INK),
                        policy=TextFitPolicy.SHRINK,
                        min_size_pt=6.0,
                    ).plan(surface, PdfRect(area.x_mm + 14.0, row_y, area.width_mm - 18.0, 3.8))
                )
    return plans


def _fallback_visual_blocks(
    fallback_page: FallbackPage,
) -> tuple[tuple[FallbackPageEntry, ...], ...]:
    blocks: list[list[FallbackPageEntry]] = []
    current: list[FallbackPageEntry] = []
    for page_entry in fallback_page.entries:
        if isinstance(page_entry.entry, FallbackTitleEntry) and current:
            blocks.append(current)
            current = []
        current.append(page_entry)
    if current:
        blocks.append(current)
    return tuple(tuple(block) for block in blocks)


def _instruction_insert_plans(
    surface: PdfSurface,
    context: StructuredContext,
    *,
    prefix: str,
    rect: PdfRect,
) -> list[PaintPlan]:
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
            style=_title_style(size_pt=7.0, color=_STAMP, char_spacing_mm=0.35),
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.CENTER,
            min_size_pt=5.4,
        ).plan(surface, PdfRect(147.0, 18.0, 39.0, 5.4)),
        TextBox(
            component_id=f"{prefix}-insert-title",
            text="HOW TO REBUILD THE RECOVERY KIT",
            style=_title_style(size_pt=15.0, char_spacing_mm=0.26),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=11.0,
        ).plan(surface, PdfRect(22.0, 23.0, 141.0, 8.0)),
        TextBox(
            component_id=f"{prefix}-insert-subtitle",
            text="Use this page after scanning the QR pages. Keep everything offline.",
            style=_body_style(size_pt=9.0, color=_INK_MUTED, char_spacing_mm=0.08),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=7.0,
        ).plan(surface, PdfRect(22.0, 34.0, 145.0, 4.5)),
        Rule(component_id=f"{prefix}-insert-hero-rule", color=_RULE_STRONG).plan(
            surface,
            PdfRect(22.0, 42.2, 166.0, 0.55),
        ),
    ]
    plans.extend(
        _instruction_steps_section(
            surface,
            prefix=prefix,
            title="Scan + Assemble",
            lines=(
                "Scan every QR code left to right, top to bottom.",
                "Save each decoded chunk in order. Do not insert spaces or blank lines.",
                "Concatenate the chunks into one continuous file.",
                "Name the file exactly: recovery_kit.bundle.html",
            ),
            rect=PdfRect(22.0, 51.0, 94.0, 64.0),
            index=1,
        )
    )
    plans.extend(
        _instruction_steps_section(
            surface,
            prefix=prefix,
            title="Open the Kit",
            lines=(
                "Open recovery_kit.bundle.html in a browser while offline.",
                "If the file is large, wait for it to finish loading.",
                "Follow the on-screen prompts to recover your payload.",
            ),
            rect=PdfRect(22.0, 104.0, 94.0, 52.0),
            index=2,
        )
    )
    plans.extend(
        _instruction_bullets_section(
            surface,
            prefix=prefix,
            title="Troubleshooting",
            lines=(
                "If the kit does not load, re-check chunk order and re-save the file.",
                "Try another browser if rendering stalls.",
                "Confirm the file size matches the sum of all QR chunks.",
            ),
            rect=PdfRect(22.0, 151.0, 94.0, 44.0),
            index=3,
        )
    )
    plans.extend(
        _instruction_callout_plans(
            surface,
            prefix=prefix,
            rect=PdfRect(124.0, 51.0, 58.0, 33.0),
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
            rect=PdfRect(124.0, 91.0, 58.0, 33.0),
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
            rect=PdfRect(124.0, 131.0, 58.0, 30.0),
            title="Security",
            lines=(
                "Work offline and on a trusted machine.",
                "Delete temporary files after recovery.",
            ),
            index=3,
        )
    )
    plans.extend(
        _instruction_checklist_plans(
            surface,
            prefix=prefix,
            rect=PdfRect(124.0, 169.0, 58.0, 56.0),
        )
    )
    plans.extend(_instruction_insert_footer(surface, context, prefix=prefix))
    return plans


def _instruction_steps_section(
    surface: PdfSurface,
    *,
    prefix: str,
    title: str,
    lines: Sequence[str],
    rect: PdfRect,
    index: int,
) -> list[PaintPlan]:
    plans = _instruction_section_label(surface, prefix=prefix, title=title, rect=rect, index=index)
    y_mm = rect.y_mm + 12.0
    for line_index, line in enumerate(lines):
        plans.append(
            Panel(
                component_id=f"{prefix}-step-icon-{index}-{line_index}",
                stroke=_RULE_STRONG,
                fill=_TAB,
                line_width_mm=0.35,
            ).plan(surface, PdfRect(rect.x_mm, y_mm + 0.6, 4.0, 4.0))
        )
        plans.append(
            Panel(
                component_id=f"{prefix}-step-icon-inner-{index}-{line_index}",
                stroke=_RULE,
                fill=None,
                line_width_mm=0.25,
            ).plan(surface, PdfRect(rect.x_mm + 0.7, y_mm + 1.3, 2.6, 2.6))
        )
        text_plan = TextBox(
            component_id=f"{prefix}-step-text-{index}-{line_index}",
            text=line,
            style=_body_style(size_pt=8.8),
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=1.24,
        ).plan(surface, PdfRect(rect.x_mm + 8.0, y_mm - 0.3, rect.width_mm - 8.0, 13.0))
        plans.append(text_plan)
        y_mm += max(9.0, text_plan.proof.used_rect.height_mm + 2.0)
    return plans


def _instruction_bullets_section(
    surface: PdfSurface,
    *,
    prefix: str,
    title: str,
    lines: Sequence[str],
    rect: PdfRect,
    index: int,
) -> list[PaintPlan]:
    plans = _instruction_section_label(surface, prefix=prefix, title=title, rect=rect, index=index)
    y_mm = rect.y_mm + 12.0
    for line_index, line in enumerate(lines):
        plans.append(
            Panel(
                component_id=f"{prefix}-bullet-marker-{index}-{line_index}",
                fill=_INK,
                line_width_mm=0.2,
            ).plan(surface, PdfRect(rect.x_mm + 1.2, y_mm + 1.7, 0.8, 0.8))
        )
        text_plan = TextBox(
            component_id=f"{prefix}-bullet-text-{index}-{line_index}",
            text=line,
            style=_body_style(size_pt=8.8),
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=1.25,
        ).plan(surface, PdfRect(rect.x_mm + 6.0, y_mm - 0.2, rect.width_mm - 6.0, 12.0))
        plans.append(text_plan)
        y_mm += max(8.4, text_plan.proof.used_rect.height_mm + 1.8)
    return plans


def _instruction_section_label(
    surface: PdfSurface,
    *,
    prefix: str,
    title: str,
    rect: PdfRect,
    index: int,
) -> list[PaintPlan]:
    label_rect = PdfRect(rect.x_mm, rect.y_mm, rect.width_mm, 6.0)
    return [
        Panel(
            component_id=f"{prefix}-section-label-box-{index}",
            stroke=_STAMP,
            fill=PdfColor(235, 244, 246),
            line_width_mm=0.35,
        ).plan(surface, label_rect),
        TextBox(
            component_id=f"{prefix}-section-label-{index}",
            text=title.upper(),
            style=_title_style(size_pt=8.0, color=_STAMP, char_spacing_mm=0.28),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(
            surface,
            PdfRect(
                label_rect.x_mm + 1.4,
                label_rect.y_mm + 1.15,
                label_rect.width_mm - 2.8,
                3.8,
            ),
        ),
    ]


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
            style=_title_style(size_pt=8.0, color=_STAMP, char_spacing_mm=0.24),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(rect.x_mm + 3.0, rect.y_mm + 3.0, rect.width_mm - 6.0, 3.5)),
    ]
    y_mm = rect.y_mm + 10.0
    for line_index, line in enumerate(lines):
        text_plan = TextBox(
            component_id=f"{prefix}-callout-line-{index}-{line_index}",
            text=line,
            style=_body_style(size_pt=8.4),
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=1.2,
        ).plan(surface, PdfRect(rect.x_mm + 3.0, y_mm, rect.width_mm - 6.0, 10.0))
        plans.append(text_plan)
        y_mm += max(7.2, text_plan.proof.used_rect.height_mm + 1.6)
    return plans


def _instruction_checklist_plans(
    surface: PdfSurface,
    *,
    prefix: str,
    rect: PdfRect,
) -> list[PaintPlan]:
    lines = (
        "All QR pages scanned in order.",
        "Bundle file saved with the correct name.",
        "Kit opens offline without errors.",
        "Recovery completed and data verified.",
    )
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-checklist",
            stroke=_RULE,
            fill=_WHITE,
            line_width_mm=0.35,
        ).plan(surface, rect)
    ]
    y_mm = rect.y_mm + 4.0
    for line_index, line in enumerate(lines):
        plans.append(
            Panel(
                component_id=f"{prefix}-check-box-{line_index}",
                stroke=_RULE_STRONG,
                fill=_WHITE,
                line_width_mm=0.35,
            ).plan(surface, PdfRect(rect.x_mm + 3.0, y_mm + 0.4, 3.4, 3.4))
        )
        text_plan = TextBox(
            component_id=f"{prefix}-check-text-{line_index}",
            text=line,
            style=_body_style(size_pt=8.2),
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=1.18,
        ).plan(surface, PdfRect(rect.x_mm + 9.0, y_mm - 0.1, rect.width_mm - 12.0, 10.0))
        plans.append(text_plan)
        y_mm += max(10.0, text_plan.proof.used_rect.height_mm + 2.0)
    return plans


def _instruction_insert_footer(
    surface: PdfSurface,
    context: StructuredContext,
    *,
    prefix: str,
) -> list[PaintPlan]:
    return [
        Rule(component_id=f"{prefix}-insert-footer-rule", color=_RULE_STRONG).plan(
            surface,
            PdfRect(22.0, 266.0, 166.0, 0.55),
        ),
        TextBox(
            component_id=f"{prefix}-insert-footer-kind",
            text="RECOVERY KIT: OFFLINE HTML BUNDLE",
            style=_body_style(size_pt=8.0, color=_INK_MUTED, char_spacing_mm=0.2),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(22.0, 271.2, 78.0, 4.2)),
        TextBox(
            component_id=f"{prefix}-insert-footer-doc",
            text=f"Document ID: {context.doc_id}",
            style=_mono_style(size_pt=7.0, color=_INK, char_spacing_mm=0.06),
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.RIGHT,
            min_size_pt=5.4,
        ).plan(surface, PdfRect(102.0, 271.2, 86.0, 4.2)),
    ]


def _title_style(
    *,
    size_pt: float,
    color: PdfColor = _INK,
    char_spacing_mm: float = 0.2,
) -> TextStyle:
    return TextStyle(
        family="Times",
        size_pt=size_pt,
        style="B",
        color=color,
        char_spacing_mm=char_spacing_mm,
    )


def _body_style(
    *,
    size_pt: float,
    color: PdfColor = _INK,
    bold: bool = False,
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
