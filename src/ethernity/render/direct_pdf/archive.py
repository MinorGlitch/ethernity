"""Archive design rendering through direct PDF primitives."""

from __future__ import annotations

import math
from collections.abc import Sequence

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
from ethernity.render.direct_pdf.forge_preview import A4_HEIGHT_MM, A4_WIDTH_MM
from ethernity.render.direct_pdf.page import DirectPdfPagePlan, PaintPlan, build_page_plan
from ethernity.render.direct_pdf.structured_common import (
    FallbackPage as _FallbackPage,
    FallbackTitleEntry as _FallbackTitleEntry,
    QrPage as _QrPage,
    QrPayloadItem as _QrPayloadItem,
    StructuredContext as _ArchiveContext,
    StructuredDirectPlan as ArchiveDirectPlan,
    StructuredPlanBuilder,
    build_artifact_proof as build_render_artifact_proof,
    build_fallback_proof as _build_fallback_proof,
    build_structured_context as _build_archive_context,
    component_prefix as _component_prefix,
    fallback_capacity as _fallback_capacity,
    fallback_entries as _fallback_entries,
    fallback_sections as _fallback_sections,
    paginate_fallback_entries as _paginate_fallback_entries,
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
_MARGIN_MM = 14.0
_CONTENT_X_MM = 14.0
_CONTENT_WIDTH_MM = A4_WIDTH_MM - 2 * _CONTENT_X_MM
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
_QR_ROWS_PER_PAGE = 3
_QR_CARD_SIZE_MM = 58.0
_QR_CARD_GAP_MM = 3.2
_QR_IMAGE_SIZE_MM = 50.5
_KIT_QR_CARD_SIZE_MM = 56.5
_KIT_QR_IMAGE_SIZE_MM = 44.0
_FALLBACK_GROUP_SIZE = 4
_FALLBACK_LINE_LENGTH = 88
_FALLBACK_ROW_HEIGHT_MM = 4.25
_ICON_HUB = chr(0xE9F4)
_ICON_LANGUAGE = chr(0xE894)
_ICON_BUILD = chr(0xE869)
_ICON_ADJUST = chr(0xE39E)
_ICON_CHECK_BOX = chr(0xE835)
_ICON_VERIFIED_USER = chr(0xE8E8)
_ICON_LOCK = chr(0xE897)


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
    qr_pages = _paginate_qr_items(items, capacity=_QR_COLUMNS * _QR_ROWS_PER_PAGE)
    context = _build_archive_context(inputs, doc_type=DOC_TYPE_MAIN)
    page_plans = tuple(
        _build_main_qr_page(surface, context, qr_page, total_pages=len(qr_pages))
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
    sections = _fallback_sections(
        inputs.fallback_sections or (),
        group_size=_FALLBACK_GROUP_SIZE,
        line_length=_FALLBACK_LINE_LENGTH,
    )
    fallback_pages = _paginate_fallback_entries(
        _fallback_entries(sections),
        capacity=_fallback_capacity(
            PdfRect(16.0, 79.0, 178.0, 181.0),
            row_height_mm=_FALLBACK_ROW_HEIGHT_MM,
        ),
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
    payloads = _resolved_qr_payloads(inputs)
    items = _qr_payload_items(payloads, config=inputs.qr_config or QrConfig())
    qr_pages = _paginate_qr_items(items, capacity=_QR_COLUMNS * _QR_ROWS_PER_PAGE)
    context = _build_archive_context(inputs, doc_type=DOC_TYPE_KIT)
    total_pages = len(qr_pages) + 1
    page_plans = tuple(
        _build_kit_qr_page(surface, context, qr_page, total_pages=total_pages)
        for qr_page in qr_pages
    )
    page_plans = (
        *page_plans,
        _build_kit_instruction_page(surface, context, page_number=total_pages),
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
    payload = _resolved_single_qr_payload(inputs)
    qr_image = _qr_image(payload, config=inputs.qr_config or QrConfig())
    context = _build_archive_context(inputs, doc_type=expected_doc_type)
    sections = _fallback_sections(
        inputs.fallback_sections or (),
        group_size=_FALLBACK_GROUP_SIZE,
        line_length=_FALLBACK_LINE_LENGTH,
    )
    fallback_area = PdfRect(14.0, 254.0, 182.0, 22.5)
    fallback_pages = _paginate_fallback_entries(
        _fallback_entries(sections),
        capacity=_fallback_capacity(fallback_area, row_height_mm=_FALLBACK_ROW_HEIGHT_MM),
    )
    page_plans = tuple(
        _build_single_qr_fallback_page(
            surface,
            context,
            fallback_page,
            qr_image=qr_image,
            fallback_area=fallback_area,
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
    total_pages: int,
) -> DirectPdfPagePlan:
    page_label = f"Page {qr_page.page_number} / {total_pages}"
    prefix = _component_prefix("archive-main", qr_page.page_number)
    plans: list[PaintPlan] = []
    plans.extend(_archive_page_background(surface, prefix=prefix))
    plans.extend(
        _main_header_plans(
            surface,
            context,
            prefix=prefix,
            page_label=page_label,
        )
    )
    if qr_page.page_number == 1:
        plans.extend(
            _instructions_panel_plans(
                surface, context, prefix=prefix, rect=PdfRect(14.0, 31.5, 182.0, 20.0)
            )
        )
        plans.append(
            Rule(component_id=f"{prefix}-qr-rule", color=_RULE_DARK).plan(
                surface, PdfRect(14.0, 54.0, 182.0, 0.5)
            )
        )
        qr_top = 56.5
    else:
        plans.append(
            Rule(component_id=f"{prefix}-qr-rule", color=_RULE_DARK).plan(
                surface, PdfRect(14.0, 34.0, 182.0, 0.5)
            )
        )
        qr_top = 38.0
    plans.extend(
        _qr_grid_plans(
            surface,
            qr_page,
            prefix=prefix,
            top_mm=qr_top,
            card_size_mm=_QR_CARD_SIZE_MM,
            image_size_mm=_QR_IMAGE_SIZE_MM,
            label_prefix=None,
        )
    )
    plans.extend(_footer_plans(surface, context, prefix=prefix, page_label=page_label))
    return build_page_plan(page_number=qr_page.page_number, rect=_PAGE_RECT, plans=plans)


def _build_recovery_page(
    surface: PdfSurface,
    context: _ArchiveContext,
    recovery_meta: RecoveryMeta,
    fallback_page: _FallbackPage,
    *,
    total_pages: int,
) -> DirectPdfPagePlan:
    page_label = f"Page {fallback_page.page_number} / {total_pages}"
    prefix = _component_prefix("archive-recovery", fallback_page.page_number)
    fallback_area = PdfRect(16.0, 79.0, 178.0, 181.0)
    plans: list[PaintPlan] = []
    plans.extend(_archive_page_background(surface, prefix=prefix))
    plans.extend(_recovery_header_plans(surface, context, recovery_meta, prefix=prefix))
    plans.extend(
        _instructions_panel_plans(
            surface, context, prefix=prefix, rect=PdfRect(14.0, 49.0, 182.0, 15.0)
        )
    )
    plans.extend(
        _recovery_fallback_plans(surface, fallback_page, prefix=prefix, area=fallback_area)
    )
    plans.extend(_recovery_validation_plans(surface, prefix=prefix))
    plans.extend(_footer_plans(surface, context, prefix=prefix, page_label=page_label))
    return build_page_plan(page_number=fallback_page.page_number, rect=_PAGE_RECT, plans=plans)


def _build_single_qr_fallback_page(
    surface: PdfSurface,
    context: _ArchiveContext,
    fallback_page: _FallbackPage,
    *,
    qr_image: bytes,
    fallback_area: PdfRect,
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
    plans.extend(_archive_page_background(surface, prefix=prefix))
    plans.extend(_shard_header_plans(surface, context, prefix=prefix))
    plans.extend(
        _instructions_panel_plans(
            surface, context, prefix=prefix, rect=PdfRect(14.0, 39.0, 182.0, 14.0)
        )
    )
    plans.extend(_single_qr_plans(surface, qr_image=qr_image, prefix=prefix))
    plans.extend(_single_fallback_plans(surface, fallback_page, prefix=prefix, area=fallback_area))
    plans.extend(_footer_plans(surface, context, prefix=prefix, page_label=page_label))
    return build_page_plan(page_number=fallback_page.page_number, rect=_PAGE_RECT, plans=plans)


def _build_kit_qr_page(
    surface: PdfSurface,
    context: _ArchiveContext,
    qr_page: _QrPage,
    *,
    total_pages: int,
) -> DirectPdfPagePlan:
    page_label = f"Page {qr_page.page_number} / {total_pages}"
    prefix = _component_prefix("archive-kit", qr_page.page_number)
    plans: list[PaintPlan] = []
    plans.extend(_archive_page_background(surface, prefix=prefix))
    plans.extend(_kit_header_plans(surface, context, prefix=prefix, page_label=page_label))
    plans.extend(_kit_qr_stage_plans(surface, qr_page, prefix=prefix))
    return build_page_plan(page_number=qr_page.page_number, rect=_PAGE_RECT, plans=plans)


def _build_kit_instruction_page(
    surface: PdfSurface,
    context: _ArchiveContext,
    *,
    page_number: int,
) -> DirectPdfPagePlan:
    prefix = _component_prefix("archive-kit", page_number)
    plans: list[PaintPlan] = []
    plans.extend(_archive_page_background(surface, prefix=prefix))
    plans.extend(_kit_instruction_plans(surface, context, prefix=prefix))
    return build_page_plan(page_number=page_number, rect=_PAGE_RECT, plans=plans)


def _archive_page_background(surface: PdfSurface, *, prefix: str) -> list[PaintPlan]:
    return [
        Panel(
            component_id=f"{prefix}-page-border",
            stroke=PdfColor(229, 231, 235),
            fill=_PAPER,
            line_width_mm=0.26,
        ).plan(surface, PdfRect(0.0, 0.0, A4_WIDTH_MM, A4_HEIGHT_MM))
    ]


def _main_header_plans(
    surface: PdfSurface,
    context: _ArchiveContext,
    *,
    prefix: str,
    page_label: str,
) -> list[PaintPlan]:
    return [
        TextBox(
            component_id=f"{prefix}-title",
            text=str(context.copy.get("title") or "Main Document").upper(),
            style=_display_style(size_pt=15.0, bold=True),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=12.0,
        ).plan(surface, PdfRect(14.0, 14.0, 118.0, 7.5)),
        Panel(
            component_id=f"{prefix}-mode-chip",
            fill=_INK,
            line_width_mm=0.2,
        ).plan(surface, PdfRect(14.0, 23.0, 9.7, 4.2)),
        TextBox(
            component_id=f"{prefix}-mode-chip-text",
            text="MODE",
            style=_mono_style(size_pt=5.9, bold=True, color=_PAPER, char_spacing_mm=0.12),
            policy=TextFitPolicy.FAIL,
            align=TextAlign.CENTER,
        ).plan(surface, PdfRect(14.6, 24.1, 8.5, 2.5)),
        TextBox(
            component_id=f"{prefix}-subtitle",
            text=str(context.copy.get("subtitle") or "Passphrase-Protected Payload").upper(),
            style=_mono_style(size_pt=6.8, bold=True, color=_INK, char_spacing_mm=0.16),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=5.4,
        ).plan(surface, PdfRect(25.0, 23.4, 102.0, 4.0)),
        *_right_meta_plans(surface, context, prefix=prefix, page_label=page_label),
    ]


def _right_meta_plans(
    surface: PdfSurface,
    context: _ArchiveContext,
    *,
    prefix: str,
    page_label: str,
) -> list[PaintPlan]:
    rows = (
        ("PAGE", page_label),
        ("DOC ID", context.doc_id),
        ("CREATED (UTC)", context.created_timestamp_utc),
    )
    plans: list[PaintPlan] = []
    for index, (label, value) in enumerate(rows):
        y_mm = 14.5 + index * 4.7
        plans.append(
            Rule(
                component_id=f"{prefix}-meta-rule-{index}",
                color=_RULE,
            ).plan(surface, PdfRect(147.8, y_mm + 3.6, 48.2, 0.2))
        )
        plans.append(
            TextBox(
                component_id=f"{prefix}-meta-label-{index}",
                text=label,
                style=_mono_style(size_pt=5.4, bold=True, color=_MUTED, char_spacing_mm=0.1),
                policy=TextFitPolicy.FAIL,
            ).plan(surface, PdfRect(147.8, y_mm, 18.0, 3.0))
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
                min_size_pt=5.0,
                align=TextAlign.RIGHT,
            ).plan(surface, PdfRect(166.0, y_mm, 30.0, 3.0))
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
            min_size_pt=4.8,
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
) -> list[PaintPlan]:
    plans: list[PaintPlan] = []
    for slot_index, item in enumerate(qr_page.items):
        row = math.floor(slot_index / _QR_COLUMNS)
        col = slot_index % _QR_COLUMNS
        rect = PdfRect(
            _CONTENT_X_MM + col * (card_size_mm + _QR_CARD_GAP_MM),
            top_mm + row * (card_size_mm + _QR_CARD_GAP_MM),
            card_size_mm,
            card_size_mm,
        )
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
    image_rect = PdfRect(
        rect.x_mm + (rect.width_mm - image_size_mm) / 2.0,
        rect.y_mm + (rect.height_mm - image_size_mm) / 2.0,
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
                style=_mono_style(size_pt=5.8, bold=True, color=_MUTED, char_spacing_mm=0.12),
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
) -> list[PaintPlan]:
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
        ).plan(surface, PdfRect(174.0, 14.3, 22.0, 4.0)),
        TextBox(
            component_id=f"{prefix}-badge-text",
            text="CONFIDENTIAL",
            style=_mono_style(size_pt=5.8, bold=True, color=_PAPER, char_spacing_mm=0.12),
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.CENTER,
            min_size_pt=4.8,
        ).plan(surface, PdfRect(175.0, 15.2, 20.0, 2.5)),
        TextBox(
            component_id=f"{prefix}-subtitle",
            text=str(context.copy.get("subtitle") or "Keys + Text Fallback").upper(),
            style=_mono_style(size_pt=6.8, bold=True, color=_INK, char_spacing_mm=0.18),
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.RIGHT,
            min_size_pt=5.2,
        ).plan(surface, PdfRect(145.0, 20.4, 51.0, 4.0)),
    ]
    plans.extend(_recovery_meta_grid_plans(surface, context, recovery_meta, prefix=prefix))
    plans.append(
        Rule(component_id=f"{prefix}-header-rule", color=_RULE_DARK).plan(
            surface, PdfRect(14.0, 46.0, 182.0, 0.55)
        )
    )
    return plans


def _recovery_meta_grid_plans(
    surface: PdfSurface,
    context: _ArchiveContext,
    recovery_meta: RecoveryMeta,
    *,
    prefix: str,
) -> list[PaintPlan]:
    rows = (
        ("Document ID", (context.doc_id,)),
        ("Created (UTC)", (context.created_timestamp_utc,)),
        (recovery_meta.quorum_label or "Shard Quorum", (recovery_meta.quorum_value or "",)),
        ("Signing Key", tuple(recovery_meta.signing_pub_lines)),
        ("Passphrase", tuple(recovery_meta.passphrase_lines)),
    )
    positions = (
        PdfRect(14.0, 26.0, 42.0, 10.0),
        PdfRect(59.0, 26.0, 42.0, 10.0),
        PdfRect(104.0, 26.0, 42.0, 10.0),
        PdfRect(149.0, 26.0, 47.0, 18.0),
        PdfRect(14.0, 38.4, 90.0, 8.0),
    )
    plans: list[PaintPlan] = []
    for index, (row, rect) in enumerate(zip(rows, positions, strict=True)):
        label, values = row
        plans.append(
            TextBox(
                component_id=f"{prefix}-meta-label-{index}",
                text=label.upper(),
                style=_mono_style(size_pt=5.4, bold=True, color=_INK, char_spacing_mm=0.12),
                policy=TextFitPolicy.SHRINK,
                min_size_pt=4.6,
            ).plan(surface, PdfRect(rect.x_mm, rect.y_mm, rect.width_mm, 2.5))
        )
        plans.append(
            TextBox(
                component_id=f"{prefix}-meta-value-{index}",
                text="\n".join(value for value in values if value),
                style=_mono_style(size_pt=6.4, bold=True, color=_INK),
                policy=TextFitPolicy.WRAP,
                line_height_multiplier=1.08,
            ).plan(
                surface, PdfRect(rect.x_mm, rect.y_mm + 2.7, rect.width_mm, rect.height_mm - 2.7)
            )
        )
    return plans


def _recovery_fallback_plans(
    surface: PdfSurface,
    fallback_page: _FallbackPage,
    *,
    prefix: str,
    area: PdfRect,
) -> list[PaintPlan]:
    plans: list[PaintPlan] = [
        TextBox(
            component_id=f"{prefix}-fallback-heading",
            text="FALLBACK BLOCKS",
            style=_display_style(size_pt=7.7, bold=True, char_spacing_mm=0.08),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(14.0, 66.5, 48.0, 4.0)),
        Rule(
            component_id=f"{prefix}-fallback-heading-rule",
            color=_RULE,
        ).plan(surface, PdfRect(44.0, 68.6, 128.0, 0.25)),
        TextBox(
            component_id=f"{prefix}-fallback-manual",
            text="MANUAL",
            style=_mono_style(size_pt=5.8, bold=True, color=_INK, char_spacing_mm=0.12),
            policy=TextFitPolicy.FAIL,
            align=TextAlign.RIGHT,
        ).plan(surface, PdfRect(176.0, 66.8, 19.0, 3.0)),
        Panel(
            component_id=f"{prefix}-fallback-panel",
            stroke=_RULE,
            fill=_PANEL,
            line_width_mm=0.22,
        ).plan(surface, area),
    ]
    plans.extend(_fallback_entry_plans(surface, fallback_page, prefix=prefix, area=area))
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
                    min_size_pt=4.8,
                ).plan(surface, PdfRect(area.x_mm + 1.2, y_mm, area.width_mm - 2.4, 3.0))
            )
        else:
            if page_entry.display_line_number is None:
                raise ValueError("fallback payload line is missing its display number")
            plans.append(
                TextBox(
                    component_id=f"{prefix}-fallback-line-{entry.section_index}-{entry.line_number}",
                    text=f"{page_entry.display_line_number:02d}. {entry.text}",
                    style=_mono_style(size_pt=5.8, color=_INK),
                    policy=TextFitPolicy.SHRINK,
                    min_size_pt=4.0,
                ).plan(surface, PdfRect(area.x_mm + 2.6, y_mm, area.width_mm - 5.0, 3.2))
            )
    return plans


def _recovery_validation_plans(surface: PdfSurface, *, prefix: str) -> list[PaintPlan]:
    return [
        Rule(
            component_id=f"{prefix}-validation-rule",
            color=_RULE_DARK,
        ).plan(surface, PdfRect(14.0, 263.5, 182.0, 0.25)),
        TextBox(
            component_id=f"{prefix}-security-title",
            text="SECURITY INSTRUCTIONS",
            style=_mono_style(size_pt=6.2, bold=True, color=_INK, char_spacing_mm=0.1),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(14.0, 265.0, 70.0, 3.0)),
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
        ).plan(surface, PdfRect(14.0, 269.0, 86.0, 11.0)),
        TextBox(
            component_id=f"{prefix}-validation-title",
            text="VALIDATION",
            style=_mono_style(size_pt=6.2, bold=True, color=_INK, char_spacing_mm=0.1),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(106.0, 265.0, 60.0, 3.0)),
        TextBox(
            component_id=f"{prefix}-validation-body",
            text="- Verified by: ____________________\n- Date validated: ____ / ____ / ____",
            style=_body_style(size_pt=6.4, color=_INK),
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=1.2,
        ).plan(surface, PdfRect(106.0, 269.0, 84.0, 8.0)),
    ]


