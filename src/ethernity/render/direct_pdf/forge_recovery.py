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
from ethernity.encoding.zbase32 import encode_zbase32
from ethernity.render.direct_pdf.assets import packaged_direct_pdf_assets
from ethernity.render.direct_pdf.components import (
    Panel,
    Rule,
    TextAlign,
    TextBox,
)
from ethernity.render.direct_pdf.debug import write_direct_layout_debug_json
from ethernity.render.direct_pdf.forge_common import (
    FORGE_CONTENT_WIDTH_MM,
    FORGE_CONTENT_X_MM,
    FORGE_PAGE_RECT,
    FORGE_SLATE_50,
    FORGE_SLATE_100,
    FORGE_SLATE_200,
    FORGE_SLATE_300,
    FORGE_SLATE_500,
    FORGE_SLATE_600,
    FORGE_SLATE_800,
    FORGE_SLATE_900,
    ForgeShellContext,
    build_forge_footer_plans,
    build_forge_header_plans,
    build_forge_shell_context,
    forge_component_prefix,
)
from ethernity.render.direct_pdf.forge_preview import A4_HEIGHT_MM, A4_WIDTH_MM
from ethernity.render.direct_pdf.forge_theme import FORGE_THEME
from ethernity.render.direct_pdf.layout_proof import build_direct_layout_proof
from ethernity.render.direct_pdf.page import DirectPdfPagePlan, PaintPlan, build_page_plan
from ethernity.render.direct_pdf.surface import FpdfSurface, PdfSurface
from ethernity.render.direct_pdf.text_fit import TextFitPolicy
from ethernity.render.direct_pdf.types import PdfRect
from ethernity.render.doc_types import DOC_TYPE_RECOVERY
from ethernity.render.fallback import fallback_section_title
from ethernity.render.fallback_text import format_zbase32_lines
from ethernity.render.proofs import build_render_artifact_proof, frame_digest
from ethernity.render.recovery_meta import RecoveryMeta
from ethernity.render.template_style import load_template_style
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
_FALLBACK_LINE_NUMBER_WIDTH_MM = 8.5
_FALLBACK_LINE_GAP_MM = 1.5
_FALLBACK_GROUP_SIZE = 4
_FALLBACK_LINE_LENGTH = 44
_FIRST_PAGE_FALLBACK_AREA = PdfRect(FORGE_CONTENT_X_MM, 134.0, FORGE_CONTENT_WIDTH_MM, 70.0)
_CONTINUATION_FALLBACK_AREA = PdfRect(
    FORGE_CONTENT_X_MM,
    78.0,
    FORGE_CONTENT_WIDTH_MM,
    176.0,
)
_ICON_WARNING = chr(0xE002)


@dataclass(frozen=True)
class ForgeRecoveryDirectPlan:
    """Measured pages and app-wide proofs for one direct Forge recovery render."""

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
    column_index: int | None
    display_line_number: int | None


@dataclass(frozen=True)
class _FallbackPageLayout:
    page_number: int
    area: PdfRect
    rows_per_column: int
    entries: tuple[_FallbackPageEntry, ...]


