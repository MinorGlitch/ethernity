"""Forge signing-key shard rendering through direct PDF primitives."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from ethernity.core.bounds import MAX_FALLBACK_LINES
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
    FORGE_SLATE_700,
    FORGE_SLATE_800,
    FORGE_SLATE_900,
    FORGE_WHITE,
    ForgeShellContext,
    build_forge_footer_plans,
    build_forge_header_plans,
    build_forge_shell_context,
    explicit_creation_date,
    forge_component_prefix,
)
from ethernity.render.direct_pdf.forge_preview import A4_HEIGHT_MM, A4_WIDTH_MM
from ethernity.render.direct_pdf.forge_theme import FORGE_THEME
from ethernity.render.direct_pdf.layout_proof import build_direct_layout_proof
from ethernity.render.direct_pdf.page import DirectPdfPagePlan, PaintPlan, build_page_plan
from ethernity.render.direct_pdf.surface import FpdfSurface, PdfSurface
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

_COMPONENT_BASE = "forge-signing-key-shard"
_FALLBACK_GROUP_SIZE = 4
_FALLBACK_LINE_LENGTH = 64
_FALLBACK_ROW_HEIGHT_MM = 4.2
_PAYLOAD_TEXT_AREA = PdfRect(72.0, 136.5, 116.0, 31.0)
_QR_IMAGE_SIZE_MM = 39.5
_ICON_SHIELD_LOCK = chr(0xF686)
_ICON_VPN_KEY = chr(0xE0DA)
_ICON_VISIBILITY = chr(0xE8F4)
_ICON_SETTINGS_ETHERNET = chr(0xE8BE)
_FORGE_SLATE_400 = PdfColor(148, 163, 184)
_FORGE_BLUE = PdfColor(25, 118, 210)


@dataclass(frozen=True)
class ForgeSigningKeyShardDirectPlan:
    """Measured pages and proofs for one direct Forge signing-key shard render."""

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


def render_forge_signing_key_shard_direct_pdf(inputs: RenderInputs) -> RenderResult:
    """Render a Forge signing-key shard document directly to PDF."""

    surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
    creation_date = explicit_creation_date(inputs)
    if creation_date is not None:
        surface.set_creation_date(creation_date)
    packaged_direct_pdf_assets().register_fonts(surface)
    plan = build_forge_signing_key_shard_direct_plan(surface, inputs)
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


def build_forge_signing_key_shard_direct_plan(
    surface: PdfSurface,
    inputs: RenderInputs,
) -> ForgeSigningKeyShardDirectPlan:
    """Build measured direct-PDF plans and proofs for Forge signing-key shard inputs."""

    _validate_inputs(inputs)
    payload = _resolved_qr_payload(inputs)
    qr_image = _qr_image(payload, config=inputs.qr_config or QrConfig())
    context = build_forge_shell_context(inputs, doc_type=DOC_TYPE_SIGNING_KEY_SHARD)
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
    return ForgeSigningKeyShardDirectPlan(
        page_plans=page_plans,
        fallback_proof=fallback_proof,
        artifact_proof=artifact_proof,
    )


def _validate_inputs(inputs: RenderInputs) -> None:
    normalized_doc_type = inputs.doc_type.strip().lower()
    if normalized_doc_type != DOC_TYPE_SIGNING_KEY_SHARD:
        raise ValueError("direct Forge signing-key shard renderer only supports signing-key shards")
    if not inputs.render_qr:
        raise ValueError("direct Forge signing-key shard renderer requires QR rendering")
    if not inputs.render_fallback:
        raise ValueError("direct Forge signing-key shard renderer requires fallback rendering")
    if len(inputs.frames) != 1:
        raise ValueError("direct Forge signing-key shard renderer requires exactly one frame")
    if not inputs.fallback_sections:
        raise ValueError("fallback_sections are required for direct Forge signing-key shards")

    paper_size = str(inputs.context.get("paper_size") or "A4").strip().lower()
    if paper_size != "a4":
        raise ValueError("direct Forge signing-key shard renderer currently supports A4 only")

    qr_config = inputs.qr_config or QrConfig()
    qr_kind = str(qr_config.kind or "png").strip().lower()
    if qr_kind != "png":
        raise ValueError("direct Forge signing-key shard renderer supports PNG QR images only")


def _resolved_qr_payload(inputs: RenderInputs) -> bytes | str:
    if inputs.qr_payloads is not None:
        payloads = tuple(inputs.qr_payloads)
    else:
        payloads = (encode_frame(inputs.frames[0]),)
    if len(payloads) != 1:
        raise ValueError("direct Forge signing-key shard renderer requires exactly one QR payload")
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


def _paginate_fallback_entries(entries: Sequence[_FallbackEntry]) -> tuple[_FallbackPage, ...]:
    if not entries:
        raise ValueError("direct Forge signing-key shard renderer has no fallback entries")

    pages: list[_FallbackPage] = []
    remaining = tuple(entries)
    page_number = 1
    capacity = _fallback_capacity()
    while remaining:
        placed = tuple(
            _FallbackPageEntry(entry=entry, row_index=row_index)
            for row_index, entry in enumerate(remaining[:capacity])
        )
        if not placed:
            raise ValueError("fallback layout cannot fit even one entry on a page")
        pages.append(_FallbackPage(page_number=page_number, entries=placed))
        remaining = remaining[len(placed) :]
        page_number += 1
    return tuple(pages)


def _fallback_capacity() -> int:
    capacity = math.floor(_PAYLOAD_TEXT_AREA.height_mm / _FALLBACK_ROW_HEIGHT_MM)
    if capacity <= 0:
        raise ValueError("fallback payload area must fit at least one row")
    return capacity


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
            classification_default="Restricted Access",
            kicker_text="",
            icon_text="",
        )
    )
    plans.extend(_warning_plans(surface, context, fallback_page.page_number))
    plans.extend(_key_material_plans(surface, context, fallback_page, qr_image=qr_image))
    plans.extend(_reference_and_specs_plans(surface, context, fallback_page.page_number))
    plans.extend(_intact_notice_plans(surface, fallback_page.page_number))
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


def _warning_plans(
    surface: PdfSurface,
    context: ForgeShellContext,
    page_number: int,
) -> list[PaintPlan]:
    prefix = forge_component_prefix(_COMPONENT_BASE, page_number)
    rect = PdfRect(FORGE_CONTENT_X_MM, 63.5, FORGE_CONTENT_WIDTH_MM, 43.2)
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-warning-panel-bg",
            stroke=FORGE_SLATE_300,
            fill=FORGE_SLATE_50,
            line_width_mm=0.2,
        ).plan(surface, rect),
    ]
    plans.extend(_dashed_border_plans(surface, f"{prefix}-warning-dash", rect, _FORGE_SLATE_400))
    plans.extend(
        [
            TextBox(
                component_id=f"{prefix}-warning-icon",
                text=_ICON_SHIELD_LOCK,
                style=FORGE_THEME.symbol_style(size_pt=16.0, color=_FORGE_BLUE),
                policy=TextFitPolicy.FAIL,
            ).plan(surface, PdfRect(20.0, 70.5, 8.0, 7.0)),
            TextBox(
                component_id=f"{prefix}-warning-title",
                text=str(context.copy.get("warning_title") or "Critical Security Notice").upper(),
                style=FORGE_THEME.sans_style(size_pt=11.0, bold=True, color=FORGE_SLATE_900),
                policy=TextFitPolicy.FAIL,
            ).plan(surface, PdfRect(29.5, 68.3, 150.0, 5.5)),
            TextBox(
                component_id=f"{prefix}-warning-body",
                text=str(context.copy.get("warning_body") or ""),
                style=FORGE_THEME.sans_style(size_pt=10.2, color=FORGE_SLATE_800),
                policy=TextFitPolicy.WRAP,
                line_height_multiplier=1.38,
            ).plan(surface, PdfRect(29.5, 76.2, 156.0, 15.8)),
            TextBox(
                component_id=f"{prefix}-warning-instructions",
                text="\n".join(context.instruction_lines),
                style=FORGE_THEME.sans_style(size_pt=8.6, color=FORGE_SLATE_700),
                policy=TextFitPolicy.WRAP,
                line_height_multiplier=1.34,
            ).plan(surface, PdfRect(29.5, 92.0, 135.0, 13.0)),
        ]
    )
    return plans


def _key_material_plans(
    surface: PdfSurface,
    context: ForgeShellContext,
    fallback_page: _FallbackPage,
    *,
    qr_image: bytes,
) -> list[PaintPlan]:
    prefix = forge_component_prefix(_COMPONENT_BASE, fallback_page.page_number)
    panel_rect = PdfRect(FORGE_CONTENT_X_MM, 124.8, FORGE_CONTENT_WIDTH_MM, 61.0)
    plans: list[PaintPlan] = [
        TextBox(
            component_id=f"{prefix}-key-section-icon",
            text=_ICON_VPN_KEY,
            style=FORGE_THEME.symbol_style(size_pt=15.0, color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(15.0, 114.0, 8.0, 7.0)),
        TextBox(
            component_id=f"{prefix}-key-section-title",
            text=(
                f"01. {str(context.copy.get('key_material_label') or 'Key Material Payload')}"
            ).upper(),
            style=FORGE_THEME.sans_style(size_pt=14.0, bold=True, color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(24.0, 113.4, 90.0, 7.5)),
        TextBox(
            component_id=f"{prefix}-key-section-zone",
            text="ZONE A // SENSITIVE",
            style=FORGE_THEME.mono_style(size_pt=7.7, color=FORGE_SLATE_700),
            policy=TextFitPolicy.FAIL,
            align=TextAlign.RIGHT,
        ).plan(surface, PdfRect(148.0, 115.2, 47.0, 4.6)),
        Rule(
            component_id=f"{prefix}-key-section-rule",
            color=FORGE_SLATE_300,
        ).plan(surface, PdfRect(FORGE_CONTENT_X_MM, 122.3, FORGE_CONTENT_WIDTH_MM, 0.35)),
        Panel(
            component_id=f"{prefix}-payload-panel",
            stroke=FORGE_SLATE_900,
            fill=FORGE_WHITE,
            line_width_mm=0.5,
        ).plan(surface, panel_rect),
    ]
    plans.extend(_blueprint_grid_plans(surface, prefix, panel_rect))
    plans.extend(_payload_corner_plans(surface, prefix, panel_rect))
    plans.extend(
        [
            Panel(
                component_id=f"{prefix}-qr-paper",
                stroke=FORGE_SLATE_200,
                fill=FORGE_WHITE,
                line_width_mm=0.2,
            ).plan(surface, PdfRect(21.5, 132.0, 44.5, 47.0)),
            ImageBox(
                component_id=f"{prefix}-qr-image",
                image=qr_image,
                image_type="png",
            ).plan(surface, PdfRect(24.0, 136.0, _QR_IMAGE_SIZE_MM, _QR_IMAGE_SIZE_MM)),
            TextBox(
                component_id=f"{prefix}-payload-static-label",
                text="SHARD PAYLOAD",
                style=FORGE_THEME.sans_style(size_pt=8.0, bold=True, color=FORGE_SLATE_800),
                policy=TextFitPolicy.FAIL,
            ).plan(surface, PdfRect(_PAYLOAD_TEXT_AREA.x_mm, 132.2, 50.0, 4.8)),
        ]
    )
    plans.extend(_payload_fallback_plans(surface, fallback_page))
    plans.extend(
        [
            Rule(
                component_id=f"{prefix}-payload-meta-rule",
                color=FORGE_SLATE_300,
            ).plan(
                surface,
                PdfRect(_PAYLOAD_TEXT_AREA.x_mm, 173.2, _PAYLOAD_TEXT_AREA.width_mm, 0.3),
            ),
            TextBox(
                component_id=f"{prefix}-payload-shard-meta",
                text=(
                    f"SHARD: {_context_int(context, 'shard_index')} / "
                    f"{_context_int(context, 'shard_total')}"
                ),
                style=FORGE_THEME.mono_style(size_pt=7.4, bold=True, color=FORGE_SLATE_900),
                policy=TextFitPolicy.FAIL,
            ).plan(surface, PdfRect(_PAYLOAD_TEXT_AREA.x_mm, 177.0, 50.0, 4.2)),
            TextBox(
                component_id=f"{prefix}-payload-encoding-meta",
                text="ENCODING: QR + TEXT",
                style=FORGE_THEME.mono_style(size_pt=7.4, bold=True, color=FORGE_SLATE_900),
                policy=TextFitPolicy.FAIL,
                align=TextAlign.RIGHT,
            ).plan(surface, PdfRect(142.0, 177.0, 46.0, 4.2)),
        ]
    )
    return plans


def _payload_fallback_plans(surface: PdfSurface, fallback_page: _FallbackPage) -> list[PaintPlan]:
    prefix = forge_component_prefix(_COMPONENT_BASE, fallback_page.page_number)
    plans: list[PaintPlan] = []
    for index, page_entry in enumerate(fallback_page.entries):
        y = _PAYLOAD_TEXT_AREA.y_mm + page_entry.row_index * _FALLBACK_ROW_HEIGHT_MM
        entry = page_entry.entry
        if isinstance(entry, _FallbackTitleEntry):
            plans.append(
                TextBox(
                    component_id=f"{prefix}-payload-title-{index}",
                    text=entry.title,
                    style=FORGE_THEME.sans_style(size_pt=8.0, bold=True, color=FORGE_SLATE_800),
                    policy=TextFitPolicy.FAIL,
                ).plan(
                    surface,
                    PdfRect(_PAYLOAD_TEXT_AREA.x_mm, y, _PAYLOAD_TEXT_AREA.width_mm, 4.0),
                )
            )
            continue
        plans.append(
            TextBox(
                component_id=f"{prefix}-payload-line-{index}",
                text=entry.text,
                style=FORGE_THEME.mono_style(size_pt=8.0, color=FORGE_SLATE_900),
                policy=TextFitPolicy.FAIL,
            ).plan(surface, PdfRect(_PAYLOAD_TEXT_AREA.x_mm, y, _PAYLOAD_TEXT_AREA.width_mm, 4.0))
        )
    return plans


def _reference_and_specs_plans(
    surface: PdfSurface,
    context: ForgeShellContext,
    page_number: int,
) -> list[PaintPlan]:
    prefix = forge_component_prefix(_COMPONENT_BASE, page_number)
    return [
        TextBox(
            component_id=f"{prefix}-reference-icon",
            text=_ICON_VISIBILITY,
            style=FORGE_THEME.symbol_style(size_pt=14.0, color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(15.0, 196.0, 8.0, 7.0)),
        TextBox(
            component_id=f"{prefix}-reference-title",
            text="02. PUBLIC REFERENCE",
            style=FORGE_THEME.sans_style(size_pt=11.4, bold=True, color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(24.0, 195.2, 75.0, 6.5)),
        TextBox(
            component_id=f"{prefix}-reference-zone",
            text="ZONE B // VERIFICATION",
            style=FORGE_THEME.mono_style(size_pt=6.8, color=FORGE_SLATE_700),
            policy=TextFitPolicy.FAIL,
            align=TextAlign.RIGHT,
        ).plan(surface, PdfRect(62.0, 199.5, 39.0, 4.0)),
        Rule(
            component_id=f"{prefix}-reference-rule",
            color=FORGE_SLATE_300,
        ).plan(surface, PdfRect(FORGE_CONTENT_X_MM, 204.4, 86.0, 0.3)),
        Panel(
            component_id=f"{prefix}-reference-panel",
            stroke=FORGE_SLATE_300,
            fill=FORGE_SLATE_50,
            line_width_mm=0.2,
        ).plan(surface, PdfRect(FORGE_CONTENT_X_MM, 207.0, 86.0, 25.5)),
        TextBox(
            component_id=f"{prefix}-fingerprint-label",
            text=str(context.copy.get("master_fingerprint_label") or "Master Fingerprint").upper(),
            style=FORGE_THEME.sans_style(size_pt=7.0, bold=True, color=FORGE_SLATE_800),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(19.0, 214.0, 50.0, 4.0)),
        TextBox(
            component_id=f"{prefix}-fingerprint-value",
            text=context.doc_id,
            style=FORGE_THEME.mono_style(size_pt=10.0, bold=True, color=FORGE_SLATE_900),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=7.5,
        ).plan(surface, PdfRect(19.0, 221.0, 70.0, 5.0)),
        TextBox(
            component_id=f"{prefix}-fingerprint-helper",
            text="Use this value to verify shard set integrity.",
            style=FORGE_THEME.sans_style(size_pt=7.0, color=FORGE_SLATE_700),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(19.0, 228.1, 75.0, 4.0)),
        TextBox(
            component_id=f"{prefix}-specs-icon",
            text=_ICON_SETTINGS_ETHERNET,
            style=FORGE_THEME.symbol_style(size_pt=14.0, color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(109.0, 196.0, 8.0, 7.0)),
        TextBox(
            component_id=f"{prefix}-specs-title",
            text="03. SPECIFICATIONS",
            style=FORGE_THEME.sans_style(size_pt=11.4, bold=True, color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(118.0, 195.2, 70.0, 6.5)),
        Rule(
            component_id=f"{prefix}-specs-rule",
            color=FORGE_SLATE_300,
        ).plan(surface, PdfRect(109.0, 204.4, 86.0, 0.3)),
        *_spec_table_plans(surface, context, prefix),
    ]


def _spec_table_plans(
    surface: PdfSurface,
    context: ForgeShellContext,
    prefix: str,
) -> list[PaintPlan]:
    rows = (
        ("SCHEMA", "Shamir Signing Key"),
        ("THRESHOLD", f"{_context_int(context, 'shard_total')} total"),
        ("DOCUMENT", str(context.copy.get("title") or "Signing Authority Shard")),
        ("VERSION", "Forge v2.1"),
    )
    x = 109.0
    y = 207.0
    label_w = 42.5
    value_w = 43.5
    row_heights = (8.6, 8.6, 12.4, 8.6)
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-specs-table",
            stroke=FORGE_SLATE_300,
            fill=FORGE_WHITE,
            line_width_mm=0.2,
        ).plan(surface, PdfRect(x, y, label_w + value_w, sum(row_heights))),
    ]
    current_y = y
    for row_index, ((label, value), row_height) in enumerate(zip(rows, row_heights, strict=True)):
        plans.extend(
            [
                Panel(
                    component_id=f"{prefix}-specs-label-bg-{row_index}",
                    stroke=None,
                    fill=FORGE_SLATE_50,
                    line_width_mm=0.2,
                ).plan(surface, PdfRect(x, current_y, label_w, row_height)),
                Rule(
                    component_id=f"{prefix}-specs-col-rule-{row_index}",
                    color=FORGE_SLATE_300,
                ).plan(surface, PdfRect(x + label_w, current_y, 0.3, row_height)),
                TextBox(
                    component_id=f"{prefix}-specs-label-{row_index}",
                    text=label,
                    style=FORGE_THEME.sans_style(size_pt=8.4, bold=True, color=FORGE_SLATE_800),
                    policy=TextFitPolicy.FAIL,
                ).plan(surface, PdfRect(x + 2.2, current_y + 2.7, label_w - 4.4, 4.0)),
                TextBox(
                    component_id=f"{prefix}-specs-value-{row_index}",
                    text=value,
                    style=FORGE_THEME.mono_style(
                        size_pt=8.4,
                        bold=row_index == 1,
                        color=FORGE_SLATE_900,
                    ),
                    policy=TextFitPolicy.WRAP,
                    line_height_multiplier=1.18,
                ).plan(surface, PdfRect(x + label_w + 2.2, current_y + 2.4, value_w - 4.4, 7.0)),
            ]
        )
        if row_index > 0:
            plans.append(
                Rule(
                    component_id=f"{prefix}-specs-row-rule-{row_index}",
                    color=FORGE_SLATE_300,
                ).plan(surface, PdfRect(x, current_y, label_w + value_w, 0.3))
            )
        current_y += row_height
    return plans


def _intact_notice_plans(surface: PdfSurface, page_number: int) -> list[PaintPlan]:
    prefix = forge_component_prefix(_COMPONENT_BASE, page_number)
    return [
        TextBox(
            component_id=f"{prefix}-intact-notice",
            text="Valid only if physically intact. Verify checksums before restoration.",
            style=FORGE_THEME.sans_style(size_pt=6.8, color=FORGE_SLATE_700),
            policy=TextFitPolicy.FAIL,
            align=TextAlign.CENTER,
        ).plan(surface, PdfRect(50.0, 252.4, 110.0, 4.0)),
    ]


def _blueprint_grid_plans(
    surface: PdfSurface,
    prefix: str,
    rect: PdfRect,
) -> list[PaintPlan]:
    plans: list[PaintPlan] = []
    step = 5.0
    x = rect.x_mm + step
    index = 0
    while x < rect.right_mm:
        plans.append(
            Rule(
                component_id=f"{prefix}-blueprint-grid-v-{index}",
                color=FORGE_SLATE_100,
            ).plan(surface, PdfRect(x, rect.y_mm, 0.25, rect.height_mm))
        )
        x += step
        index += 1
    y = rect.y_mm + step
    index = 0
    while y < rect.bottom_mm:
        plans.append(
            Rule(
                component_id=f"{prefix}-blueprint-grid-h-{index}",
                color=FORGE_SLATE_100,
            ).plan(surface, PdfRect(rect.x_mm, y, rect.width_mm, 0.25))
        )
        y += step
        index += 1
    return plans


def _payload_corner_plans(
    surface: PdfSurface,
    prefix: str,
    rect: PdfRect,
) -> list[PaintPlan]:
    size = 3.2
    return [
        Panel(
            component_id=f"{prefix}-payload-corner-tl",
            stroke=FORGE_SLATE_900,
            fill=FORGE_SLATE_900,
            line_width_mm=0.2,
        ).plan(surface, PdfRect(rect.x_mm, rect.y_mm, size, size)),
        Panel(
            component_id=f"{prefix}-payload-corner-tr",
            stroke=FORGE_SLATE_900,
            fill=FORGE_SLATE_900,
            line_width_mm=0.2,
        ).plan(surface, PdfRect(rect.right_mm - size, rect.y_mm, size, size)),
        Panel(
            component_id=f"{prefix}-payload-corner-bl",
            stroke=FORGE_SLATE_900,
            fill=FORGE_SLATE_900,
            line_width_mm=0.2,
        ).plan(surface, PdfRect(rect.x_mm, rect.bottom_mm - size, size, size)),
        Panel(
            component_id=f"{prefix}-payload-corner-br",
            stroke=FORGE_SLATE_900,
            fill=FORGE_SLATE_900,
            line_width_mm=0.2,
        ).plan(surface, PdfRect(rect.right_mm - size, rect.bottom_mm - size, size, size)),
    ]


def _dashed_border_plans(
    surface: PdfSurface,
    prefix: str,
    rect: PdfRect,
    color: PdfColor,
) -> list[PaintPlan]:
    plans: list[PaintPlan] = []
    dash = 1.8
    gap = 1.4
    thickness = 0.25

    x = rect.x_mm
    index = 0
    while x < rect.right_mm:
        width = min(dash, rect.right_mm - x)
        plans.append(
            Rule(
                component_id=f"{prefix}-top-{index}",
                color=color,
            ).plan(surface, PdfRect(x, rect.y_mm, width, thickness))
        )
        plans.append(
            Rule(
                component_id=f"{prefix}-bottom-{index}",
                color=color,
            ).plan(surface, PdfRect(x, rect.bottom_mm - thickness, width, thickness))
        )
        x += dash + gap
        index += 1

    y = rect.y_mm
    index = 0
    while y < rect.bottom_mm:
        height = min(dash, rect.bottom_mm - y)
        plans.append(
            Rule(
                component_id=f"{prefix}-left-{index}",
                color=color,
            ).plan(surface, PdfRect(rect.x_mm, y, thickness, height))
        )
        plans.append(
            Rule(
                component_id=f"{prefix}-right-{index}",
                color=color,
            ).plan(surface, PdfRect(rect.right_mm - thickness, y, thickness, height))
        )
        y += dash + gap
        index += 1
    return plans


def _context_int(context: ForgeShellContext, key: str) -> int:
    value = context.values.get(key)
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return 0
    return 0


def _build_fallback_proof(
    inputs: RenderInputs,
    sections: Sequence[_FallbackSectionLines],
    pages: Sequence[_FallbackPage],
) -> RenderFallbackProof:
    emitted_lines = tuple(
        entry.entry.text
        for page in pages
        for entry in page.entries
        if isinstance(entry.entry, _FallbackLineEntry)
    )
    return RenderFallbackProof(
        section_frame_digests=tuple(
            frame_digest(section.frame) for section in inputs.fallback_sections or ()
        ),
        section_titles=tuple(section.title for section in sections if section.title),
        expected_section_count=len(sections),
        consumed_section_count=len(sections),
        fully_consumed=True,
        emitted_fallback_lines=emitted_lines,
        emitted_block_count=len(sections),
        emitted_line_count=len(emitted_lines),
    )


__all__ = [
    "ForgeSigningKeyShardDirectPlan",
    "build_forge_signing_key_shard_direct_plan",
    "render_forge_signing_key_shard_direct_pdf",
]