def _shard_header_plans(
    surface: PdfSurface,
    context: _ArchiveContext,
    *,
    prefix: str,
) -> list[PaintPlan]:
    shard_index = _positive_int(context.values.get("shard_index"), default=1)
    shard_total = _positive_int(context.values.get("shard_total"), default=1)
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
            min_size_pt=5.8,
        ).plan(surface, PdfRect(14.0, 22.2, 92.0, 4.0)),
        Panel(
            component_id=f"{prefix}-badge",
            fill=_INK,
            line_width_mm=0.2,
        ).plan(surface, PdfRect(174.0, 14.3, 22.0, 4.8)),
        TextBox(
            component_id=f"{prefix}-badge-text",
            text=f"SHARD {shard_index} / {shard_total}",
            style=_mono_style(size_pt=6.0, bold=True, color=_PAPER, char_spacing_mm=0.1),
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.CENTER,
            min_size_pt=4.5,
        ).plan(surface, PdfRect(175.0, 15.5, 20.0, 2.7)),
        TextBox(
            component_id=f"{prefix}-confidential",
            text="CONFIDENTIAL",
            style=_mono_style(size_pt=5.4, bold=True, color=_MUTED, char_spacing_mm=0.12),
            policy=TextFitPolicy.FAIL,
            align=TextAlign.RIGHT,
        ).plan(surface, PdfRect(168.0, 21.0, 28.0, 3.0)),
        Panel(
            component_id=f"{prefix}-meta-panel",
            stroke=_RULE,
            fill=_PANEL,
            line_width_mm=0.2,
        ).plan(surface, PdfRect(14.0, 25.0, 182.0, 11.0)),
        TextBox(
            component_id=f"{prefix}-doc-id-label",
            text="DOCUMENT ID",
            style=_mono_style(size_pt=5.6, bold=True, color=_INK, char_spacing_mm=0.1),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(15.4, 26.8, 48.0, 2.6)),
        TextBox(
            component_id=f"{prefix}-doc-id",
            text=context.doc_id,
            style=_mono_style(size_pt=6.2, bold=True, color=_INK),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=4.8,
        ).plan(surface, PdfRect(15.4, 30.0, 58.0, 3.0)),
        TextBox(
            component_id=f"{prefix}-created-label",
            text="CREATED (UTC)",
            style=_mono_style(size_pt=5.6, bold=True, color=_INK, char_spacing_mm=0.1),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(61.0, 26.8, 48.0, 2.6)),
        TextBox(
            component_id=f"{prefix}-created",
            text=context.created_timestamp_utc,
            style=_mono_style(size_pt=6.2, bold=True, color=_INK),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=4.8,
        ).plan(surface, PdfRect(61.0, 30.0, 58.0, 3.0)),
        Rule(
            component_id=f"{prefix}-header-rule",
            color=_RULE_DARK,
        ).plan(surface, PdfRect(14.0, 38.0, 182.0, 0.55)),
    ]


