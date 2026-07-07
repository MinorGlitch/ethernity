"""Sentinel recovery document rendering through direct PDF primitives."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ethernity.encoding.framing import encode_frame
from ethernity.encoding.zbase32 import encode_zbase32
from ethernity.render.direct_pdf.assets import packaged_direct_pdf_assets
from ethernity.render.direct_pdf.components import Panel, Rule, TextAlign, TextBox
from ethernity.render.direct_pdf.debug import write_direct_layout_debug_json
from ethernity.render.direct_pdf.layout_proof import build_direct_layout_proof
from ethernity.render.direct_pdf.page import DirectPdfPagePlan, PaintPlan, build_page_plan
from ethernity.render.direct_pdf.sentinel_common import (
    SENTINEL_BACKGROUND,
    SENTINEL_BLACK,
    SENTINEL_BORDER,
    SENTINEL_GRID_LINE,
    SENTINEL_LINE_FILL,
    SENTINEL_MUTED,
    SENTINEL_ORANGE,
    SENTINEL_PAGE_RECT,
    SENTINEL_TEXT,
    SENTINEL_WARNING_FILL,
    SENTINEL_WHITE,
    SentinelShellContext,
    build_sentinel_footer_plans,
    build_sentinel_header_plans,
    build_sentinel_shell_context,
    build_sentinel_surface,
    sentinel_component_prefix,
)
from ethernity.render.direct_pdf.sentinel_theme import SENTINEL_THEME
from ethernity.render.direct_pdf.surface import PdfSurface
from ethernity.render.direct_pdf.text_fit import TextFitPolicy, fit_text_to_width
from ethernity.render.direct_pdf.types import PdfRect
from ethernity.render.doc_types import DOC_TYPE_RECOVERY
from ethernity.render.fallback import fallback_section_title
from ethernity.render.fallback_text import format_zbase32_lines
from ethernity.render.proofs import build_render_artifact_proof, frame_digest
from ethernity.render.recovery_meta import RecoveryMeta
from ethernity.render.types import (
    FallbackSection,
    RenderArtifactProof,
    RenderFallbackProof,
    RenderInputs,
    RenderResult,
)

_COMPONENT_BASE = "sentinel-recovery"
_FALLBACK_GROUP_SIZE = 4
_FALLBACK_LINE_LENGTH = 59
_FIRST_PAGE_ROW_HEIGHT_MM = 5.8
_CONTINUATION_ROW_HEIGHT_MM = 5.8
_FIRST_PAGE_MAX_ROWS = 24
_CONTINUATION_MAX_ROWS = 28
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


@dataclass(frozen=True)
class _FallbackPageLayout:
    page_number: int
    entries: tuple[_FallbackPageEntry, ...]
    row_capacity: int
    row_height_mm: float


def render_sentinel_recovery_direct_pdf(inputs: RenderInputs) -> RenderResult:
    """Render a Sentinel recovery document directly to PDF and return validation proofs."""

    surface = build_sentinel_surface()
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
    sections = _fallback_sections(inputs.fallback_sections or ())
    fallback_pages = _paginate_fallback_entries(_fallback_entries(sections))
    page_plans = tuple(
        _build_page(
            surface,
            context,
            recovery_meta=recovery_meta,
            fallback_page=fallback_page,
            total_pages=len(fallback_pages),
        )
        for fallback_page in fallback_pages
    )
    fallback_proof = _build_fallback_proof(inputs, sections, fallback_pages)
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

    paper_size = str(inputs.context.get("paper_size") or "A4").strip().lower()
    if paper_size != "a4":
        raise ValueError("direct Sentinel recovery renderer currently supports A4 paper only")


def _fallback_sections(sections: Sequence[FallbackSection]) -> tuple[_FallbackSectionLines, ...]:
    resolved: list[_FallbackSectionLines] = []
    for index, section in enumerate(sections):
        encoded = encode_zbase32(encode_frame(section.frame))
        lines = format_zbase32_lines(
            encoded,
            group_size=_FALLBACK_GROUP_SIZE,
            line_length=_FALLBACK_LINE_LENGTH,
            line_count=None,
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


def _paginate_fallback_entries(
    entries: Sequence[_FallbackEntry],
) -> tuple[_FallbackPageLayout, ...]:
    if not entries:
        raise ValueError("direct Sentinel recovery renderer has no fallback entries to render")

    remaining = tuple(entries)
    page_number = 1
    pages: list[_FallbackPageLayout] = []
    while remaining:
        row_capacity = _FIRST_PAGE_MAX_ROWS if page_number == 1 else _CONTINUATION_MAX_ROWS
        row_height = _FIRST_PAGE_ROW_HEIGHT_MM if page_number == 1 else _CONTINUATION_ROW_HEIGHT_MM
        page_entries, consumed = _consume_page_entries(remaining, row_capacity=row_capacity)
        if consumed <= 0:
            raise ValueError("fallback layout cannot fit even one entry on a page")
        pages.append(
            _FallbackPageLayout(
                page_number=page_number,
                entries=page_entries,
                row_capacity=row_capacity,
                row_height_mm=row_height,
            )
        )
        remaining = remaining[consumed:]
        page_number += 1
    return tuple(pages)


def _consume_page_entries(
    entries: Sequence[_FallbackEntry],
    *,
    row_capacity: int,
) -> tuple[tuple[_FallbackPageEntry, ...], int]:
    placed: list[_FallbackPageEntry] = []
    row_index = 0
    consumed = 0
    for index, entry in enumerate(entries):
        required_rows = 1
        if isinstance(entry, _FallbackTitleEntry):
            next_entry = entries[index + 1] if index + 1 < len(entries) else None
            required_rows = 2 if isinstance(next_entry, _FallbackLineEntry) else 1
        if row_index + required_rows > row_capacity:
            break
        placed.append(_FallbackPageEntry(entry=entry, row_index=row_index))
        row_index += 1
        consumed += 1
    return tuple(placed), consumed


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
    return build_page_plan(page_number=page_number, rect=SENTINEL_PAGE_RECT, plans=plans)


def _warning_plans(
    surface: PdfSurface,
    context: SentinelShellContext,
    *,
    page_number: int,
) -> list[PaintPlan]:
    prefix = sentinel_component_prefix(_COMPONENT_BASE, page_number)
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
    prefix = sentinel_component_prefix(_COMPONENT_BASE, 1)
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
    prefix = sentinel_component_prefix(_COMPONENT_BASE, 1)
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
        ).plan(surface, PdfRect(14.0, 85.0, 52.5, 34.0)),
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
                    min_size_pt=5.6,
                ).plan(surface, PdfRect(16.0, y_mm, 23.0, 4.2)),
                TextBox(
                    component_id=f"{prefix}-session-row-value-{index}",
                    text=value,
                    style=SENTINEL_THEME.mono_style(size_pt=7.4, color=SENTINEL_TEXT),
                    policy=TextFitPolicy.SHRINK,
                    align=TextAlign.RIGHT,
                    min_size_pt=4.5,
                ).plan(surface, PdfRect(38.0, y_mm, 26.0, 4.2)),
            ]
        )
        y_mm += 5.9
    return plans


def _workspace_check_plans(surface: PdfSurface, context: SentinelShellContext) -> list[PaintPlan]:
    prefix = sentinel_component_prefix(_COMPONENT_BASE, 1)
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
    prefix = sentinel_component_prefix(_COMPONENT_BASE, 1)
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
                min_size_pt=5.8,
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
    prefix = sentinel_component_prefix(_COMPONENT_BASE, 1)
    panel_rect = PdfRect(75.2, 57.8, 124.3, 216.0)
    table_rect = PdfRect(79.7, 80.5, 115.2, 133.8)
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
    plans.extend(_first_page_fallback_rows(surface, fallback_page, table_rect))
    return plans


def _first_page_fallback_rows(
    surface: PdfSurface,
    fallback_page: _FallbackPageLayout,
    table_rect: PdfRect,
) -> list[PaintPlan]:
    prefix = sentinel_component_prefix(_COMPONENT_BASE, fallback_page.page_number)
    plans: list[PaintPlan] = []
    for index, page_entry in enumerate(fallback_page.entries):
        row_rect = _row_rect(table_rect, page_entry.row_index, fallback_page.row_height_mm)
        if isinstance(page_entry.entry, _FallbackTitleEntry):
            plans.extend(
                _fallback_title_row(surface, prefix, page_entry.entry.title, row_rect, index)
            )
        else:
            plans.extend(_fallback_line_row(surface, prefix, page_entry.entry, row_rect, index))

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
) -> list[PaintPlan]:
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
            min_size_pt=5.2,
        ).plan(
            surface,
            PdfRect(row_rect.x_mm + 6.0, row_rect.y_mm + 1.6, row_rect.width_mm - 12.0, 3.5),
        ),
    ]


def _fallback_line_row(
    surface: PdfSurface,
    prefix: str,
    entry: _FallbackLineEntry,
    row_rect: PdfRect,
    index: int,
) -> list[PaintPlan]:
    return [
        Rule(
            component_id=f"{prefix}-fallback-line-rule-{index}",
            color=SENTINEL_GRID_LINE,
        ).plan(surface, PdfRect(row_rect.x_mm, row_rect.bottom_mm, row_rect.width_mm, 0.2)),
        TextBox(
            component_id=f"{prefix}-fallback-line-number-{index}",
            text=f"{entry.line_number:02d}.",
            style=SENTINEL_THEME.mono_style(size_pt=7.0, color=SENTINEL_TEXT),
            policy=TextFitPolicy.FAIL,
            align=TextAlign.RIGHT,
        ).plan(surface, PdfRect(row_rect.x_mm + 3.0, row_rect.y_mm + 1.7, 8.8, 3.5)),
        TextBox(
            component_id=f"{prefix}-fallback-line-text-{index}",
            text=entry.text,
            style=SENTINEL_THEME.mono_style(size_pt=6.6, color=SENTINEL_TEXT),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=4.8,
        ).plan(surface, PdfRect(row_rect.x_mm + 14.0, row_rect.y_mm + 1.7, 96.0, 3.5)),
    ]


def _metadata_plans(surface: PdfSurface, recovery_meta: RecoveryMeta) -> list[PaintPlan]:
    plans: list[PaintPlan] = []
    y_mm = 219.5
    for index, row in enumerate(_metadata_rows(recovery_meta)):
        row_plans, y_mm = _metadata_row_plans(surface, row, index=index, y_mm=y_mm)
        plans.extend(row_plans)
    return plans


def _metadata_rows(meta: RecoveryMeta) -> tuple[tuple[str, tuple[str, ...]], ...]:
    rows: list[tuple[str, tuple[str, ...]]] = []
    if meta.quorum_value:
        rows.append((meta.quorum_label, (meta.quorum_value,)))
    if meta.passphrase_lines:
        rows.append(("Passphrase", (" ".join(meta.passphrase_lines),)))
    elif meta.passphrase:
        rows.append(("Passphrase", (meta.passphrase,)))
    if meta.signing_pub_lines:
        rows.append(("Master Signing Public Key", tuple(meta.signing_pub_lines)))
    return tuple(rows)


def _metadata_row_plans(
    surface: PdfSurface,
    row: tuple[str, tuple[str, ...]],
    *,
    index: int,
    y_mm: float,
) -> tuple[list[PaintPlan], float]:
    label, lines = row
    text = "\n".join(lines)
    value_style = SENTINEL_THEME.mono_style(size_pt=8.7, color=SENTINEL_TEXT)
    measured_value = fit_text_to_width(
        surface,
        text,
        value_style,
        max_width_mm=110.2,
        policy=TextFitPolicy.WRAP,
        line_height_multiplier=1.15,
    )
    box_height = max(8.7, measured_value.height_mm + 5.0)
    box_y = y_mm + 4.9
    if box_y + box_height > 273.0:
        raise ValueError("recovery metadata exceeds the direct Sentinel metadata area")
    plans: list[PaintPlan] = [
        TextBox(
            component_id=f"sentinel-recovery-p1-metadata-label-{index}",
            text=label.upper(),
            style=SENTINEL_THEME.sans_style(size_pt=8.0, bold=True, color=SENTINEL_TEXT),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=5.2,
        ).plan(surface, PdfRect(79.7, y_mm, 112.0, 4.2)),
        Panel(
            component_id=f"sentinel-recovery-p1-metadata-box-{index}",
            stroke=SENTINEL_BORDER,
            fill=SENTINEL_LINE_FILL,
            line_width_mm=0.18,
        ).plan(surface, PdfRect(79.7, box_y, 115.2, box_height)),
        TextBox(
            component_id=f"sentinel-recovery-p1-metadata-value-{index}",
            text=text,
            style=value_style,
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=1.15,
        ).plan(surface, PdfRect(82.2, box_y + 2.0, 110.2, box_height - 4.0)),
    ]
    return plans, box_y + box_height + 3.0


def _continuation_body_plans(
    surface: PdfSurface,
    context: SentinelShellContext,
    fallback_page: _FallbackPageLayout,
) -> list[PaintPlan]:
    prefix = sentinel_component_prefix(_COMPONENT_BASE, fallback_page.page_number)
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
    plans.extend(_continuation_fallback_rows(surface, fallback_page, table_rect))
    return plans


def _continuation_fallback_rows(
    surface: PdfSurface,
    fallback_page: _FallbackPageLayout,
    table_rect: PdfRect,
) -> list[PaintPlan]:
    prefix = sentinel_component_prefix(_COMPONENT_BASE, fallback_page.page_number)
    body_rect = PdfRect(
        table_rect.x_mm + 3.0,
        table_rect.y_mm + 10.0,
        table_rect.width_mm - 6.0,
        166.0,
    )
    plans: list[PaintPlan] = []
    for index, page_entry in enumerate(fallback_page.entries):
        row_rect = _row_rect(body_rect, page_entry.row_index, fallback_page.row_height_mm)
        if isinstance(page_entry.entry, _FallbackTitleEntry):
            plans.extend(
                _continuation_title_row(surface, prefix, page_entry.entry.title, row_rect, index)
            )
        else:
            plans.extend(_continuation_line_row(surface, prefix, page_entry.entry, row_rect, index))
    return plans


def _continuation_title_row(
    surface: PdfSurface,
    prefix: str,
    title: str,
    row_rect: PdfRect,
    index: int,
) -> list[PaintPlan]:
    return [
        TextBox(
            component_id=f"{prefix}-fallback-title-{index}",
            text=title.upper(),
            style=SENTINEL_THEME.sans_style(size_pt=6.8, bold=True, color=SENTINEL_MUTED),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=5.0,
        ).plan(surface, PdfRect(row_rect.x_mm + 24.0, row_rect.y_mm + 1.6, 90.0, 3.5)),
    ]


def _continuation_line_row(
    surface: PdfSurface,
    prefix: str,
    entry: _FallbackLineEntry,
    row_rect: PdfRect,
    index: int,
) -> list[PaintPlan]:
    return [
        TextBox(
            component_id=f"{prefix}-fallback-line-number-{index}",
            text=f"{entry.line_number:02d}.",
            style=SENTINEL_THEME.mono_style(size_pt=8.5, bold=True, color=SENTINEL_MUTED),
            policy=TextFitPolicy.FAIL,
            align=TextAlign.RIGHT,
        ).plan(surface, PdfRect(row_rect.x_mm, row_rect.y_mm + 1.2, 17.0, 4.0)),
        Panel(
            component_id=f"{prefix}-fallback-line-box-{index}",
            stroke=SENTINEL_BORDER,
            fill=SENTINEL_WHITE,
            line_width_mm=0.15,
        ).plan(surface, PdfRect(row_rect.x_mm + 20.0, row_rect.y_mm, 116.0, row_rect.height_mm)),
        TextBox(
            component_id=f"{prefix}-fallback-line-text-{index}",
            text=entry.text,
            style=SENTINEL_THEME.mono_style(size_pt=6.8, color=SENTINEL_TEXT),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=4.8,
        ).plan(surface, PdfRect(row_rect.x_mm + 22.0, row_rect.y_mm + 1.5, 112.0, 3.7)),
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
        ).plan(surface, PdfRect(row_rect.x_mm + 151.0, row_rect.y_mm + 1.5, 9.0, 4.5)),
    ]


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