def render_forge_recovery_direct_pdf(inputs: RenderInputs) -> RenderResult:
    """Render a Forge recovery document directly to PDF and return validation proofs."""

    surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
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
    sections = _fallback_sections(inputs.fallback_sections or ())
    capabilities = load_template_style(inputs.design_name).capabilities
    fallback_pages = _paginate_fallback_entries(
        _fallback_entries(sections),
        first_page_single_section=capabilities.recovery_first_page_single_section,
    )
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
    return ForgeRecoveryDirectPlan(
        page_plans=page_plans,
        fallback_proof=fallback_proof,
        artifact_proof=artifact_proof,
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

    paper_size = str(inputs.context.get("paper_size") or "A4").strip().lower()
    if paper_size != "a4":
        raise ValueError("direct Forge recovery renderer currently supports A4 paper only")


def _fallback_sections(sections: Sequence[FallbackSection]) -> tuple[_FallbackSectionLines, ...]:
    resolved: list[_FallbackSectionLines] = []
    for index, section in enumerate(sections):
        encoded = encode_zbase32(encode_frame(section.frame))
        lines = format_zbase32_lines(
            encoded,
            group_size=_FALLBACK_GROUP_SIZE,
            line_length=_FALLBACK_LINE_LENGTH,
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


def _paginate_fallback_entries(
    entries: Sequence[_FallbackEntry],
    *,
    first_page_single_section: bool,
) -> tuple[_FallbackPageLayout, ...]:
    if not entries:
        raise ValueError("direct Forge recovery renderer has no fallback entries to render")

    remaining = tuple(entries)
    page_number = 1
    pages: list[_FallbackPageLayout] = []
    while remaining:
        area = _fallback_area_for_page(page_number)
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


def _fallback_area_for_page(page_number: int) -> PdfRect:
    if page_number <= 1:
        return _FIRST_PAGE_FALLBACK_AREA
    return _CONTINUATION_FALLBACK_AREA


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
    recovery_meta: RecoveryMeta,
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
        )
    )
    plans.extend(_warning_plans(surface, context, page_number=page_number))
    if page_number == 1:
        plans.extend(_instruction_plans(surface, context))
    plans.extend(_fallback_plans(surface, fallback_page))
    if page_number == 1:
        plans.extend(_metadata_plans(surface, recovery_meta))
    plans.extend(
        build_forge_footer_plans(
            surface,
            context,
            page_label=page_label,
            page_number=page_number,
            component_base=_COMPONENT_BASE,
        )
    )
    return build_page_plan(page_number=page_number, rect=FORGE_PAGE_RECT, plans=plans)


