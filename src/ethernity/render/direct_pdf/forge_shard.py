"""Forge shard document rendering through direct PDF primitives."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from ethernity.encoding.framing import encode_frame
from ethernity.encoding.zbase32 import encode_zbase32
from ethernity.qr.codec import QrConfig, qr_bytes
from ethernity.render.direct_pdf.assets import packaged_direct_pdf_assets
from ethernity.render.direct_pdf.components import ImageBox, Panel, Rule, TextAlign, TextBox
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
    FORGE_SLATE_700,
    FORGE_SLATE_800,
    FORGE_SLATE_900,
    FORGE_WHITE,
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
from ethernity.render.direct_pdf.types import PdfRect, TextStyle
from ethernity.render.doc_types import DOC_TYPE_SHARD
from ethernity.render.fallback import fallback_section_title
from ethernity.render.fallback_text import format_zbase32_lines
from ethernity.render.proofs import build_render_artifact_proof, frame_digest
from ethernity.render.types import (
    FallbackSection,
    RenderArtifactProof,
    RenderFallbackProof,
    RenderInputs,
    RenderResult,
)

_COMPONENT_BASE = "forge-shard"
_FALLBACK_GROUP_SIZE = 4
_FALLBACK_LINE_LENGTH = 88
_FALLBACK_ROW_HEIGHT_MM = 5.0
_FIRST_PAGE_FALLBACK_AREA = PdfRect(15.0, 232.5, 180.0, 29.0)
_CONTINUATION_FALLBACK_AREA = PdfRect(22.0, 126.0, 166.0, 122.0)
_QR_IMAGE_SIZE_MM = 68.0
_QR_FRAME_SIZE_MM = 82.0
_CONTINUATION_QR_IMAGE_SIZE_MM = 36.0
_ICON_WARNING = chr(0xE002)


@dataclass(frozen=True)
class ForgeShardDirectPlan:
    """Measured pages and app-wide proofs for one direct Forge shard render."""

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
class _FallbackPage:
    page_number: int
    area: PdfRect
    entries: tuple[_FallbackPageEntry, ...]


def render_forge_shard_direct_pdf(inputs: RenderInputs) -> RenderResult:
    """Render a Forge shard document directly to PDF and return validation proofs."""

    surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
    packaged_direct_pdf_assets().register_fonts(surface)
    plan = build_forge_shard_direct_plan(surface, inputs)
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


def build_forge_shard_direct_plan(
    surface: PdfSurface,
    inputs: RenderInputs,
) -> ForgeShardDirectPlan:
    """Build measured direct-PDF plans and render proofs for Forge shard inputs."""

    _validate_inputs(inputs)
    payload = _resolved_qr_payload(inputs)
    qr_image = _qr_image(payload, config=inputs.qr_config or QrConfig())
    context = build_forge_shell_context(inputs, doc_type=inputs.doc_type.strip().lower())
    sections = _fallback_sections(inputs.fallback_sections or ())
    fallback_pages = _paginate_fallback_entries(_fallback_entries(sections))
    page_plans = tuple(
        _build_page(
            surface,
            context,
            fallback_page,
            qr_image=qr_image,
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
    return ForgeShardDirectPlan(
        page_plans=page_plans,
        fallback_proof=fallback_proof,
        artifact_proof=artifact_proof,
    )


def _validate_inputs(inputs: RenderInputs) -> None:
    normalized_doc_type = inputs.doc_type.strip().lower()
    if normalized_doc_type != DOC_TYPE_SHARD:
        raise ValueError("direct Forge shard renderer only supports shard documents")
    if not inputs.render_qr:
        raise ValueError("direct Forge shard renderer requires QR rendering")
    if not inputs.render_fallback:
        raise ValueError("direct Forge shard renderer requires fallback rendering")
    if len(inputs.frames) != 1:
        raise ValueError("direct Forge shard renderer requires exactly one frame")
    if not inputs.fallback_sections:
        raise ValueError("fallback_sections are required for direct Forge shard rendering")

    paper_size = str(inputs.context.get("paper_size") or "A4").strip().lower()
    if paper_size != "a4":
        raise ValueError("direct Forge shard renderer currently supports A4 paper only")

    qr_config = inputs.qr_config or QrConfig()
    qr_kind = str(qr_config.kind or "png").strip().lower()
    if qr_kind != "png":
        raise ValueError("direct Forge shard renderer currently supports PNG QR images only")


def _resolved_qr_payload(inputs: RenderInputs) -> bytes | str:
    if inputs.qr_payloads is not None:
        payloads = tuple(inputs.qr_payloads)
    else:
        payloads = (encode_frame(inputs.frames[0]),)
    if len(payloads) != 1:
        raise ValueError("direct Forge shard renderer requires exactly one QR payload")
    return payloads[0]


def _qr_image(payload: bytes | str, *, config: QrConfig) -> bytes:
    return qr_bytes(
        payload,
        error=config.error,
        scale=config.scale,
        border=config.border,
        kind="png",
        dark=config.dark,
        light=config.light,
        version=config.version,
        mask=config.mask,
        micro=config.micro,
        boost_error=config.boost_error,
    )


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


def _paginate_fallback_entries(entries: Sequence[_FallbackEntry]) -> tuple[_FallbackPage, ...]:
    if not entries:
        raise ValueError("direct Forge shard renderer has no fallback entries to render")

    pages: list[_FallbackPage] = []
    remaining = tuple(entries)
    page_number = 1
    while remaining:
        area = _fallback_area_for_page(page_number)
        capacity = _fallback_capacity(area)
        page_entries, consumed = _consume_page_entries(remaining, capacity=capacity)
        if consumed <= 0:
            raise ValueError("fallback layout cannot fit even one entry on a page")
        pages.append(_FallbackPage(page_number=page_number, area=area, entries=page_entries))
        remaining = remaining[consumed:]
        page_number += 1
    return tuple(pages)


def _fallback_area_for_page(page_number: int) -> PdfRect:
    if page_number <= 1:
        return _FIRST_PAGE_FALLBACK_AREA
    return _CONTINUATION_FALLBACK_AREA


def _fallback_capacity(area: PdfRect) -> int:
    capacity = math.floor(max(0.0, area.height_mm - 7.0) / _FALLBACK_ROW_HEIGHT_MM)
    if capacity <= 0:
        raise ValueError("fallback area must fit at least one row")
    return capacity


def _consume_page_entries(
    entries: Sequence[_FallbackEntry],
    *,
    capacity: int,
) -> tuple[tuple[_FallbackPageEntry, ...], int]:
    placed: list[_FallbackPageEntry] = []
    consumed = 0
    for row_index, entry in enumerate(entries[:capacity]):
        placed.append(_FallbackPageEntry(entry=entry, row_index=row_index))
        consumed += 1
    return tuple(placed), consumed


def _build_page(
    surface: PdfSurface,
    context: ForgeShellContext,
    fallback_page: _FallbackPage,
    *,
    qr_image: bytes,
    total_pages: int,
) -> DirectPdfPagePlan:
    page_label = f"PAGE {fallback_page.page_number} / {total_pages}"
    plans: list[PaintPlan] = []
    plans.extend(
        build_forge_header_plans(
            surface,
            context,
            page_label=page_label,
            page_number=fallback_page.page_number,
            component_base=_COMPONENT_BASE,
            classification_default=_classification_default(context),
        )
    )
    if fallback_page.page_number == 1:
        plans.extend(_warning_plans(surface, context))
        plans.extend(_shard_stats_plans(surface, context))
        plans.extend(_primary_qr_plans(surface, qr_image=qr_image))
        plans.extend(_signature_plans(surface))
    else:
        plans.extend(_continuation_plans(surface, context, page_number=fallback_page.page_number))
        plans.extend(
            _continuation_qr_plans(
                surface,
                qr_image=qr_image,
                page_number=fallback_page.page_number,
            )
        )
    plans.extend(_fallback_plans(surface, fallback_page, context=context))
    if fallback_page.page_number > 1:
        plans.extend(
            build_forge_footer_plans(
                surface,
                context,
                page_label=page_label,
                page_number=fallback_page.page_number,
                component_base=_COMPONENT_BASE,
            )
        )
    return build_page_plan(page_number=fallback_page.page_number, rect=FORGE_PAGE_RECT, plans=plans)


def _classification_default(context: ForgeShellContext) -> str:
    if context.copy.get("key_material_label"):
        return "Restricted Access"
    return "Confidential"


def _warning_plans(surface: PdfSurface, context: ForgeShellContext) -> list[PaintPlan]:
    prefix = forge_component_prefix(_COMPONENT_BASE, 1)
    return [
        Panel(
            component_id=f"{prefix}-warning-panel",
            stroke=FORGE_SLATE_900,
            fill=FORGE_SLATE_100,
            line_width_mm=0.5,
        ).plan(surface, PdfRect(FORGE_CONTENT_X_MM, 65.0, FORGE_CONTENT_WIDTH_MM, 34.0)),
        Panel(
            component_id=f"{prefix}-warning-icon-box",
            fill=FORGE_SLATE_900,
            line_width_mm=0.2,
        ).plan(surface, PdfRect(20.0, 69.7, 11.0, 11.0)),
        TextBox(
            component_id=f"{prefix}-warning-icon",
            text=_ICON_WARNING,
            style=FORGE_THEME.symbol_style(size_pt=12.0, color=FORGE_WHITE),
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.CENTER,
            min_size_pt=8.0,
        ).plan(surface, PdfRect(20.0, 70.7, 11.0, 9.0)),
        TextBox(
            component_id=f"{prefix}-warning-title",
            text=str(context.copy.get("warning_title") or "Critical Security Notice").upper(),
            style=FORGE_THEME.sans_style(size_pt=13.5, bold=True, color=FORGE_SLATE_900),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=7.0,
        ).plan(surface, PdfRect(37.0, 70.7, 130.0, 7.0)),
        TextBox(
            component_id=f"{prefix}-warning-body",
            text=str(context.copy.get("warning_body") or ""),
            style=FORGE_THEME.sans_style(size_pt=10.5, color=FORGE_SLATE_800),
            policy=TextFitPolicy.WRAP,
        ).plan(surface, PdfRect(37.0, 79.8, 146.0, 15.8)),
    ]


def _shard_stats_plans(surface: PdfSurface, context: ForgeShellContext) -> list[PaintPlan]:
    shard_total = str(context.values.get("shard_total") or "")
    return [
        TextBox(
            component_id="forge-shard-p1-total-label",
            text="TOTAL SHARDS",
            style=FORGE_THEME.sans_style(size_pt=9.0, bold=True, color=FORGE_SLATE_800),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(18.0, 108.0, 45.0, 5.0)),
        TextBox(
            component_id="forge-shard-p1-total-value",
            text=shard_total,
            style=FORGE_THEME.mono_style(size_pt=15.0, bold=True, color=FORGE_SLATE_900),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=8.0,
        ).plan(surface, PdfRect(18.0, 113.2, 45.0, 8.5)),
        TextBox(
            component_id="forge-shard-p1-generated-label",
            text="GENERATED",
            style=FORGE_THEME.sans_style(size_pt=9.0, bold=True, color=FORGE_SLATE_800),
            policy=TextFitPolicy.FAIL,
            align=TextAlign.RIGHT,
        ).plan(surface, PdfRect(115.0, 108.0, 75.0, 5.0)),
        TextBox(
            component_id="forge-shard-p1-generated-value",
            text=context.created_timestamp_utc,
            style=FORGE_THEME.mono_style(size_pt=15.0, bold=True, color=FORGE_SLATE_900),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
            align=TextAlign.RIGHT,
        ).plan(surface, PdfRect(94.0, 113.2, 96.0, 8.5)),
        Rule(
            component_id="forge-shard-p1-stats-rule",
            color=FORGE_SLATE_900,
        ).plan(surface, PdfRect(15.0, 124.0, 180.0, 0.35)),
    ]


def _primary_qr_plans(surface: PdfSurface, *, qr_image: bytes) -> list[PaintPlan]:
    frame_rect = PdfRect(64.0, 138.0, _QR_FRAME_SIZE_MM, _QR_FRAME_SIZE_MM)
    image_rect = PdfRect(
        frame_rect.x_mm + (_QR_FRAME_SIZE_MM - _QR_IMAGE_SIZE_MM) / 2.0,
        frame_rect.y_mm + (_QR_FRAME_SIZE_MM - _QR_IMAGE_SIZE_MM) / 2.0,
        _QR_IMAGE_SIZE_MM,
        _QR_IMAGE_SIZE_MM,
    )
    return [
        Panel(
            component_id="forge-shard-p1-qr-frame",
            stroke=FORGE_SLATE_900,
            fill=FORGE_WHITE,
            line_width_mm=0.9,
        ).plan(surface, frame_rect),
        ImageBox(
            component_id="forge-shard-p1-qr-image",
            image=qr_image,
            image_type="PNG",
        ).plan(surface, image_rect),
    ]


def _signature_plans(surface: PdfSurface) -> list[PaintPlan]:
    plans = _signature_dash_plans(surface)
    plans.extend(
        [
            Rule(
                component_id="forge-shard-p1-validator-line",
                color=FORGE_SLATE_900,
            ).plan(surface, PdfRect(15.0, 293.0, 80.0, 0.35)),
            Rule(
                component_id="forge-shard-p1-date-line",
                color=FORGE_SLATE_900,
            ).plan(surface, PdfRect(142.0, 293.0, 53.0, 0.35)),
            TextBox(
                component_id="forge-shard-p1-date-placeholder",
                text="____ / ____ / ________",
                style=FORGE_THEME.mono_style(size_pt=7.2, color=FORGE_SLATE_900),
                policy=TextFitPolicy.FAIL,
                align=TextAlign.RIGHT,
            ).plan(surface, PdfRect(125.0, 289.0, 70.0, 4.0)),
            TextBox(
                component_id="forge-shard-p1-validator-label",
                text="VALIDATOR SIGNATURE",
                style=FORGE_THEME.sans_style(size_pt=5.6, bold=True, color=FORGE_SLATE_900),
                policy=TextFitPolicy.FAIL,
            ).plan(surface, PdfRect(15.0, 294.2, 70.0, 2.6)),
            TextBox(
                component_id="forge-shard-p1-date-label",
                text="DATE VERIFIED",
                style=FORGE_THEME.sans_style(size_pt=5.6, bold=True, color=FORGE_SLATE_900),
                policy=TextFitPolicy.FAIL,
                align=TextAlign.RIGHT,
            ).plan(surface, PdfRect(130.0, 294.2, 65.0, 2.6)),
        ]
    )
    return plans


def _signature_dash_plans(surface: PdfSurface) -> list[PaintPlan]:
    plans: list[PaintPlan] = []
    x = 15.0
    index = 0
    while x < 195.0:
        width = min(1.6, 195.0 - x)
        plans.append(
            Rule(
                component_id=f"forge-shard-p1-signature-dash-{index}",
                color=FORGE_SLATE_900,
            ).plan(surface, PdfRect(x, 276.0, width, 0.35))
        )
        x += 3.0
        index += 1
    return plans


def _continuation_plans(
    surface: PdfSurface,
    context: ForgeShellContext,
    *,
    page_number: int,
) -> list[PaintPlan]:
    prefix = forge_component_prefix(_COMPONENT_BASE, page_number)
    return [
        Panel(
            component_id=f"{prefix}-continuation-panel",
            stroke=FORGE_SLATE_200,
            fill=FORGE_SLATE_50,
            line_width_mm=0.18,
        ).plan(surface, PdfRect(15.0, 70.0, 180.0, 42.0)),
        TextBox(
            component_id=f"{prefix}-continuation-title",
            text="MANUAL TRANSCRIPTION CONTINUATION",
            style=TextStyle(family="Helvetica", size_pt=9.0, style="B", color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(62.0, 78.0, 118.0, 7.0)),
        TextBox(
            component_id=f"{prefix}-continuation-body",
            text=str(context.copy.get("footer_guidance") or ""),
            style=TextStyle(family="Helvetica", size_pt=7.0, color=FORGE_SLATE_700),
            policy=TextFitPolicy.WRAP,
        ).plan(surface, PdfRect(62.0, 88.0, 118.0, 13.0)),
    ]


def _continuation_qr_plans(
    surface: PdfSurface,
    *,
    qr_image: bytes,
    page_number: int,
) -> list[PaintPlan]:
    prefix = forge_component_prefix(_COMPONENT_BASE, page_number)
    return [
        Panel(
            component_id=f"{prefix}-qr-thumb-frame",
            stroke=FORGE_SLATE_900,
            fill=FORGE_WHITE,
            line_width_mm=0.35,
        ).plan(surface, PdfRect(22.0, 73.0, 42.0, 36.0)),
        ImageBox(
            component_id=f"{prefix}-qr-thumb-image",
            image=qr_image,
            image_type="PNG",
        ).plan(
            surface,
            PdfRect(25.0, 73.0, _CONTINUATION_QR_IMAGE_SIZE_MM, _CONTINUATION_QR_IMAGE_SIZE_MM),
        ),
    ]


def _fallback_plans(
    surface: PdfSurface,
    fallback_page: _FallbackPage,
    *,
    context: ForgeShellContext,
) -> list[PaintPlan]:
    prefix = forge_component_prefix(_COMPONENT_BASE, fallback_page.page_number)
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-fallback-panel",
            stroke=FORGE_SLATE_300,
            fill=FORGE_SLATE_50,
            line_width_mm=0.2,
        ).plan(surface, fallback_page.area),
        TextBox(
            component_id=f"{prefix}-fallback-label",
            text=str(
                context.copy.get("manual_transcription_label") or "Manual Transcription"
            ).upper(),
            style=TextStyle(family="Helvetica", size_pt=5.8, style="B", color=FORGE_SLATE_600),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=4.6,
        ).plan(
            surface,
            PdfRect(
                fallback_page.area.x_mm + 3.0,
                fallback_page.area.y_mm + 1.5,
                fallback_page.area.width_mm - 6.0,
                4.5,
            ),
        ),
    ]
    line_start_y = fallback_page.area.y_mm + 7.0
    for index, page_entry in enumerate(fallback_page.entries):
        row_y = line_start_y + page_entry.row_index * _FALLBACK_ROW_HEIGHT_MM
        if isinstance(page_entry.entry, _FallbackTitleEntry):
            plans.append(
                TextBox(
                    component_id=f"{prefix}-fallback-title-{index}",
                    text=page_entry.entry.title.upper(),
                    style=TextStyle(
                        family="Helvetica",
                        size_pt=5.5,
                        style="B",
                        color=FORGE_SLATE_500,
                    ),
                    policy=TextFitPolicy.FAIL,
                ).plan(
                    surface,
                    PdfRect(
                        fallback_page.area.x_mm + 4.0,
                        row_y,
                        fallback_page.area.width_mm - 8.0,
                        3.9,
                    ),
                )
            )
            continue
        plans.append(
            TextBox(
                component_id=f"{prefix}-fallback-line-{index}",
                text=page_entry.entry.text,
                style=TextStyle(family="Courier", size_pt=6.2, color=FORGE_SLATE_900),
                policy=TextFitPolicy.SHRINK,
                min_size_pt=5.1,
            ).plan(
                surface,
                PdfRect(
                    fallback_page.area.x_mm + 4.0,
                    row_y,
                    fallback_page.area.width_mm - 8.0,
                    3.9,
                ),
            )
        )
    return plans


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


__all__ = [
    "ForgeShardDirectPlan",
    "build_forge_shard_direct_plan",
    "render_forge_shard_direct_pdf",
]
