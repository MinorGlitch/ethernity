"""Sentinel signing-key shard rendering through direct PDF primitives."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from ethernity.encoding.framing import encode_frame
from ethernity.encoding.zbase32 import encode_zbase32
from ethernity.qr.codec import QrConfig, qr_bytes
from ethernity.render.direct_pdf.assets import packaged_direct_pdf_assets
from ethernity.render.direct_pdf.components import ImageBox, Line, Panel, Rule, TextAlign, TextBox
from ethernity.render.direct_pdf.debug import write_direct_layout_debug_json
from ethernity.render.direct_pdf.layout_proof import build_direct_layout_proof
from ethernity.render.direct_pdf.page import DirectPdfPagePlan, PaintPlan, build_page_plan
from ethernity.render.direct_pdf.sentinel_common import (
    SENTINEL_BACKGROUND,
    SENTINEL_BLACK,
    SENTINEL_BORDER,
    SENTINEL_GRID_LINE,
    SENTINEL_PAGE_RECT,
    SENTINEL_TEXT,
    SENTINEL_WHITE,
    SentinelShellContext,
    build_sentinel_corner_mark_plans,
    build_sentinel_footer_plans,
    build_sentinel_header_plans,
    build_sentinel_shell_context,
    build_sentinel_surface,
    sentinel_component_prefix,
)
from ethernity.render.direct_pdf.sentinel_theme import SENTINEL_THEME
from ethernity.render.direct_pdf.surface import PdfSurface
from ethernity.render.direct_pdf.text_fit import TextFitPolicy
from ethernity.render.direct_pdf.types import PdfColor, PdfRect
from ethernity.render.doc_types import DOC_TYPE_SIGNING_KEY_SHARD
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

_COMPONENT_BASE = "sentinel-signing-key-shard"
_FALLBACK_GROUP_SIZE = 4
_FALLBACK_LINE_LENGTH = 76
_FALLBACK_ROW_HEIGHT_MM = 5.1
_FALLBACK_AREA = PdfRect(80.0, 95.5, 119.0, 42.0)
_QR_FRAME_RECT = PdfRect(11.0, 96.0, 62.5, 62.5)
_QR_IMAGE_RECT = PdfRect(14.2, 99.1, 56.0, 56.0)
_WARNING_RECT = PdfRect(11.0, 36.5, 188.0, 41.5)
_DASH_LENGTH_MM = 2.0
_DASH_GAP_MM = 1.6
_ICON_WARNING = chr(0xE002)
_ICON_GROUP_WORK = chr(0xE886)
_ICON_FINGERPRINT = chr(0xE90D)


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
    row_index: int


@dataclass(frozen=True)
class _FallbackPage:
    page_number: int
    entries: tuple[_FallbackPageEntry, ...]


def render_sentinel_signing_key_shard_direct_pdf(inputs: RenderInputs) -> RenderResult:
    """Render a Sentinel signing-key shard document directly to PDF."""

    surface = build_sentinel_surface()
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
    qr_image = _qr_image(payload, config=inputs.qr_config or QrConfig())
    context = build_sentinel_shell_context(inputs, doc_type=DOC_TYPE_SIGNING_KEY_SHARD)
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
    if len(inputs.frames) != 1:
        raise ValueError("direct Sentinel signing-key shard renderer requires exactly one frame")
    if not inputs.fallback_sections:
        raise ValueError("fallback_sections are required for direct Sentinel signing-key shards")

    paper_size = str(inputs.context.get("paper_size") or "A4").strip().lower()
    if paper_size != "a4":
        raise ValueError("direct Sentinel signing-key shard renderer currently supports A4 only")

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
        raise ValueError("direct Sentinel signing-key shard renderer has no fallback entries")

    pages: list[_FallbackPage] = []
    remaining = tuple(entries)
    page_number = 1
    capacity = _fallback_capacity()
    while remaining:
        page_entries, consumed = _consume_page_entries(remaining, capacity=capacity)
        if consumed <= 0:
            raise ValueError("fallback layout cannot fit even one entry on a page")
        pages.append(_FallbackPage(page_number=page_number, entries=page_entries))
        remaining = remaining[consumed:]
        page_number += 1
    return tuple(pages)


def _fallback_capacity() -> int:
    capacity = math.floor(max(0.0, _FALLBACK_AREA.height_mm - 10.0) / _FALLBACK_ROW_HEIGHT_MM)
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
    prefix = sentinel_component_prefix(_COMPONENT_BASE, fallback_page.page_number)
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
    plans.extend(_fallback_plans(surface, context, fallback_page=fallback_page, prefix=prefix))
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
    return build_page_plan(
        page_number=fallback_page.page_number,
        rect=SENTINEL_PAGE_RECT,
        plans=plans,
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
        ).plan(surface, PdfRect(12.5, 162.0, 59.5, 5.0))
    )
    return plans


def _fallback_plans(
    surface: PdfSurface,
    context: SentinelShellContext,
    *,
    fallback_page: _FallbackPage,
    prefix: str,
) -> list[PaintPlan]:
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-payload-panel",
            stroke=SENTINEL_GRID_LINE,
            fill=SENTINEL_BACKGROUND,
            line_width_mm=0.2,
        ).plan(surface, _FALLBACK_AREA),
    ]
    line_start_y = _FALLBACK_AREA.y_mm + 7.0
    for index, page_entry in enumerate(fallback_page.entries):
        row_y = line_start_y + page_entry.row_index * _FALLBACK_ROW_HEIGHT_MM
        if isinstance(page_entry.entry, _FallbackTitleEntry):
            plans.append(
                TextBox(
                    component_id=f"{prefix}-fallback-title-{index}",
                    text=page_entry.entry.title.upper(),
                    style=SENTINEL_THEME.mono_style(
                        size_pt=7.4,
                        bold=True,
                        color=SENTINEL_TEXT,
                        char_spacing_mm=0.22,
                    ),
                    policy=TextFitPolicy.SHRINK,
                    min_size_pt=5.5,
                ).plan(
                    surface,
                    PdfRect(_FALLBACK_AREA.x_mm + 4.5, row_y, _FALLBACK_AREA.width_mm - 9.0, 4.0),
                )
            )
            continue
        plans.append(
            TextBox(
                component_id=f"{prefix}-fallback-line-{index}",
                text=page_entry.entry.text,
                style=SENTINEL_THEME.mono_style(size_pt=7.0, color=SENTINEL_BLACK),
                policy=TextFitPolicy.SHRINK,
                min_size_pt=5.2,
            ).plan(
                surface,
                PdfRect(_FALLBACK_AREA.x_mm + 4.5, row_y, _FALLBACK_AREA.width_mm - 9.0, 4.0),
            )
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
                    _FALLBACK_AREA.x_mm + 4.5,
                    _FALLBACK_AREA.y_mm + 7.0,
                    _FALLBACK_AREA.width_mm - 9.0,
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
    left_rect = PdfRect(11.0, 251.0, 91.0, 24.0)
    right_rect = PdfRect(108.5, 251.0, 90.5, 24.0)
    return [
        Panel(
            component_id=f"{prefix}-reference-panel",
            stroke=SENTINEL_BORDER,
            fill=PdfColor(250, 248, 244),
            line_width_mm=0.2,
        ).plan(surface, left_rect),
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
        ).plan(surface, PdfRect(left_rect.x_mm + 3.5, left_rect.y_mm + 4.2, 80.0, 4.5)),
        TextBox(
            component_id=f"{prefix}-reference-doc-id",
            text=context.doc_id,
            style=SENTINEL_THEME.mono_style(size_pt=8.0, bold=True, color=SENTINEL_BLACK),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(left_rect.x_mm + 3.5, left_rect.y_mm + 10.5, 80.0, 4.5)),
        TextBox(
            component_id=f"{prefix}-reference-help",
            text="Use this value to verify shard set integrity.",
            style=SENTINEL_THEME.sans_style(size_pt=7.0, color=SENTINEL_TEXT),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=5.0,
        ).plan(surface, PdfRect(left_rect.x_mm + 3.5, left_rect.y_mm + 17.0, 80.0, 4.0)),
        Panel(
            component_id=f"{prefix}-specs-panel",
            stroke=SENTINEL_BORDER,
            fill=PdfColor(250, 248, 244),
            line_width_mm=0.2,
        ).plan(surface, right_rect),
        *_spec_row_plans(
            surface,
            prefix=prefix,
            row_index=0,
            label="SCHEMA",
            value="Signing Key Shard",
            y_mm=right_rect.y_mm + 4.0,
        ),
        *_spec_row_plans(
            surface,
            prefix=prefix,
            row_index=1,
            label="GENERATED",
            value=context.created_timestamp_utc,
            y_mm=right_rect.y_mm + 10.5,
        ),
        *_spec_row_plans(
            surface,
            prefix=prefix,
            row_index=2,
            label="PAGE",
            value=page_label,
            y_mm=right_rect.y_mm + 17.0,
        ),
    ]


def _spec_row_plans(
    surface: PdfSurface,
    *,
    prefix: str,
    row_index: int,
    label: str,
    value: str,
    y_mm: float,
) -> list[PaintPlan]:
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
        ).plan(surface, PdfRect(112.0, y_mm, 36.0, 4.5)),
        TextBox(
            component_id=f"{prefix}-spec-value-{row_index}",
            text=value,
            style=SENTINEL_THEME.mono_style(size_pt=8.5, color=SENTINEL_TEXT),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(154.0, y_mm, 39.5, 4.5)),
    ]
    if row_index < 2:
        plans.append(
            Rule(
                component_id=f"{prefix}-spec-rule-{row_index}",
                color=SENTINEL_BORDER,
            ).plan(surface, PdfRect(112.0, y_mm + 5.0, 82.5, 0.18))
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