def _warning_plans(
    surface: PdfSurface,
    context: ForgeShellContext,
    *,
    page_number: int,
) -> list[PaintPlan]:
    prefix = forge_component_prefix(_COMPONENT_BASE, page_number)
    return [
        Panel(
            component_id=f"{prefix}-warning-panel",
            stroke=FORGE_SLATE_300,
            fill=FORGE_SLATE_100,
            line_width_mm=0.25,
        ).plan(surface, PdfRect(15.0, 68.0, 180.0, 21.0)),
        TextBox(
            component_id=f"{prefix}-warning-icon",
            text=_ICON_WARNING,
            style=FORGE_THEME.symbol_style(size_pt=13.0, color=FORGE_SLATE_900),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=8.0,
        ).plan(surface, PdfRect(20.0, 73.0, 15.0, 7.0)),
        TextBox(
            component_id=f"{prefix}-warning-title",
            text=str(context.copy.get("warning_title") or "Critical Security Warning").upper(),
            style=FORGE_THEME.sans_style(size_pt=9.0, bold=True, color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(38.0, 71.0, 128.0, 5.2)),
        TextBox(
            component_id=f"{prefix}-warning-body",
            text=str(context.copy.get("warning_body") or ""),
            style=FORGE_THEME.sans_style(size_pt=9.0, color=FORGE_SLATE_800),
            policy=TextFitPolicy.WRAP,
        ).plan(surface, PdfRect(38.0, 77.0, 146.0, 9.2)),
    ]


def _instruction_plans(surface: PdfSurface, context: ForgeShellContext) -> list[PaintPlan]:
    body = "\n".join(
        f"{index}. {line}" for index, line in enumerate(context.instruction_lines, start=1)
    )
    return [
        TextBox(
            component_id="forge-recovery-p1-instructions-title",
            text=context.instructions_label.upper(),
            style=FORGE_THEME.sans_style(size_pt=10.5, bold=True, color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(17.0, 99.0, 52.0, 6.0)),
        Rule(
            component_id="forge-recovery-p1-instructions-title-rule",
            color=FORGE_SLATE_900,
        ).plan(surface, PdfRect(17.0, 106.5, 29.0, 0.35)),
        TextBox(
            component_id="forge-recovery-p1-instructions-body",
            text=body,
            style=FORGE_THEME.sans_style(size_pt=10.5, color=FORGE_SLATE_800),
            policy=TextFitPolicy.WRAP,
        ).plan(surface, PdfRect(17.0, 112.0, 168.0, 16.5)),
    ]


def _fallback_plans(
    surface: PdfSurface,
    fallback_page: _FallbackPageLayout,
) -> list[PaintPlan]:
    prefix = forge_component_prefix(_COMPONENT_BASE, fallback_page.page_number)
    area = fallback_page.area
    plans: list[PaintPlan] = []
    for index, page_entry in enumerate(fallback_page.entries):
        if isinstance(page_entry.entry, _FallbackTitleEntry):
            plans.extend(_fallback_title_plans(surface, prefix, page_entry, index, area))
        else:
            plans.extend(_fallback_line_plans(surface, prefix, page_entry, index, area))
    return plans


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
) -> list[PaintPlan]:
    assert isinstance(page_entry.entry, _FallbackLineEntry)
    if page_entry.display_line_number is None:
        raise ValueError("fallback payload line is missing its display number")
    column_index = page_entry.column_index or 0
    column_width = (area.width_mm - _FALLBACK_COLUMN_GAP_MM) / 2.0
    column_x = area.x_mm + 5.0 + column_index * (column_width + _FALLBACK_COLUMN_GAP_MM)
    row_y = area.y_mm + page_entry.row_index * _FALLBACK_ROW_HEIGHT_MM + 0.7
    payload_x = column_x + _FALLBACK_LINE_NUMBER_WIDTH_MM + _FALLBACK_LINE_GAP_MM
    payload_width = column_width - _FALLBACK_LINE_NUMBER_WIDTH_MM - _FALLBACK_LINE_GAP_MM - 5.0
    line_number_text = f"{page_entry.display_line_number:02d}."
    return [
        TextBox(
            component_id=f"{prefix}-fallback-line-number-{index}",
            text=line_number_text,
            style=FORGE_THEME.mono_style(size_pt=10.5, color=FORGE_SLATE_500),
            policy=TextFitPolicy.FAIL,
            align=TextAlign.RIGHT,
        ).plan(
            surface,
            PdfRect(column_x, row_y + 1.0, _FALLBACK_LINE_NUMBER_WIDTH_MM, 4.8),
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
            style=FORGE_THEME.mono_style(size_pt=9.0, color=FORGE_SLATE_800),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.8,
        ).plan(surface, PdfRect(payload_x + 1.8, row_y + 1.0, payload_width - 3.6, 4.4)),
    ]


def _metadata_plans(surface: PdfSurface, recovery_meta: RecoveryMeta) -> list[PaintPlan]:
    plans: list[PaintPlan] = [
        Rule(
            component_id="forge-recovery-p1-metadata-rule",
            color=FORGE_SLATE_900,
        ).plan(surface, PdfRect(15.0, 200.0, 180.0, 0.75)),
        TextBox(
            component_id="forge-recovery-p1-metadata-title",
            text="EXTENDED METADATA",
            style=FORGE_THEME.sans_style(size_pt=10.5, bold=True, color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(17.0, 205.0, 75.0, 6.0)),
    ]
    cursor_y = 212.0
    for index, row in enumerate(_metadata_rows(recovery_meta)):
        row_plans, cursor_y = _metadata_row_plans(surface, row, index=index, y_mm=cursor_y)
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
    line_count = max(1, len(lines))
    box_height = max(7.8, 4.0 * line_count + 2.8)
    box_y = y_mm + 5.2
    if box_y + box_height > 262.0:
        raise ValueError("recovery metadata exceeds the direct Forge first-page metadata area")
    plans: list[PaintPlan] = [
        TextBox(
            component_id=f"forge-recovery-p1-metadata-label-{index}",
            text=label.upper(),
            style=FORGE_THEME.sans_style(size_pt=9.0, bold=True, color=FORGE_SLATE_600),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=4.8,
        ).plan(surface, PdfRect(15.0, y_mm, 180.0, 4.8)),
        Panel(
            component_id=f"forge-recovery-p1-metadata-box-{index}",
            stroke=FORGE_SLATE_300,
            fill=FORGE_SLATE_50,
            line_width_mm=0.2,
        ).plan(surface, PdfRect(15.0, box_y, 180.0, box_height)),
        TextBox(
            component_id=f"forge-recovery-p1-metadata-value-{index}",
            text=text,
            style=FORGE_THEME.mono_style(size_pt=9.0, color=FORGE_SLATE_800),
            policy=TextFitPolicy.WRAP,
        ).plan(surface, PdfRect(18.0, box_y + 2.0, 174.0, box_height - 2.0)),
    ]
    return plans, box_y + box_height + 3.0


__all__ = [
    "ForgeRecoveryDirectPlan",
    "build_forge_recovery_direct_plan",
    "render_forge_recovery_direct_pdf",
]
