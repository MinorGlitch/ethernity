"""Sentinel recovery document rendering through direct PDF primitives."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from ethernity.render.direct_pdf.assets import packaged_direct_pdf_assets
from ethernity.render.direct_pdf.components import Panel, Rule, TextAlign, TextBox
from ethernity.render.direct_pdf.debug import write_direct_layout_debug_json
from ethernity.render.direct_pdf.fallback_layout import (
    FallbackLineEntry as _FallbackLineEntry,
    FallbackPage,
    FallbackPageEntry as _FallbackPageEntry,
    FallbackSectionLines as _FallbackSectionLines,
    FallbackTitleEntry as _FallbackTitleEntry,
    ResponsiveFallbackPageProfile,
    ResponsiveFallbackPagination,
    ResponsiveFallbackSpec,
    build_fallback_proof,
    resolve_responsive_fallback_pagination,
)
from ethernity.render.direct_pdf.layout_proof import build_direct_layout_proof
from ethernity.render.direct_pdf.page import DirectPdfPagePlan, PaintPlan
from ethernity.render.direct_pdf.page_geometry import resolve_page_geometry
from ethernity.render.direct_pdf.recovery_metadata import (
    RecoveryPassphraseContinuationPage,
    RecoveryPassphrasePagination,
    paginate_recovery_passphrase,
)
from ethernity.render.direct_pdf.sentinel.common import (
    SENTINEL_BACKGROUND,
    SENTINEL_BLACK,
    SENTINEL_BORDER,
    SENTINEL_GRID_LINE,
    SENTINEL_LINE_FILL,
    SENTINEL_MUTED,
    SENTINEL_ORANGE,
    SENTINEL_TEXT,
    SENTINEL_WARNING_FILL,
    SENTINEL_WHITE,
    SentinelPageLayout,
    SentinelShellContext,
    build_sentinel_footer_plans,
    build_sentinel_header_plans,
    build_sentinel_page_plan,
    build_sentinel_shell_context,
    build_sentinel_surface,
)
from ethernity.render.direct_pdf.sentinel.theme import SENTINEL_THEME
from ethernity.render.direct_pdf.structured_common import component_prefix
from ethernity.render.direct_pdf.surface import PdfSurface
from ethernity.render.direct_pdf.text_fit import TextFitPolicy, fit_text_to_width
from ethernity.render.direct_pdf.types import PdfRect, TextStyle
from ethernity.render.doc_types import DOC_TYPE_RECOVERY
from ethernity.render.proofs import build_render_artifact_proof
from ethernity.render.recovery_meta import (
    PASSPHRASE_PRINT_MODE_JSON_PARTS,
    RecoveryMeta,
    recovery_passphrase_display,
)
from ethernity.render.types import (
    FallbackSection,
    RenderArtifactProof,
    RenderFallbackProof,
    RenderInputs,
    RenderResult,
)

_COMPONENT_BASE = "sentinel-recovery"
_FALLBACK_GROUP_SIZE = 4
_FALLBACK_MINIMUM_ROW_HEIGHT_MM = 5.6
_FALLBACK_MINIMUM_BODY_SIZE_PT = 6.0
_FIRST_FALLBACK_BODY_SIZE_PT = 6.6
_CONTINUATION_FALLBACK_BODY_SIZE_PT = 6.8
_FALLBACK_TEXT_WIDTH_SAFETY_MM = 0.6
_FIRST_FALLBACK_AREA = PdfRect(79.7, 80.5, 115.2, 133.8)
_CONTINUATION_FALLBACK_AREA = PdfRect(18.0, 83.0, 174.0, 166.0)
_FIRST_FALLBACK_NUMBER_LEFT_INSET_MM = 3.0
_FIRST_FALLBACK_NUMBER_WIDTH_MM = 8.8
_FIRST_FALLBACK_NUMBER_GAP_MM = 2.2
_FIRST_FALLBACK_RIGHT_INSET_MM = 5.2
_CONTINUATION_FALLBACK_NUMBER_WIDTH_MM = 17.0
_CONTINUATION_FALLBACK_NUMBER_GAP_MM = 5.0
_CONTINUATION_FALLBACK_RIGHT_INSET_MM = 40.0
_ICON_WARNING = chr(0xE002)
_ICON_INFO = chr(0xE88E)
_ICON_CHECK_CIRCLE = chr(0xE86C)


@dataclass(frozen=True)
class SentinelRecoveryDirectPlan:
    """Measured pages and app-wide proofs for one direct Sentinel recovery render."""

    page_plans: tuple[DirectPdfPagePlan, ...]
    fallback_proof: RenderFallbackProof
    artifact_proof: RenderArtifactProof


@dataclass(frozen=True)
class _FallbackPageLayout:
    page_number: int
    entries: tuple[_FallbackPageEntry, ...]
    row_capacity: int
    row_height_mm: float


@dataclass(frozen=True)
class _SentinelMetadataRow:
    label: str
    value_lines: tuple[str, ...]
    guidance: str = ""


def render_sentinel_recovery_direct_pdf(inputs: RenderInputs) -> RenderResult:
    """Render a Sentinel recovery document directly to PDF and return validation proofs."""

    surface = build_sentinel_surface(inputs)
    packaged_direct_pdf_assets().register_fonts(surface)
    plan = build_sentinel_recovery_direct_plan(surface, inputs)
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


def build_sentinel_recovery_direct_plan(
    surface: PdfSurface,
    inputs: RenderInputs,
) -> SentinelRecoveryDirectPlan:
    """Build measured direct-PDF plans and render proofs for Sentinel recovery inputs."""

    _validate_inputs(inputs)
    context = build_sentinel_shell_context(inputs, doc_type=DOC_TYPE_RECOVERY)
    recovery_meta = inputs.recovery_meta or RecoveryMeta()
    passphrase_pagination = _paginate_sentinel_passphrase(
        surface,
        recovery_meta,
        page_layout=context.page_layout,
    )
    sections, fallback_pages = _resolve_fallback_layout(
        surface,
        inputs.fallback_sections or (),
        page_layout=context.page_layout,
    )
    total_pages = len(fallback_pages) + len(passphrase_pagination.continuation_pages)
    fallback_page_plans = tuple(
        _build_page(
            surface,
            context,
            recovery_meta=passphrase_pagination.inline_meta,
            fallback_page=fallback_page,
            total_pages=total_pages,
        )
        for fallback_page in fallback_pages
    )
    passphrase_page_plans = tuple(
        _build_passphrase_continuation_page(
            surface,
            context,
            continuation_page=continuation_page,
            page_number=len(fallback_pages) + continuation_page.page_index,
            total_pages=total_pages,
        )
        for continuation_page in passphrase_pagination.continuation_pages
    )
    page_plans = fallback_page_plans + passphrase_page_plans
    fallback_proof = build_fallback_proof(
        inputs,
        sections,
        tuple(
            FallbackPage(page_number=page.page_number, entries=page.entries)
            for page in fallback_pages
        ),
    )
    artifact_proof = build_render_artifact_proof(
        inputs,
        encoded_payload_count=len(inputs.qr_payloads or inputs.frames),
        physical_qr_count=0,
        physical_qr_payload_indexes=(),
        page_count=len(page_plans),
        fallback_proof=fallback_proof,
    )
    return SentinelRecoveryDirectPlan(
        page_plans=page_plans,
        fallback_proof=fallback_proof,
        artifact_proof=artifact_proof,
    )


def _paginate_sentinel_passphrase(
    surface: PdfSurface,
    recovery_meta: RecoveryMeta,
    *,
    page_layout: SentinelPageLayout,
) -> RecoveryPassphrasePagination:
    inline_meta = recovery_meta
    if (
        recovery_meta.passphrase_print_mode != PASSPHRASE_PRINT_MODE_JSON_PARTS
        and recovery_meta.passphrase_lines
    ):
        inline_meta = replace(
            recovery_meta,
            passphrase_lines=(" ".join(recovery_meta.passphrase_lines),),
        )
    style = _metadata_value_style()
    guidance_style = _metadata_guidance_style()
    continuation_rect = _passphrase_continuation_value_rect(page_layout)
    inline_height_mm = _passphrase_inline_text_height(surface, inline_meta)
    mapped_continuation_rect = page_layout.map_rect(continuation_rect)
    return paginate_recovery_passphrase(
        surface,
        inline_meta,
        style=style,
        guidance_style=guidance_style,
        max_width_mm=110.2,
        inline_height_mm=inline_height_mm,
        continuation_height_mm=mapped_continuation_rect.height_mm,
        line_height_multiplier=1.15,
    )


def _passphrase_inline_text_height(surface: PdfSurface, recovery_meta: RecoveryMeta) -> float:
    meta_without_passphrase = replace(
        recovery_meta,
        passphrase=None,
        passphrase_lines=(),
    )
    fixed_height_mm = sum(
        _metadata_row_advance_mm(surface, row) for row in _metadata_rows(meta_without_passphrase)
    )
    available_row_height_mm = 273.0 - 219.5 - fixed_height_mm
    text_height_mm = available_row_height_mm - 12.9
    if text_height_mm <= 0:
        raise ValueError("Sentinel page has zero-capacity inline passphrase metadata area")
    return text_height_mm


def _passphrase_continuation_value_rect(page_layout: SentinelPageLayout) -> PdfRect:
    _ = page_layout
    return PdfRect(49.9, 70.0, 110.2, 198.0)


def _validate_inputs(inputs: RenderInputs) -> None:
    normalized_doc_type = inputs.doc_type.strip().lower()
    if normalized_doc_type != DOC_TYPE_RECOVERY:
        raise ValueError("direct Sentinel recovery renderer only supports recovery documents")
    if inputs.render_qr:
        raise ValueError("direct Sentinel recovery renderer does not place physical QR codes")
    if not inputs.render_fallback:
        raise ValueError("direct Sentinel recovery renderer requires fallback rendering")
    if not inputs.frames:
        raise ValueError("frames cannot be empty for direct Sentinel recovery rendering")
    if not inputs.fallback_sections:
        raise ValueError("fallback_sections are required for direct Sentinel recovery rendering")
    if inputs.recovery_meta is None:
        raise ValueError("recovery metadata is required for direct Sentinel recovery rendering")

    resolve_page_geometry(inputs)


def _resolve_fallback_layout(
    surface: PdfSurface,
    sections: Sequence[FallbackSection],
    *,
    page_layout: SentinelPageLayout,
) -> tuple[tuple[_FallbackSectionLines, ...], tuple[_FallbackPageLayout, ...]]:
    first_area = page_layout.map_rect(_FIRST_FALLBACK_AREA)
    continuation_area = page_layout.map_rect(_CONTINUATION_FALLBACK_AREA)
    pagination = resolve_responsive_fallback_pagination(
        surface,
        sections,
        first_profile=ResponsiveFallbackPageProfile(
            area=first_area,
            spec=ResponsiveFallbackSpec(
                group_size=_FALLBACK_GROUP_SIZE,
                row_height_mm=_FALLBACK_MINIMUM_ROW_HEIGHT_MM,
                body_style=SENTINEL_THEME.mono_style(
                    size_pt=_FIRST_FALLBACK_BODY_SIZE_PT,
                    color=SENTINEL_TEXT,
                ),
                number_style=SENTINEL_THEME.mono_style(size_pt=7.0, color=SENTINEL_TEXT),
                content_left_inset_mm=_FIRST_FALLBACK_NUMBER_LEFT_INSET_MM,
                content_right_inset_mm=_FIRST_FALLBACK_RIGHT_INSET_MM,
                vertical_reserved_mm=0.0,
                number_gap_mm=_FIRST_FALLBACK_NUMBER_GAP_MM,
                number_minimum_width_mm=_FIRST_FALLBACK_NUMBER_WIDTH_MM,
                safety_mm=_FALLBACK_TEXT_WIDTH_SAFETY_MM,
            ),
        ),
        continuation_profile=ResponsiveFallbackPageProfile(
            area=continuation_area,
            spec=ResponsiveFallbackSpec(
                group_size=_FALLBACK_GROUP_SIZE,
                row_height_mm=_FALLBACK_MINIMUM_ROW_HEIGHT_MM,
                body_style=SENTINEL_THEME.mono_style(
                    size_pt=_CONTINUATION_FALLBACK_BODY_SIZE_PT,
                    color=SENTINEL_TEXT,
                ),
                number_style=SENTINEL_THEME.mono_style(
                    size_pt=8.5,
                    bold=True,
                    color=SENTINEL_MUTED,
                ),
                content_left_inset_mm=0.0,
                content_right_inset_mm=_CONTINUATION_FALLBACK_RIGHT_INSET_MM,
                vertical_reserved_mm=0.0,
                number_gap_mm=_CONTINUATION_FALLBACK_NUMBER_GAP_MM,
                number_minimum_width_mm=_CONTINUATION_FALLBACK_NUMBER_WIDTH_MM,
                safety_mm=_FALLBACK_TEXT_WIDTH_SAFETY_MM,
            ),
        ),
    )
    page_layouts = tuple(
        _responsive_page_layout(page, pagination=pagination) for page in pagination.pages
    )
    return pagination.sections, page_layouts


def _responsive_page_layout(
    page: FallbackPage,
    *,
    pagination: ResponsiveFallbackPagination,
) -> _FallbackPageLayout:
    # Profiled pagination owns physical capacity; Sentinel stores
    # canonical row height because its shell performs the final page reflow.
    if page.page_number == 1:
        reference_area = _FIRST_FALLBACK_AREA
        row_capacity = pagination.first_capacity
    else:
        reference_area = _CONTINUATION_FALLBACK_AREA
        row_capacity = pagination.continuation_capacity
    return _FallbackPageLayout(
        page_number=page.page_number,
        entries=page.entries,
        row_capacity=row_capacity,
        row_height_mm=reference_area.height_mm / row_capacity,
    )


def _build_page(
    surface: PdfSurface,
    context: SentinelShellContext,
    *,
    recovery_meta: RecoveryMeta,
    fallback_page: _FallbackPageLayout,
    total_pages: int,
) -> DirectPdfPagePlan:
    page_number = fallback_page.page_number
    page_label = f"Page {page_number} / {total_pages}"
    plans: list[PaintPlan] = []
    plans.extend(
        build_sentinel_header_plans(
            surface,
            context,
            page_label=page_label,
            page_number=page_number,
            component_base=_COMPONENT_BASE,
            title_default="Recovery Document",
            subtitle_default="Keys + Text Fallback",
        )
    )
    if page_number == 1:
        plans.extend(_warning_plans(surface, context, page_number=page_number))
        plans.extend(
            _first_page_body_plans(
                surface,
                context,
                recovery_meta,
                fallback_page,
                page_label=page_label,
            )
        )
    else:
        plans.extend(_continuation_body_plans(surface, context, fallback_page))
    plans.extend(
        build_sentinel_footer_plans(
            surface,
            context,
            page_label=page_label,
            page_number=page_number,
            component_base=_COMPONENT_BASE,
        )
    )
    return build_sentinel_page_plan(
        page_number=page_number,
        page_layout=context.page_layout,
        plans=plans,
        physical_component_ids=_physical_fallback_text_component_ids(fallback_page),
    )


def _build_passphrase_continuation_page(
    surface: PdfSurface,
    context: SentinelShellContext,
    *,
    continuation_page: RecoveryPassphraseContinuationPage,
    page_number: int,
    total_pages: int,
) -> DirectPdfPagePlan:
    prefix = component_prefix(_COMPONENT_BASE, page_number)
    page_label = f"Page {page_number} / {total_pages}"
    value_rect = _passphrase_continuation_value_rect(context.page_layout)
    panel_rect = PdfRect(
        value_rect.x_mm - 3.0,
        value_rect.y_mm - 2.0,
        value_rect.width_mm + 6.0,
        value_rect.height_mm + 4.0,
    )
    plans: list[PaintPlan] = []
    plans.extend(
        build_sentinel_header_plans(
            surface,
            context,
            page_label=page_label,
            page_number=page_number,
            component_base=_COMPONENT_BASE,
            title_default="Recovery Document",
            subtitle_default="Passphrase Continuation",
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
                style=SENTINEL_THEME.sans_style(
                    size_pt=11.0,
                    bold=True,
                    color=SENTINEL_TEXT,
                ),
                policy=TextFitPolicy.FAIL,
            ).plan(surface, PdfRect(15.0, 36.0, 180.0, 5.5)),
            TextBox(
                component_id=f"{prefix}-passphrase-continuation-instructions",
                text=continuation_page.instructions,
                style=SENTINEL_THEME.sans_style(size_pt=8.2, color=SENTINEL_TEXT),
                policy=TextFitPolicy.WRAP,
            ).plan(surface, PdfRect(15.0, 44.0, 180.0, 17.0)),
            Panel(
                component_id=f"{prefix}-passphrase-continuation-panel",
                stroke=SENTINEL_BORDER,
                fill=SENTINEL_LINE_FILL,
                line_width_mm=0.2,
            ).plan(surface, panel_rect),
            TextBox(
                component_id=f"{prefix}-passphrase-continuation-value",
                text=continuation_page.text,
                style=_metadata_value_style(),
                policy=TextFitPolicy.FAIL,
                line_height_multiplier=1.15,
            ).plan(surface, value_rect),
        ]
    )
    plans.extend(
        build_sentinel_footer_plans(
            surface,
            context,
            page_label=page_label,
            page_number=page_number,
            component_base=_COMPONENT_BASE,
        )
    )
    return build_sentinel_page_plan(
        page_number=page_number,
        page_layout=context.page_layout,
        plans=plans,
    )


def _warning_plans(
    surface: PdfSurface,
    context: SentinelShellContext,
    *,
    page_number: int,
) -> list[PaintPlan]:
    prefix = component_prefix(_COMPONENT_BASE, page_number)
    return [
        Panel(
            component_id=f"{prefix}-warning-panel",
            stroke=SENTINEL_ORANGE,
            fill=SENTINEL_WARNING_FILL,
            line_width_mm=0.22,
        ).plan(surface, PdfRect(10.5, 32.3, 189.0, 21.2)),
        TextBox(
            component_id=f"{prefix}-warning-icon",
            text=_ICON_WARNING,
            style=SENTINEL_THEME.symbol_style(size_pt=18.0, color=SENTINEL_ORANGE),
            policy=TextFitPolicy.FAIL,
            line_height_multiplier=1.0,
        ).plan(surface, PdfRect(14.0, 38.0, 8.0, 8.0)),
        TextBox(
            component_id=f"{prefix}-warning-title",
            text=str(context.copy.get("warning_title") or "Critical Security Warning").upper(),
            style=SENTINEL_THEME.sans_style(size_pt=11.5, bold=True, color=SENTINEL_TEXT),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(23.0, 36.2, 80.0, 5.0)),
        TextBox(
            component_id=f"{prefix}-warning-body",
            text=str(context.copy.get("warning_body") or ""),
            style=SENTINEL_THEME.sans_style(size_pt=10.5, color=SENTINEL_BLACK),
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=1.2,
        ).plan(surface, PdfRect(23.0, 41.6, 169.0, 9.0)),
    ]


def _first_page_body_plans(
    surface: PdfSurface,
    context: SentinelShellContext,
    recovery_meta: RecoveryMeta,
    fallback_page: _FallbackPageLayout,
    *,
    page_label: str,
) -> list[PaintPlan]:
    plans: list[PaintPlan] = []
    plans.extend(_session_log_plans(surface, context, recovery_meta, page_label=page_label))
    plans.extend(_transcription_panel_plans(surface, context, fallback_page))
    plans.extend(_metadata_plans(surface, recovery_meta))
    return plans


def _session_log_plans(
    surface: PdfSurface,
    context: SentinelShellContext,
    recovery_meta: RecoveryMeta,
    *,
    page_label: str,
) -> list[PaintPlan]:
    prefix = component_prefix(_COMPONENT_BASE, 1)
    left_rect = PdfRect(10.5, 57.8, 59.4, 216.0)
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-session-panel",
            stroke=SENTINEL_BORDER,
            fill=SENTINEL_LINE_FILL,
            line_width_mm=0.22,
        ).plan(surface, left_rect),
        Panel(
            component_id=f"{prefix}-session-heading-panel",
            stroke=SENTINEL_BORDER,
            fill=SENTINEL_WHITE,
            line_width_mm=0.18,
        ).plan(surface, PdfRect(left_rect.x_mm, left_rect.y_mm, left_rect.width_mm, 19.0)),
        TextBox(
            component_id=f"{prefix}-session-heading",
            text=str(context.copy.get("session_log_label") or "Recovery Session Log").upper(),
            style=SENTINEL_THEME.sans_style(size_pt=10.5, bold=True, color=SENTINEL_TEXT),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=7.5,
        ).plan(surface, PdfRect(14.0, 62.0, 50.0, 4.8)),
        TextBox(
            component_id=f"{prefix}-session-helper",
            text="Complete this checklist before manual transcription.",
            style=SENTINEL_THEME.sans_style(size_pt=8.0, color=SENTINEL_TEXT),
            policy=TextFitPolicy.WRAP,
        ).plan(surface, PdfRect(14.0, 67.0, 50.0, 8.0)),
        TextBox(
            component_id=f"{prefix}-session-label",
            text="SESSION",
            style=SENTINEL_THEME.sans_style(size_pt=8.4, bold=True, color=SENTINEL_TEXT),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(14.0, 81.0, 30.0, 4.5)),
    ]
    plans.extend(_session_table_plans(surface, context, recovery_meta, page_label=page_label))
    plans.extend(_workspace_check_plans(surface, context))
    plans.extend(_completion_check_plans(surface, context))
    return plans


def _session_table_plans(
    surface: PdfSurface,
    context: SentinelShellContext,
    recovery_meta: RecoveryMeta,
    *,
    page_label: str,
) -> list[PaintPlan]:
    prefix = component_prefix(_COMPONENT_BASE, 1)
    rows = (
        ("Doc ID", context.doc_id),
        ("Generated (UTC)", context.created_timestamp_utc),
        ("Page", page_label),
        ("Created Date", context.created_date),
        ("Quorum", recovery_meta.quorum_value or ""),
    )
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-session-table",
            stroke=SENTINEL_BORDER,
            fill=SENTINEL_WHITE,
            line_width_mm=0.2,
        ).plan(surface, PdfRect(14.0, 85.0, 55.5, 34.0)),
    ]
    y_mm = 89.0
    for index, (label, value) in enumerate(rows):
        plans.extend(
            [
                TextBox(
                    component_id=f"{prefix}-session-row-label-{index}",
                    text=label.upper(),
                    style=SENTINEL_THEME.sans_style(
                        size_pt=7.8,
                        bold=True,
                        color=SENTINEL_TEXT,
                    ),
                    policy=TextFitPolicy.SHRINK,
                    min_size_pt=6.0,
                ).plan(surface, PdfRect(16.0, y_mm, 23.0, 4.2)),
                TextBox(
                    component_id=f"{prefix}-session-row-value-{index}",
                    text=value,
                    style=SENTINEL_THEME.mono_style(size_pt=7.4, color=SENTINEL_TEXT),
                    policy=TextFitPolicy.SHRINK,
                    align=TextAlign.RIGHT,
                    min_size_pt=6.0,
                ).plan(surface, PdfRect(39.0, y_mm, 29.0, 4.2)),
            ]
        )
        y_mm += 5.9
    return plans


def _workspace_check_plans(surface: PdfSurface, context: SentinelShellContext) -> list[PaintPlan]:
    prefix = component_prefix(_COMPONENT_BASE, 1)
    plans: list[PaintPlan] = [
        Rule(
            component_id=f"{prefix}-workspace-dash",
            color=SENTINEL_BORDER,
        ).plan(surface, PdfRect(14.0, 123.0, 52.0, 0.28)),
        TextBox(
            component_id=f"{prefix}-workspace-title",
            text=str(
                context.copy.get("workspace_check_label") or "Recovery Workspace Check"
            ).upper(),
            style=SENTINEL_THEME.sans_style(size_pt=8.0, bold=True, color=SENTINEL_TEXT),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(14.0, 126.5, 51.0, 4.3)),
    ]
    y_mm = 132.0
    for index, line in enumerate(_copy_lines(context.copy.get("workspace_checklist"))):
        text_plan = TextBox(
            component_id=f"{prefix}-workspace-line-{index}",
            text=line,
            style=SENTINEL_THEME.sans_style(size_pt=7.8, color=SENTINEL_TEXT),
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=1.25,
        ).plan(surface, PdfRect(14.0, y_mm, 51.0, 10.5))
        plans.append(text_plan)
        y_mm += max(8.4, text_plan.proof.used_rect.height_mm + 1.8)
    return plans


def _completion_check_plans(surface: PdfSurface, context: SentinelShellContext) -> list[PaintPlan]:
    prefix = component_prefix(_COMPONENT_BASE, 1)
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-completion-heading-panel",
            stroke=SENTINEL_BORDER,
            fill=SENTINEL_WHITE,
            line_width_mm=0.18,
        ).plan(surface, PdfRect(10.5, 216.5, 59.4, 57.3)),
        TextBox(
            component_id=f"{prefix}-completion-title",
            text=str(
                context.copy.get("completion_check_label") or "Recovery Completion Check"
            ).upper(),
            style=SENTINEL_THEME.sans_style(size_pt=8.8, bold=True, color=SENTINEL_TEXT),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(14.0, 221.0, 51.0, 4.5)),
    ]
    y_mm = 228.0
    for index, line in enumerate(_copy_lines(context.copy.get("completion_checklist"))):
        text_plan = TextBox(
            component_id=f"{prefix}-completion-line-{index}",
            text=line,
            style=SENTINEL_THEME.sans_style(size_pt=7.5, color=SENTINEL_TEXT),
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=1.24,
        ).plan(surface, PdfRect(14.0, y_mm, 51.0, 8.8))
        plans.append(text_plan)
        y_mm += max(7.3, text_plan.proof.used_rect.height_mm + 1.4)
    plans.extend(
        [
            TextBox(
                component_id=f"{prefix}-sha-label",
                text=str(context.copy.get("verified_sha_label") or "Verified output SHA-256:"),
                style=SENTINEL_THEME.sans_style(size_pt=7.8, color=SENTINEL_TEXT),
                policy=TextFitPolicy.SHRINK,
                min_size_pt=6.0,
            ).plan(surface, PdfRect(14.0, 256.5, 51.0, 4.0)),
            Panel(
                component_id=f"{prefix}-sha-box",
                stroke=SENTINEL_BORDER,
                fill=SENTINEL_WHITE,
                line_width_mm=0.18,
            ).plan(surface, PdfRect(14.0, 262.0, 52.5, 8.8)),
            Rule(
                component_id=f"{prefix}-sha-line",
                color=SENTINEL_BLACK,
            ).plan(surface, PdfRect(16.5, 268.4, 47.5, 0.22)),
        ]
    )
    return plans


def _transcription_panel_plans(
    surface: PdfSurface,
    context: SentinelShellContext,
    fallback_page: _FallbackPageLayout,
) -> list[PaintPlan]:
    prefix = component_prefix(_COMPONENT_BASE, 1)
    panel_rect = PdfRect(75.2, 57.8, 124.3, 216.0)
    table_rect = _FIRST_FALLBACK_AREA
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-transcription-panel",
            stroke=SENTINEL_BORDER,
            fill=SENTINEL_WHITE,
            line_width_mm=0.22,
        ).plan(surface, panel_rect),
        Panel(
            component_id=f"{prefix}-transcription-heading-panel",
            stroke=SENTINEL_BORDER,
            fill=SENTINEL_BACKGROUND,
            line_width_mm=0.18,
        ).plan(surface, PdfRect(panel_rect.x_mm, panel_rect.y_mm, panel_rect.width_mm, 18.3)),
        TextBox(
            component_id=f"{prefix}-transcription-title",
            text=str(
                context.copy.get("transcription_sequence_label") or "Manual Transcription Sequence"
            ).upper(),
            style=SENTINEL_THEME.sans_style(size_pt=13.0, bold=True, color=SENTINEL_BLACK),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=9.0,
        ).plan(surface, PdfRect(79.7, 62.2, 96.0, 5.8)),
        TextBox(
            component_id=f"{prefix}-transcription-helper",
            text=str(context.copy.get("transcription_helper") or ""),
            style=SENTINEL_THEME.sans_style(size_pt=10.0, color=SENTINEL_TEXT),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=7.2,
        ).plan(surface, PdfRect(79.7, 69.0, 105.0, 4.8)),
        Panel(
            component_id=f"{prefix}-fallback-table",
            stroke=SENTINEL_GRID_LINE,
            fill=SENTINEL_WHITE,
            line_width_mm=0.2,
        ).plan(surface, table_rect),
    ]
    plans.extend(
        _first_page_fallback_rows(
            surface,
            fallback_page,
            table_rect,
            page_layout=context.page_layout,
        )
    )
    return plans


def _first_page_fallback_rows(
    surface: PdfSurface,
    fallback_page: _FallbackPageLayout,
    table_rect: PdfRect,
    *,
    page_layout: SentinelPageLayout,
) -> list[PaintPlan]:
    prefix = component_prefix(_COMPONENT_BASE, fallback_page.page_number)
    plans: list[PaintPlan] = []
    for index, page_entry in enumerate(fallback_page.entries):
        row_rect = _row_rect(table_rect, page_entry.row_index, fallback_page.row_height_mm)
        if isinstance(page_entry.entry, _FallbackTitleEntry):
            plans.extend(
                _fallback_title_row(
                    surface,
                    prefix,
                    page_entry.entry.title,
                    row_rect,
                    index,
                    page_layout=page_layout,
                )
            )
        else:
            plans.extend(
                _fallback_line_row(
                    surface,
                    prefix,
                    page_entry.entry,
                    row_rect,
                    index,
                    display_line_number=page_entry.display_line_number,
                    page_layout=page_layout,
                )
            )

    used_rows = {entry.row_index for entry in fallback_page.entries}
    for row_index in range(fallback_page.row_capacity):
        if row_index not in used_rows:
            row_rect = _row_rect(table_rect, row_index, fallback_page.row_height_mm)
            plans.append(
                Rule(
                    component_id=f"{prefix}-fallback-filler-rule-{row_index}",
                    color=SENTINEL_GRID_LINE,
                ).plan(surface, PdfRect(row_rect.x_mm, row_rect.bottom_mm, row_rect.width_mm, 0.2))
            )
    return plans


def _fallback_title_row(
    surface: PdfSurface,
    prefix: str,
    title: str,
    row_rect: PdfRect,
    index: int,
    *,
    page_layout: SentinelPageLayout,
) -> list[PaintPlan]:
    text_rect = _centered_physical_row_content_rect(
        row_rect,
        page_layout=page_layout,
        x_offset_mm=6.0,
        width_mm=row_rect.width_mm - 12.0,
        preferred_height_mm=3.5,
    )
    return [
        Panel(
            component_id=f"{prefix}-fallback-title-fill-{index}",
            stroke=SENTINEL_GRID_LINE,
            fill=SENTINEL_LINE_FILL,
            line_width_mm=0.14,
        ).plan(surface, row_rect),
        TextBox(
            component_id=f"{prefix}-fallback-title-{index}",
            text=title.upper(),
            style=SENTINEL_THEME.mono_style(size_pt=7.0, bold=True, color=SENTINEL_TEXT),
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.CENTER,
            min_size_pt=6.0,
        ).plan(surface, text_rect),
    ]


def _fallback_line_row(
    surface: PdfSurface,
    prefix: str,
    entry: _FallbackLineEntry,
    row_rect: PdfRect,
    index: int,
    *,
    display_line_number: int | None,
    page_layout: SentinelPageLayout,
) -> list[PaintPlan]:
    if display_line_number is None:
        raise ValueError("fallback payload line is missing its display number")
    number_rect = _centered_physical_row_content_rect(
        row_rect,
        page_layout=page_layout,
        x_offset_mm=_FIRST_FALLBACK_NUMBER_LEFT_INSET_MM,
        width_mm=_FIRST_FALLBACK_NUMBER_WIDTH_MM,
        preferred_height_mm=3.5,
    )
    text_x_offset_mm = (
        _FIRST_FALLBACK_NUMBER_LEFT_INSET_MM
        + _FIRST_FALLBACK_NUMBER_WIDTH_MM
        + _FIRST_FALLBACK_NUMBER_GAP_MM
    )
    text_rect = _centered_physical_row_content_rect(
        row_rect,
        page_layout=page_layout,
        x_offset_mm=text_x_offset_mm,
        width_mm=row_rect.width_mm - text_x_offset_mm - _FIRST_FALLBACK_RIGHT_INSET_MM,
        preferred_height_mm=3.5,
    )
    return [
        Rule(
            component_id=f"{prefix}-fallback-line-rule-{index}",
            color=SENTINEL_GRID_LINE,
        ).plan(surface, PdfRect(row_rect.x_mm, row_rect.bottom_mm, row_rect.width_mm, 0.2)),
        TextBox(
            component_id=f"{prefix}-fallback-line-number-{index}",
            text=f"{display_line_number:02d}.",
            style=SENTINEL_THEME.mono_style(size_pt=7.0, color=SENTINEL_TEXT),
            policy=TextFitPolicy.FAIL,
            align=TextAlign.RIGHT,
        ).plan(surface, number_rect),
        TextBox(
            component_id=f"{prefix}-fallback-line-text-{index}",
            text=entry.text,
            style=SENTINEL_THEME.mono_style(
                size_pt=_FIRST_FALLBACK_BODY_SIZE_PT,
                color=SENTINEL_TEXT,
            ),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=_FALLBACK_MINIMUM_BODY_SIZE_PT,
        ).plan(surface, text_rect),
    ]


def _metadata_plans(surface: PdfSurface, recovery_meta: RecoveryMeta) -> list[PaintPlan]:
    plans: list[PaintPlan] = []
    y_mm = 219.5
    for index, row in enumerate(_metadata_rows(recovery_meta)):
        row_plans, y_mm = _metadata_row_plans(surface, row, index=index, y_mm=y_mm)
        plans.extend(row_plans)
    return plans


def _metadata_rows(meta: RecoveryMeta) -> tuple[_SentinelMetadataRow, ...]:
    rows: list[_SentinelMetadataRow] = []
    if meta.quorum_value:
        rows.append(_SentinelMetadataRow(meta.quorum_label, (meta.quorum_value,)))
    if meta.passphrase_lines:
        passphrase = recovery_passphrase_display(meta)
        passphrase_lines = (
            passphrase.value_lines
            if meta.passphrase_print_mode == PASSPHRASE_PRINT_MODE_JSON_PARTS
            else (" ".join(passphrase.value_lines),)
        )
        rows.append(
            _SentinelMetadataRow(
                passphrase.label,
                passphrase_lines,
                passphrase.guidance,
            )
        )
    elif meta.passphrase:
        rows.append(_SentinelMetadataRow(meta.passphrase_label, (meta.passphrase,)))
    if meta.signing_pub_lines:
        rows.append(
            _SentinelMetadataRow(
                "Master Signing Public Key",
                tuple(meta.signing_pub_lines),
            )
        )
    return tuple(rows)


def _metadata_value_style() -> TextStyle:
    return SENTINEL_THEME.mono_style(size_pt=8.7, color=SENTINEL_TEXT)


def _metadata_guidance_style() -> TextStyle:
    return SENTINEL_THEME.sans_style(size_pt=6.4, color=SENTINEL_MUTED)


def _metadata_row_advance_mm(
    surface: PdfSurface,
    row: _SentinelMetadataRow,
) -> float:
    guidance_height_mm = 0.0
    if row.guidance:
        guidance_height_mm = (
            fit_text_to_width(
                surface,
                row.guidance,
                _metadata_guidance_style(),
                max_width_mm=110.2,
                policy=TextFitPolicy.WRAP,
                line_height_multiplier=1.15,
            ).height_mm
            + 1.0
        )
    measured_value = fit_text_to_width(
        surface,
        "\n".join(row.value_lines),
        _metadata_value_style(),
        max_width_mm=110.2,
        policy=TextFitPolicy.WRAP,
        line_height_multiplier=1.15,
    )
    box_height_mm = max(8.7, guidance_height_mm + measured_value.height_mm + 5.0)
    return 4.9 + box_height_mm + 3.0


def _metadata_row_plans(
    surface: PdfSurface,
    row: _SentinelMetadataRow,
    *,
    index: int,
    y_mm: float,
) -> tuple[list[PaintPlan], float]:
    text = "\n".join(row.value_lines)
    value_style = _metadata_value_style()
    guidance_height_mm = 0.0
    if row.guidance:
        guidance_height_mm = (
            fit_text_to_width(
                surface,
                row.guidance,
                _metadata_guidance_style(),
                max_width_mm=110.2,
                policy=TextFitPolicy.WRAP,
                line_height_multiplier=1.15,
            ).height_mm
            + 1.0
        )
    measured_value = fit_text_to_width(
        surface,
        text,
        value_style,
        max_width_mm=110.2,
        policy=TextFitPolicy.WRAP,
        line_height_multiplier=1.15,
    )
    box_height = max(8.7, guidance_height_mm + measured_value.height_mm + 5.0)
    box_y = y_mm + 4.9
    if box_y + box_height > 273.0:
        raise ValueError("recovery metadata exceeds the direct Sentinel metadata area")
    plans: list[PaintPlan] = [
        TextBox(
            component_id=f"sentinel-recovery-p1-metadata-label-{index}",
            text=row.label.upper(),
            style=SENTINEL_THEME.sans_style(size_pt=8.0, bold=True, color=SENTINEL_TEXT),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(79.7, y_mm, 112.0, 4.2)),
        Panel(
            component_id=f"sentinel-recovery-p1-metadata-box-{index}",
            stroke=SENTINEL_BORDER,
            fill=SENTINEL_LINE_FILL,
            line_width_mm=0.18,
        ).plan(surface, PdfRect(79.7, box_y, 115.2, box_height)),
    ]
    value_y_mm = box_y + 2.0
    if row.guidance:
        plans.append(
            TextBox(
                component_id=f"sentinel-recovery-p1-metadata-guidance-{index}",
                text=row.guidance,
                style=_metadata_guidance_style(),
                policy=TextFitPolicy.WRAP,
                line_height_multiplier=1.15,
            ).plan(
                surface,
                PdfRect(82.2, value_y_mm, 110.2, guidance_height_mm - 1.0),
            )
        )
        value_y_mm += guidance_height_mm
    plans.append(
        TextBox(
            component_id=f"sentinel-recovery-p1-metadata-value-{index}",
            text=text,
            style=value_style,
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=1.15,
        ).plan(
            surface,
            PdfRect(82.2, value_y_mm, 110.2, box_y + box_height - 2.0 - value_y_mm),
        )
    )
    return plans, box_y + box_height + 3.0


def _continuation_body_plans(
    surface: PdfSurface,
    context: SentinelShellContext,
    fallback_page: _FallbackPageLayout,
) -> list[PaintPlan]:
    prefix = component_prefix(_COMPONENT_BASE, fallback_page.page_number)
    table_rect = PdfRect(15.0, 73.0, 180.0, 180.0)
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-continuation-hint-panel",
            stroke=SENTINEL_ORANGE,
            fill=SENTINEL_WARNING_FILL,
            line_width_mm=0.18,
        ).plan(surface, PdfRect(15.0, 34.0, 180.0, 11.0)),
        TextBox(
            component_id=f"{prefix}-continuation-icon",
            text=_ICON_INFO,
            style=SENTINEL_THEME.symbol_style(size_pt=13.0, color=SENTINEL_ORANGE),
            policy=TextFitPolicy.FAIL,
            line_height_multiplier=1.0,
        ).plan(surface, PdfRect(18.0, 37.0, 6.0, 6.0)),
        TextBox(
            component_id=f"{prefix}-continuation-text",
            text=str(context.copy.get("continuation_hint") or ""),
            style=SENTINEL_THEME.sans_style(size_pt=8.5, bold=True, color=SENTINEL_BLACK),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.4,
        ).plan(surface, PdfRect(26.0, 37.4, 160.0, 4.0)),
        Panel(
            component_id=f"{prefix}-continuation-table",
            stroke=SENTINEL_BORDER,
            fill=SENTINEL_WHITE,
            line_width_mm=0.2,
        ).plan(surface, table_rect),
        Rule(
            component_id=f"{prefix}-continuation-heading-rule",
            color=SENTINEL_BLACK,
        ).plan(surface, PdfRect(table_rect.x_mm, table_rect.y_mm + 7.2, table_rect.width_mm, 0.35)),
        TextBox(
            component_id=f"{prefix}-continuation-index-label",
            text=str(context.copy.get("index_label") or "Idx").upper(),
            style=SENTINEL_THEME.sans_style(size_pt=6.8, bold=True, color=SENTINEL_TEXT),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(table_rect.x_mm + 4.0, table_rect.y_mm + 2.6, 16.0, 3.4)),
        TextBox(
            component_id=f"{prefix}-continuation-data-label",
            text=str(context.copy.get("data_entry_label") or "Data Entry Block").upper(),
            style=SENTINEL_THEME.sans_style(size_pt=6.8, bold=True, color=SENTINEL_TEXT),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(table_rect.x_mm + 26.0, table_rect.y_mm + 2.6, 80.0, 3.4)),
        TextBox(
            component_id=f"{prefix}-continuation-verify-label",
            text=str(context.copy.get("verify_label") or "Verify").upper(),
            style=SENTINEL_THEME.sans_style(size_pt=6.8, bold=True, color=SENTINEL_TEXT),
            policy=TextFitPolicy.FAIL,
            align=TextAlign.CENTER,
        ).plan(surface, PdfRect(table_rect.right_mm - 28.0, table_rect.y_mm + 2.6, 20.0, 3.4)),
    ]
    plans.extend(
        _continuation_fallback_rows(
            surface,
            fallback_page,
            table_rect,
            page_layout=context.page_layout,
        )
    )
    return plans


def _continuation_fallback_rows(
    surface: PdfSurface,
    fallback_page: _FallbackPageLayout,
    table_rect: PdfRect,
    *,
    page_layout: SentinelPageLayout,
) -> list[PaintPlan]:
    prefix = component_prefix(_COMPONENT_BASE, fallback_page.page_number)
    _ = table_rect
    body_rect = _CONTINUATION_FALLBACK_AREA
    plans: list[PaintPlan] = []
    for index, page_entry in enumerate(fallback_page.entries):
        row_rect = _row_rect(body_rect, page_entry.row_index, fallback_page.row_height_mm)
        if isinstance(page_entry.entry, _FallbackTitleEntry):
            plans.extend(
                _continuation_title_row(
                    surface,
                    prefix,
                    page_entry.entry.title,
                    row_rect,
                    index,
                    page_layout=page_layout,
                )
            )
        else:
            plans.extend(
                _continuation_line_row(
                    surface,
                    prefix,
                    page_entry.entry,
                    row_rect,
                    index,
                    display_line_number=page_entry.display_line_number,
                    page_layout=page_layout,
                )
            )
    return plans


def _continuation_title_row(
    surface: PdfSurface,
    prefix: str,
    title: str,
    row_rect: PdfRect,
    index: int,
    *,
    page_layout: SentinelPageLayout,
) -> list[PaintPlan]:
    text_rect = _centered_physical_row_content_rect(
        row_rect,
        page_layout=page_layout,
        x_offset_mm=24.0,
        width_mm=90.0,
        preferred_height_mm=3.5,
    )
    return [
        TextBox(
            component_id=f"{prefix}-fallback-title-{index}",
            text=title.upper(),
            style=SENTINEL_THEME.sans_style(size_pt=6.8, bold=True, color=SENTINEL_MUTED),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(surface, text_rect),
    ]


def _continuation_line_row(
    surface: PdfSurface,
    prefix: str,
    entry: _FallbackLineEntry,
    row_rect: PdfRect,
    index: int,
    *,
    display_line_number: int | None,
    page_layout: SentinelPageLayout,
) -> list[PaintPlan]:
    if display_line_number is None:
        raise ValueError("fallback payload line is missing its display number")
    number_rect = _centered_physical_row_content_rect(
        row_rect,
        page_layout=page_layout,
        x_offset_mm=0.0,
        width_mm=17.0,
        preferred_height_mm=4.0,
    )
    text_rect = _centered_physical_row_content_rect(
        row_rect,
        page_layout=page_layout,
        x_offset_mm=22.0,
        width_mm=112.0,
        preferred_height_mm=3.7,
    )
    icon_rect = _centered_physical_row_content_rect(
        row_rect,
        page_layout=page_layout,
        x_offset_mm=151.0,
        width_mm=9.0,
        preferred_height_mm=4.5,
    )
    return [
        TextBox(
            component_id=f"{prefix}-fallback-line-number-{index}",
            text=f"{display_line_number:02d}.",
            style=SENTINEL_THEME.mono_style(size_pt=8.5, bold=True, color=SENTINEL_MUTED),
            policy=TextFitPolicy.FAIL,
            align=TextAlign.RIGHT,
        ).plan(surface, number_rect),
        Panel(
            component_id=f"{prefix}-fallback-line-box-{index}",
            stroke=SENTINEL_BORDER,
            fill=SENTINEL_WHITE,
            line_width_mm=0.15,
        ).plan(surface, PdfRect(row_rect.x_mm + 20.0, row_rect.y_mm, 116.0, row_rect.height_mm)),
        TextBox(
            component_id=f"{prefix}-fallback-line-text-{index}",
            text=entry.text,
            style=SENTINEL_THEME.mono_style(
                size_pt=_CONTINUATION_FALLBACK_BODY_SIZE_PT,
                color=SENTINEL_TEXT,
            ),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=_FALLBACK_MINIMUM_BODY_SIZE_PT,
        ).plan(surface, text_rect),
        Panel(
            component_id=f"{prefix}-fallback-verify-box-{index}",
            stroke=SENTINEL_BORDER,
            fill=SENTINEL_LINE_FILL,
            line_width_mm=0.15,
        ).plan(surface, PdfRect(row_rect.x_mm + 141.0, row_rect.y_mm, 31.0, row_rect.height_mm)),
        TextBox(
            component_id=f"{prefix}-fallback-verify-icon-{index}",
            text=_ICON_CHECK_CIRCLE,
            style=SENTINEL_THEME.symbol_style(size_pt=9.0, color=SENTINEL_GRID_LINE),
            policy=TextFitPolicy.FAIL,
            align=TextAlign.CENTER,
            line_height_multiplier=1.0,
        ).plan(surface, icon_rect),
    ]


def _centered_physical_row_content_rect(
    row_rect: PdfRect,
    *,
    page_layout: SentinelPageLayout,
    x_offset_mm: float,
    width_mm: float,
    preferred_height_mm: float,
) -> PdfRect:
    """Place fallback text directly inside the row's measured physical rectangle."""

    mapped_row = page_layout.map_rect(row_rect)
    available_height_mm = mapped_row.height_mm - 0.4
    if available_height_mm <= 0:
        raise ValueError("Sentinel fallback row has no readable text height")
    content_height_mm = min(preferred_height_mm, available_height_mm)
    return PdfRect(
        mapped_row.x_mm + x_offset_mm,
        mapped_row.y_mm + (mapped_row.height_mm - content_height_mm) / 2.0,
        width_mm,
        content_height_mm,
    )