def _single_qr_plans(
    surface: PdfSurface,
    *,
    qr_image: bytes,
    prefix: str,
) -> list[PaintPlan]:
    frame = PdfRect(72.0, 128.0, 66.0, 66.0)
    image = PdfRect(79.5, 135.5, 51.0, 51.0)
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
) -> list[PaintPlan]:
    plans: list[PaintPlan] = [
        Line(
            component_id=f"{prefix}-fallback-dashed-rule",
            color=_RULE,
            line_width_mm=0.25,
        ).plan(
            surface,
            start_x_mm=area.x_mm,
            start_y_mm=area.y_mm - 4.8,
            end_x_mm=area.right_mm,
            end_y_mm=area.y_mm - 4.8,
        ),
        TextBox(
            component_id=f"{prefix}-fallback-heading",
            text="RAW TEXT FALLBACK",
            style=_mono_style(size_pt=6.1, bold=True, color=_INK, char_spacing_mm=0.1),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(area.x_mm, area.y_mm - 2.8, 58.0, 3.0)),
        TextBox(
            component_id=f"{prefix}-fallback-helper",
            text="USE IF QR IS UNREADABLE",
            style=_mono_style(size_pt=5.2, color=_MUTED_SOFT, char_spacing_mm=0.1),
            policy=TextFitPolicy.FAIL,
            align=TextAlign.RIGHT,
        ).plan(surface, PdfRect(area.right_mm - 60.0, area.y_mm - 2.8, 60.0, 3.0)),
        Panel(
            component_id=f"{prefix}-fallback-panel",
            stroke=_RULE,
            fill=_PANEL,
            line_width_mm=0.2,
        ).plan(surface, area),
    ]
    plans.extend(_fallback_entry_plans(surface, fallback_page, prefix=prefix, area=area))
    return plans


