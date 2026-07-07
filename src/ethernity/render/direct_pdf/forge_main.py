"""Forge main document rendering through direct PDF primitives."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from ethernity.encoding.framing import encode_frame
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
from ethernity.render.direct_pdf.types import PdfRect
from ethernity.render.doc_types import DOC_TYPE_MAIN
from ethernity.render.proofs import build_render_artifact_proof
from ethernity.render.types import RenderArtifactProof, RenderInputs, RenderResult

_COMPONENT_BASE = "forge-main"
_QR_COLUMNS = 3
_QR_CARD_GAP_MM = 4.25
_QR_CARD_HEIGHT_MM = 65.0
_QR_IMAGE_SIZE_MM = 50.8
_FIRST_PAGE_QR_TOP_MM = 104.5
_CONTINUATION_QR_TOP_MM = 78.0
_FIRST_PAGE_QR_ROWS = 2
_CONTINUATION_QR_ROWS = 3
_DIRECTIVE_TITLE_TOP_MM = 51.0
_DIRECTIVE_TOP_MM = 62.0
_DIRECTIVE_CARD_GAP_MM = 4.25
_DIRECTIVE_CARD_HEIGHT_MM = 27.0
_DIRECTIVE_SECTION_RULE_Y_MM = 95.6
_DIRECTIVE_ICONS = (
    chr(0xE8F5),
    chr(0xE899),
    chr(0xE9B0),
    chr(0xE873),
)


@dataclass(frozen=True)
class ForgeMainDirectPlan:
    """Measured pages and app-wide proof for one direct Forge main render."""

    page_plans: tuple[DirectPdfPagePlan, ...]
    artifact_proof: RenderArtifactProof


@dataclass(frozen=True)
class _QrPayloadItem:
    payload_index: int
    payload: bytes | str
    image: bytes

    @property
    def label_index(self) -> int:
        return self.payload_index + 1


@dataclass(frozen=True)
class _QrPage:
    page_number: int
    items: tuple[_QrPayloadItem, ...]


def render_forge_main_direct_pdf(inputs: RenderInputs) -> RenderResult:
    """Render a Forge main document directly to PDF and return validation proofs."""

    surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
    packaged_direct_pdf_assets().register_fonts(surface)
    plan = build_forge_main_direct_plan(surface, inputs)
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
    return RenderResult(artifact_proof=plan.artifact_proof, layout_proof=layout_proof)


def build_forge_main_direct_plan(
    surface: PdfSurface,
    inputs: RenderInputs,
) -> ForgeMainDirectPlan:
    """Build measured direct-PDF plans and render proofs for Forge main inputs."""

    _validate_inputs(inputs)
    payloads = _resolved_qr_payloads(inputs)
    items = _qr_payload_items(payloads, config=inputs.qr_config or QrConfig())
    qr_pages = _paginate_qr_items(items)
    context = build_forge_shell_context(inputs, doc_type=DOC_TYPE_MAIN)
    page_plans = tuple(
        _build_page(surface, context, qr_page, total_pages=len(qr_pages)) for qr_page in qr_pages
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
    return ForgeMainDirectPlan(page_plans=page_plans, artifact_proof=artifact_proof)


def _validate_inputs(inputs: RenderInputs) -> None:
    normalized_doc_type = inputs.doc_type.strip().lower()
    if normalized_doc_type != DOC_TYPE_MAIN:
        raise ValueError("direct Forge main renderer only supports main documents")
    if not inputs.render_qr:
        raise ValueError("direct Forge main renderer requires QR rendering")
    if inputs.render_fallback:
        raise ValueError("direct Forge main renderer does not render fallback text")
    if not inputs.frames:
        raise ValueError("frames cannot be empty for direct Forge main rendering")

    paper_size = str(inputs.context.get("paper_size") or "A4").strip().lower()
    if paper_size != "a4":
        raise ValueError("direct Forge main renderer currently supports A4 paper only")

    qr_config = inputs.qr_config or QrConfig()
    qr_kind = str(qr_config.kind or "png").strip().lower()
    if qr_kind != "png":
        raise ValueError("direct Forge main renderer currently supports PNG QR images only")


def _resolved_qr_payloads(inputs: RenderInputs) -> tuple[bytes | str, ...]:
    if inputs.qr_payloads is not None:
        payloads = tuple(inputs.qr_payloads)
    else:
        payloads = tuple(encode_frame(frame) for frame in inputs.frames)
    if len(payloads) != len(inputs.frames):
        raise ValueError("qr_payloads length must match frames")
    return payloads


def _qr_payload_items(
    payloads: Sequence[bytes | str],
    *,
    config: QrConfig,
) -> tuple[_QrPayloadItem, ...]:
    return tuple(
        _QrPayloadItem(
            payload_index=index,
            payload=payload,
            image=qr_bytes(
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
            ),
        )
        for index, payload in enumerate(payloads)
    )


def _paginate_qr_items(items: Sequence[_QrPayloadItem]) -> tuple[_QrPage, ...]:
    if not items:
        raise ValueError("direct Forge main renderer has no QR payloads to render")

    pages: list[_QrPage] = []
    cursor = 0
    page_number = 1
    while cursor < len(items):
        capacity = _page_qr_capacity(page_number)
        page_items = tuple(items[cursor : cursor + capacity])
        pages.append(_QrPage(page_number=page_number, items=page_items))
        cursor += len(page_items)
        page_number += 1
    return tuple(pages)


def _page_qr_capacity(page_number: int) -> int:
    rows = _FIRST_PAGE_QR_ROWS if page_number <= 1 else _CONTINUATION_QR_ROWS
    return _QR_COLUMNS * rows


def _build_page(
    surface: PdfSurface,
    context: ForgeShellContext,
    qr_page: _QrPage,
    *,
    total_pages: int,
) -> DirectPdfPagePlan:
    page_label = f"PAGE {qr_page.page_number} / {total_pages}"
    plans: list[PaintPlan] = []
    plans.extend(
        build_forge_header_plans(
            surface,
            context,
            page_label=page_label,
            page_number=qr_page.page_number,
            component_base=_COMPONENT_BASE,
            classification_default="MASTER KEY",
        )
    )
    if qr_page.page_number == 1:
        plans.extend(_directive_plans(surface, context))
    else:
        plans.extend(_continuation_hint_plans(surface, context, page_number=qr_page.page_number))
    plans.extend(_qr_grid_plans(surface, context, qr_page))
    plans.extend(
        build_forge_footer_plans(
            surface,
            context,
            page_label=page_label,
            page_number=qr_page.page_number,
            component_base=_COMPONENT_BASE,
        )
    )
    return build_page_plan(page_number=qr_page.page_number, rect=FORGE_PAGE_RECT, plans=plans)


def _directive_plans(surface: PdfSurface, context: ForgeShellContext) -> list[PaintPlan]:
    prefix = forge_component_prefix(_COMPONENT_BASE, 1)
    lines = tuple(context.instruction_lines) + (
        "Store this QR document separately from the recovery document.",
    )
    card_width = (FORGE_CONTENT_WIDTH_MM - _DIRECTIVE_CARD_GAP_MM * 3) / 4.0
    plans: list[PaintPlan] = [
        TextBox(
            component_id=f"{prefix}-directives-title",
            text=str(context.copy.get("directives_label") or context.instructions_label),
            style=FORGE_THEME.serif_style(size_pt=13.5, bold=True, color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(FORGE_CONTENT_X_MM, _DIRECTIVE_TITLE_TOP_MM, 62.0, 7.5)),
    ]
    for index, line in enumerate(lines[:4]):
        card_x = FORGE_CONTENT_X_MM + index * (card_width + _DIRECTIVE_CARD_GAP_MM)
        plans.extend(
            _directive_card_plans(
                surface,
                text=line,
                component_index=index,
                rect=PdfRect(card_x, _DIRECTIVE_TOP_MM, card_width, _DIRECTIVE_CARD_HEIGHT_MM),
            )
        )
    plans.append(
        Rule(
            component_id=f"{prefix}-directives-rule",
            color=FORGE_SLATE_200,
        ).plan(surface, PdfRect(FORGE_CONTENT_X_MM, _DIRECTIVE_SECTION_RULE_Y_MM, 180.0, 0.35))
    )
    return plans


def _directive_card_plans(
    surface: PdfSurface,
    *,
    text: str,
    component_index: int,
    rect: PdfRect,
) -> list[PaintPlan]:
    prefix = forge_component_prefix(_COMPONENT_BASE, 1)
    icon = (
        _DIRECTIVE_ICONS[component_index]
        if component_index < len(_DIRECTIVE_ICONS)
        else chr(0xE88E)
    )
    return [
        Panel(
            component_id=f"{prefix}-directive-card-{component_index}",
            stroke=None,
            fill=FORGE_SLATE_50,
            line_width_mm=0.18,
        ).plan(surface, rect),
        TextBox(
            component_id=f"{prefix}-directive-icon-{component_index}",
            text=icon,
            style=FORGE_THEME.symbol_style(size_pt=17.0, color=FORGE_SLATE_800),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(rect.x_mm + 3.0, rect.y_mm + 2.8, 10.0, 7.2)),
        TextBox(
            component_id=f"{prefix}-directive-text-{component_index}",
            text=text,
            style=FORGE_THEME.sans_style(size_pt=9.0, color=FORGE_SLATE_700),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=5.7,
            line_height_multiplier=1.15,
        ).plan(surface, PdfRect(rect.x_mm + 3.0, rect.y_mm + 12.0, rect.width_mm - 6.0, 12.6)),
    ]


def _continuation_hint_plans(
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
        ).plan(surface, PdfRect(FORGE_CONTENT_X_MM, 68.0, FORGE_CONTENT_WIDTH_MM, 8.0)),
        TextBox(
            component_id=f"{prefix}-continuation-hint",
            text=str(context.copy.get("continuation_hint") or ""),
            style=FORGE_THEME.sans_style(size_pt=7.5, bold=True, color=FORGE_SLATE_600),
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.CENTER,
            min_size_pt=4.8,
        ).plan(surface, PdfRect(FORGE_CONTENT_X_MM + 3.0, 70.0, FORGE_CONTENT_WIDTH_MM - 6.0, 4.8)),
    ]


def _qr_grid_plans(
    surface: PdfSurface,
    context: ForgeShellContext,
    qr_page: _QrPage,
) -> list[PaintPlan]:
    prefix = forge_component_prefix(_COMPONENT_BASE, qr_page.page_number)
    top_y = _FIRST_PAGE_QR_TOP_MM if qr_page.page_number <= 1 else _CONTINUATION_QR_TOP_MM
    card_width = (FORGE_CONTENT_WIDTH_MM - (_QR_COLUMNS - 1) * _QR_CARD_GAP_MM) / _QR_COLUMNS
    row_stride = _QR_CARD_HEIGHT_MM + _QR_CARD_GAP_MM
    segment_prefix = str(context.copy.get("segment_prefix") or "Segment").upper()

    plans: list[PaintPlan] = []
    for slot_index, item in enumerate(qr_page.items):
        row = math.floor(slot_index / _QR_COLUMNS)
        col = slot_index % _QR_COLUMNS
        rect = PdfRect(
            FORGE_CONTENT_X_MM + col * (card_width + _QR_CARD_GAP_MM),
            top_y + row * row_stride,
            card_width,
            _QR_CARD_HEIGHT_MM,
        )
        plans.extend(
            _qr_card_plans(
                surface,
                prefix=prefix,
                segment_prefix=segment_prefix,
                item=item,
                rect=rect,
            )
        )
    return plans


def _qr_card_plans(
    surface: PdfSurface,
    *,
    prefix: str,
    segment_prefix: str,
    item: _QrPayloadItem,
    rect: PdfRect,
) -> list[PaintPlan]:
    image_x = rect.x_mm + (rect.width_mm - _QR_IMAGE_SIZE_MM) / 2.0
    image_rect = PdfRect(image_x, rect.y_mm + 10.6, _QR_IMAGE_SIZE_MM, _QR_IMAGE_SIZE_MM)
    label = f"{segment_prefix} {item.label_index:02d}"
    return [
        Panel(
            component_id=f"{prefix}-qr-card-{item.payload_index}",
            stroke=FORGE_SLATE_300,
            fill=FORGE_WHITE,
            line_width_mm=0.2,
        ).plan(surface, rect),
        Rule(
            component_id=f"{prefix}-qr-card-rule-{item.payload_index}",
            color=FORGE_SLATE_100,
        ).plan(surface, PdfRect(rect.x_mm + 3.0, rect.y_mm + 9.2, rect.width_mm - 6.0, 0.35)),
        TextBox(
            component_id=f"{prefix}-qr-label-{item.payload_index}",
            text=label,
            style=FORGE_THEME.mono_style(size_pt=8.5, bold=True, color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(rect.x_mm + 3.0, rect.y_mm + 3.0, rect.width_mm - 6.0, 5.0)),
        ImageBox(
            component_id=f"{prefix}-qr-image-{item.payload_index}",
            image=item.image,
            image_type="PNG",
        ).plan(surface, image_rect),
    ]


__all__ = [
    "ForgeMainDirectPlan",
    "build_forge_main_direct_plan",
    "render_forge_main_direct_pdf",
]