def _physical_fallback_text_component_ids(
    fallback_page: _FallbackPageLayout,
) -> tuple[str, ...]:
    prefix = component_prefix(_COMPONENT_BASE, fallback_page.page_number)
    component_ids: list[str] = []
    for index, page_entry in enumerate(fallback_page.entries):
        if isinstance(page_entry.entry, _FallbackTitleEntry):
            component_ids.append(f"{prefix}-fallback-title-{index}")
            continue
        component_ids.extend(
            (
                f"{prefix}-fallback-line-number-{index}",
                f"{prefix}-fallback-line-text-{index}",
            )
        )
        if fallback_page.page_number > 1:
            component_ids.append(f"{prefix}-fallback-verify-icon-{index}")
    return tuple(component_ids)


def _row_rect(area: PdfRect, row_index: int, row_height_mm: float) -> PdfRect:
    return PdfRect(
        area.x_mm,
        area.y_mm + row_index * row_height_mm,
        area.width_mm,
        min(row_height_mm, area.height_mm - row_index * row_height_mm),
    )


def _copy_lines(value: object) -> tuple[str, ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(str(item) for item in value)
    if isinstance(value, str) and value.strip():
        return (value,)
    return ()


__all__ = [
    "SentinelRecoveryDirectPlan",
    "build_sentinel_recovery_direct_plan",
    "render_sentinel_recovery_direct_pdf",
]