def _kit_header_plans(
    surface: PdfSurface,
    context: _ArchiveContext,
    *,
    prefix: str,
    page_label: str,
) -> list[PaintPlan]:
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
            min_size_pt=5.5,
        ).plan(surface, PdfRect(14.0, 23.0, 110.0, 4.0)),
        Panel(
            component_id=f"{prefix}-lock",
            stroke=_RULE,
            fill=PdfColor(243, 244, 246),
            line_width_mm=0.24,
        ).plan(surface, PdfRect(188.0, 14.0, 8.0, 8.0)),
        TextBox(
            component_id=f"{prefix}-lock-icon",
            text=_ICON_LOCK,
            style=_symbol_style(size_pt=17.5, color=_MUTED_SOFT),
            policy=TextFitPolicy.FAIL,
            align=TextAlign.CENTER,
            line_height_multiplier=1.0,
        ).plan(surface, PdfRect(188.6, 14.9, 6.8, 6.5)),
        *_kit_meta_plans(surface, context, prefix=prefix, page_label=page_label),
        Rule(
            component_id=f"{prefix}-header-rule",
            color=_RULE_DARK,
        ).plan(surface, PdfRect(14.0, 36.5, 182.0, 0.55)),
    ]


def _kit_meta_plans(
    surface: PdfSurface,
    context: _ArchiveContext,
    *,
    prefix: str,
    page_label: str,
) -> list[PaintPlan]:
    rows = (
        ("DOCUMENT ID", context.doc_id, TextAlign.LEFT, PdfRect(14.0, 28.0, 58.0, 6.0)),
        (
            "CREATED (UTC)",
            context.created_timestamp_utc,
            TextAlign.CENTER,
            PdfRect(76.0, 28.0, 58.0, 6.0),
        ),
        ("PAGE", page_label, TextAlign.RIGHT, PdfRect(138.0, 28.0, 58.0, 6.0)),
    )
    plans: list[PaintPlan] = []
    for index, (label, value, align, rect) in enumerate(rows):
        plans.append(
            TextBox(
                component_id=f"{prefix}-kit-meta-label-{index}",
                text=label,
                style=_mono_style(size_pt=5.5, bold=True, color=_INK, char_spacing_mm=0.1),
                policy=TextFitPolicy.FAIL,
                align=align,
            ).plan(surface, PdfRect(rect.x_mm, rect.y_mm, rect.width_mm, 2.4))
        )
        plans.append(
            TextBox(
                component_id=f"{prefix}-kit-meta-value-{index}",
                text=value,
                style=_mono_style(size_pt=6.4, bold=True, color=_INK),
                policy=TextFitPolicy.SHRINK,
                align=align,
                min_size_pt=4.7,
            ).plan(surface, PdfRect(rect.x_mm, rect.y_mm + 2.8, rect.width_mm, 3.0))
        )
    return plans


def _kit_qr_stage_plans(surface: PdfSurface, qr_page: _QrPage, *, prefix: str) -> list[PaintPlan]:
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-kit-stage",
            stroke=_RULE,
            fill=_PANEL,
            line_width_mm=0.2,
        ).plan(surface, PdfRect(14.0, 39.0, 182.0, 66.5)),
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
            card_size_mm=_KIT_QR_CARD_SIZE_MM,
            image_size_mm=_KIT_QR_IMAGE_SIZE_MM,
            label_prefix="PART",
        )
    )
    return plans


def _kit_instruction_plans(
    surface: PdfSurface,
    context: _ArchiveContext,
    *,
    prefix: str,
) -> list[PaintPlan]:
    shell = PdfRect(14.0, 14.0, 182.0, 268.0)
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
        ).plan(surface, PdfRect(21.0, 22.0, 166.0, 10.0)),
        TextBox(
            component_id=f"{prefix}-instruction-subtitle",
            text="Use this page after scanning the QR pages. Keep everything offline.",
            style=_body_style(size_pt=10.6, color=_INK),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=8.2,
        ).plan(surface, PdfRect(21.0, 34.7, 160.0, 5.5)),
        Rule(
            component_id=f"{prefix}-instruction-rule",
            color=PdfColor(203, 213, 225),
        ).plan(surface, PdfRect(21.0, 41.8, 168.0, 0.35)),
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
            rect=PdfRect(21.0, 47.5, 82.0, 50.0),
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
            rect=PdfRect(21.0, 107.0, 82.0, 42.0),
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
            rect=PdfRect(21.0, 157.0, 82.0, 48.0),
            index=3,
            bullet_icon="disc",
        )
    )
    plans.extend(_instruction_right_column_plans(surface, context, prefix=prefix))
    plans.extend(_instruction_footer_plans(surface, context, prefix=prefix))
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
) -> list[PaintPlan]:
    plans: list[PaintPlan] = []
    cards = (
        (
            "Verify",
            (
                "Confirm the kit loads and shows the Recovery Kit home screen.",
                "If it fails to open, re-check the order and re-save the file.",
            ),
            PdfRect(108.0, 47.5, 81.0, 34.0),
        ),
        (
            "Storage",
            (
                "Keep the QR pages and the bundle file in separate locations.",
                "Store the bundle on a write-protected drive if possible.",
            ),
            PdfRect(108.0, 85.0, 81.0, 34.0),
        ),
        (
            "Security",
            (
                "Work offline and on a trusted machine.",
                "Delete temporary files after successful recovery.",
            ),
            PdfRect(108.0, 123.0, 81.0, 32.0),
        ),
    )
    for index, (title, paragraphs, rect) in enumerate(cards):
        plans.extend(_instruction_info_card_plans(surface, prefix, title, paragraphs, rect, index))
    plans.extend(
        _instruction_checklist_plans(
            surface,
            context,
            prefix=prefix,
            rect=PdfRect(108.0, 159.0, 81.0, 76.0),
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
            min_size_pt=5.8,
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
) -> list[PaintPlan]:
    return [
        Rule(
            component_id=f"{prefix}-instruction-footer-rule",
            color=PdfColor(203, 213, 225),
        ).plan(surface, PdfRect(21.0, 267.0, 168.0, 0.25)),
        TextBox(
            component_id=f"{prefix}-instruction-footer-kind",
            text="RECOVERY KIT: OFFLINE HTML BUNDLE",
            style=_body_style(size_pt=7.4, color=_INK, char_spacing_mm=0.16),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=5.8,
        ).plan(surface, PdfRect(21.0, 272.0, 82.0, 4.0)),
        TextBox(
            component_id=f"{prefix}-instruction-footer-doc-id",
            text=f"DOCUMENT ID: {context.doc_id}",
            style=_mono_style(size_pt=6.5, color=_INK, char_spacing_mm=0.1),
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.RIGHT,
            min_size_pt=5.0,
        ).plan(surface, PdfRect(105.0, 272.0, 84.0, 4.0)),
    ]


def _footer_plans(
    surface: PdfSurface,
    context: _ArchiveContext,
    *,
    prefix: str,
    page_label: str,
) -> list[PaintPlan]:
    return [
        Rule(
            component_id=f"{prefix}-footer-rule",
            color=_RULE_DARK,
        ).plan(surface, PdfRect(14.0, 280.3, 182.0, 0.25)),
        Ellipse(
            component_id=f"{prefix}-footer-dot",
            fill=_ACCENT,
            line_width_mm=0.18,
        ).plan(surface, PdfRect(14.0, 282.7, 1.8, 1.8)),
        TextBox(
            component_id=f"{prefix}-footer-left",
            text=context.footer_left.upper(),
            style=_mono_style(size_pt=6.1, color=_MUTED_SOFT, char_spacing_mm=0.12),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=4.8,
        ).plan(surface, PdfRect(17.2, 282.5, 70.0, 3.5)),
        TextBox(
            component_id=f"{prefix}-footer-page",
            text=page_label.upper().replace("PAGE", "PAGE"),
            style=_mono_style(size_pt=6.0, color=_MUTED, char_spacing_mm=0.12),
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.RIGHT,
            min_size_pt=4.8,
        ).plan(surface, PdfRect(150.0, 282.5, 46.0, 3.5)),
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
