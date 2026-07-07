"""Sentinel main-document rendering through direct PDF primitives."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from ethernity.encoding.framing import encode_frame
from ethernity.qr.codec import QrConfig, qr_bytes
from ethernity.render.direct_pdf.assets import packaged_direct_pdf_assets
from ethernity.render.direct_pdf.components import (
    Ellipse,
    ImageBox,
    Panel,
    Rule,
    TextAlign,
    TextBox,
)
from ethernity.render.direct_pdf.debug import write_direct_layout_debug_json
from ethernity.render.direct_pdf.layout_proof import build_direct_layout_proof
from ethernity.render.direct_pdf.page import DirectPdfPagePlan, PaintPlan, build_page_plan
from ethernity.render.direct_pdf.sentinel_common import (
    SENTINEL_BACKGROUND,
    SENTINEL_BLACK,
    SENTINEL_BORDER,
    SENTINEL_GRID_LINE,
    SENTINEL_ORANGE,
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
from ethernity.render.direct_pdf.types import PdfRect
from ethernity.render.doc_types import DOC_TYPE_MAIN
from ethernity.render.proofs import build_render_artifact_proof
from ethernity.render.types import RenderArtifactProof, RenderInputs, RenderResult

_COMPONENT_BASE = "sentinel-main"
_FIRST_PAGE_CAPACITY = 4
_CONTINUATION_COLUMNS = 3
_CONTINUATION_ROWS = 3
_SMALL_CARD_GAP_MM = 3.4
_SMALL_CARD_WIDTH_MM = 57.7
_SMALL_CARD_HEIGHT_MM = 65.0
_SMALL_CARD_IMAGE_MM = 44.0
_ICON_VISIBILITY_OFF = chr(0xE8F5)
_ICON_INFO = chr(0xE88E)


@dataclass(frozen=True)
class SentinelMainDirectPlan:
    """Measured pages and app-wide proof for one direct Sentinel main render."""

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


def render_sentinel_main_direct_pdf(inputs: RenderInputs) -> RenderResult:
    """Render a Sentinel main document directly to PDF and return validation proofs."""

    surface = build_sentinel_surface()
    packaged_direct_pdf_assets().register_fonts(surface)
    plan = build_sentinel_main_direct_plan(surface, inputs)
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
    return RenderResult(artifact_proof=plan.artifact_proof, layout_proof=layout_proof)


def build_sentinel_main_direct_plan(
    surface: PdfSurface,
    inputs: RenderInputs,
) -> SentinelMainDirectPlan:
    """Build measured direct-PDF plans and render proof for Sentinel main inputs."""

    _validate_inputs(inputs)
    payloads = _resolved_qr_payloads(inputs)
    items = _qr_payload_items(payloads, config=inputs.qr_config or QrConfig())
    qr_pages = _paginate_qr_items(items)
    context = build_sentinel_shell_context(inputs, doc_type=DOC_TYPE_MAIN)
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
    return SentinelMainDirectPlan(page_plans=page_plans, artifact_proof=artifact_proof)


def _validate_inputs(inputs: RenderInputs) -> None:
    normalized_doc_type = inputs.doc_type.strip().lower()
    if normalized_doc_type != DOC_TYPE_MAIN:
        raise ValueError("direct Sentinel main renderer only supports main documents")
    if not inputs.render_qr:
        raise ValueError("direct Sentinel main renderer requires QR rendering")
    if inputs.render_fallback:
        raise ValueError("direct Sentinel main renderer does not render fallback text")
    if not inputs.frames:
        raise ValueError("frames cannot be empty for direct Sentinel main rendering")

    paper_size = str(inputs.context.get("paper_size") or "A4").strip().lower()
    if paper_size != "a4":
        raise ValueError("direct Sentinel main renderer currently supports A4 paper only")

    qr_config = inputs.qr_config or QrConfig()
    qr_kind = str(qr_config.kind or "png").strip().lower()
    if qr_kind != "png":
        raise ValueError("direct Sentinel main renderer currently supports PNG QR images only")


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
        raise ValueError("direct Sentinel main renderer has no QR payloads to render")
    pages: list[_QrPage] = []
    cursor = 0
    page_number = 1
    while cursor < len(items):
        capacity = _FIRST_PAGE_CAPACITY if page_number == 1 else _continuation_capacity()
        page_items = tuple(items[cursor : cursor + capacity])
        pages.append(_QrPage(page_number=page_number, items=page_items))
        cursor += len(page_items)
        page_number += 1
    return tuple(pages)


def _continuation_capacity() -> int:
    return _CONTINUATION_COLUMNS * _CONTINUATION_ROWS


def _build_page(
    surface: PdfSurface,
    context: SentinelShellContext,
    qr_page: _QrPage,
    *,
    total_pages: int,
) -> DirectPdfPagePlan:
    page_label = f"Page {qr_page.page_number} / {total_pages}"
    plans: list[PaintPlan] = []
    plans.extend(
        build_sentinel_header_plans(
            surface,
            context,
            page_label=page_label,
            page_number=qr_page.page_number,
            component_base=_COMPONENT_BASE,
            top_strip_text="Restricted // Offline Handling Only // Do Not Upload",
            title_default="Main Document",
            subtitle_default="Passphrase-Protected Payload",
        )
    )
    if qr_page.page_number == 1:
        plans.extend(_first_page_plans(surface, context, qr_page))
    else:
        plans.extend(_continuation_page_plans(surface, context, qr_page))
    plans.extend(
        build_sentinel_footer_plans(
            surface,
            context,
            page_label=page_label,
            page_number=qr_page.page_number,
            component_base=_COMPONENT_BASE,
        )
    )
    return build_page_plan(page_number=qr_page.page_number, rect=SENTINEL_PAGE_RECT, plans=plans)


def _first_page_plans(
    surface: PdfSurface,
    context: SentinelShellContext,
    qr_page: _QrPage,
) -> list[PaintPlan]:
    plans: list[PaintPlan] = []
    plans.extend(_directive_plans(surface, context))
    if qr_page.items:
        plans.extend(_primary_qr_plans(surface, context, qr_page.items[0]))
    for offset, item in enumerate(qr_page.items[1:]):
        card_x = 15.0 + offset * (_SMALL_CARD_WIDTH_MM + _SMALL_CARD_GAP_MM)
        rect = PdfRect(card_x, 207.0, _SMALL_CARD_WIDTH_MM, _SMALL_CARD_HEIGHT_MM)
        plans.extend(_small_qr_card_plans(surface, context, item, rect, page_number=1))
    return plans


def _directive_plans(surface: PdfSurface, context: SentinelShellContext) -> list[PaintPlan]:
    prefix = sentinel_component_prefix(_COMPONENT_BASE, 1)
    instruction_lines = tuple(context.instruction_lines)
    plans: list[PaintPlan] = [
        Rule(
            component_id=f"{prefix}-directive-divider",
            color=SENTINEL_BORDER,
        ).plan(surface, PdfRect(70.5, 32.2, 0.25, 169.5)),
        TextBox(
            component_id=f"{prefix}-directives-title",
            text=str(context.copy.get("directives_label") or "Directives").upper(),
            style=SENTINEL_THEME.sans_style(size_pt=11.0, bold=True, color=SENTINEL_TEXT),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(15.0, 32.6, 48.0, 5.0)),
    ]
    y_mm = 41.0
    for index, line in enumerate(instruction_lines[:4]):
        plans.extend(
            _directive_row_plans(
                surface,
                prefix=prefix,
                number=index + 1,
                text=line,
                y_mm=y_mm,
            )
        )
        y_mm += 18.0
    plans.extend(_security_notice_plans(surface, context))
    return plans


def _directive_row_plans(
    surface: PdfSurface,
    *,
    prefix: str,
    number: int,
    text: str,
    y_mm: float,
) -> list[PaintPlan]:
    return [
        Ellipse(
            component_id=f"{prefix}-directive-number-fill-{number}",
            stroke=SENTINEL_BLACK,
            fill=SENTINEL_BLACK,
            line_width_mm=0.2,
        ).plan(surface, PdfRect(15.0, y_mm, 6.4, 6.4)),
        TextBox(
            component_id=f"{prefix}-directive-number-{number}",
            text=str(number),
            style=SENTINEL_THEME.sans_style(size_pt=8.2, bold=True, color=SENTINEL_WHITE),
            policy=TextFitPolicy.FAIL,
            align=TextAlign.CENTER,
        ).plan(surface, PdfRect(15.0, y_mm + 1.2, 6.4, 3.8)),
        TextBox(
            component_id=f"{prefix}-directive-text-{number}",
            text=text,
            style=SENTINEL_THEME.sans_style(size_pt=10.2, bold=True, color=SENTINEL_BLACK),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=7.6,
            line_height_multiplier=1.3,
        ).plan(surface, PdfRect(25.0, y_mm, 39.0, 17.0)),
    ]


def _security_notice_plans(surface: PdfSurface, context: SentinelShellContext) -> list[PaintPlan]:
    prefix = sentinel_component_prefix(_COMPONENT_BASE, 1)
    return [
        Panel(
            component_id=f"{prefix}-security-notice-panel",
            stroke=SENTINEL_GRID_LINE,
            fill=SENTINEL_BACKGROUND,
            line_width_mm=0.2,
        ).plan(surface, PdfRect(15.0, 174.0, 51.0, 27.5)),
        TextBox(
            component_id=f"{prefix}-security-notice-icon",
            text=_ICON_VISIBILITY_OFF,
            style=SENTINEL_THEME.symbol_style(size_pt=13.0, color=SENTINEL_ORANGE),
            policy=TextFitPolicy.FAIL,
            line_height_multiplier=1.0,
        ).plan(surface, PdfRect(18.0, 178.4, 6.0, 6.0)),
        TextBox(
            component_id=f"{prefix}-security-notice-title",
            text=str(context.copy.get("security_notice_label") or "Security Notice").upper(),
            style=SENTINEL_THEME.sans_style(size_pt=9.3, bold=True, color=SENTINEL_ORANGE),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.8,
        ).plan(surface, PdfRect(26.0, 179.0, 35.0, 4.2)),
        TextBox(
            component_id=f"{prefix}-security-notice-body",
            text=str(context.copy.get("security_notice_body") or ""),
            style=SENTINEL_THEME.sans_style(size_pt=7.0, color=SENTINEL_TEXT),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=5.4,
            line_height_multiplier=1.15,
        ).plan(surface, PdfRect(18.0, 187.0, 43.5, 11.8)),
    ]


def _primary_qr_plans(
    surface: PdfSurface,
    context: SentinelShellContext,
    item: _QrPayloadItem,
) -> list[PaintPlan]:
    prefix = sentinel_component_prefix(_COMPONENT_BASE, 1)
    frame_rect = PdfRect(92.5, 69.5, 87.0, 87.0)
    image_rect = PdfRect(98.0, 75.0, 76.0, 76.0)
    segment_prefix = str(context.copy.get("segment_prefix") or "Segment")
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-primary-qr-frame",
            stroke=SENTINEL_BLACK,
            fill=SENTINEL_WHITE,
            line_width_mm=0.85,
        ).plan(surface, frame_rect),
        ImageBox(
            component_id=f"{prefix}-primary-qr-image",
            image=item.image,
            image_type="PNG",
        ).plan(surface, image_rect),
        TextBox(
            component_id=f"{prefix}-primary-qr-label",
            text=f"{segment_prefix} {item.label_index:02d}",
            style=SENTINEL_THEME.mono_style(size_pt=9.0, color=SENTINEL_TEXT),
            policy=TextFitPolicy.FAIL,
            align=TextAlign.CENTER,
        ).plan(surface, PdfRect(108.0, 161.0, 55.0, 4.8)),
    ]
    plans.extend(
        build_sentinel_corner_mark_plans(
            surface,
            component_prefix=prefix,
            marker_name="primary",
            rect=frame_rect,
            color=SENTINEL_ORANGE,
            length_mm=4.3,
            width_mm=0.9,
        )
    )
    return plans


def _small_qr_card_plans(
    surface: PdfSurface,
    context: SentinelShellContext,
    item: _QrPayloadItem,
    rect: PdfRect,
    *,
    page_number: int,
) -> list[PaintPlan]:
    prefix = sentinel_component_prefix(_COMPONENT_BASE, page_number)
    label = f"{str(context.copy.get('segment_prefix') or 'Segment').upper()} {item.label_index:02d}"
    image_rect = PdfRect(
        rect.x_mm + (rect.width_mm - _SMALL_CARD_IMAGE_MM) / 2.0,
        rect.y_mm + 15.0,
        _SMALL_CARD_IMAGE_MM,
        _SMALL_CARD_IMAGE_MM,
    )
    image_frame = PdfRect(image_rect.x_mm - 1.0, image_rect.y_mm - 1.0, 46.0, 46.0)
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-qr-card-{item.payload_index}",
            stroke=SENTINEL_BLACK,
            fill=SENTINEL_WHITE,
            line_width_mm=0.25 if page_number == 1 else 0.45,
        ).plan(surface, rect),
        TextBox(
            component_id=f"{prefix}-qr-label-{item.payload_index}",
            text=label,
            style=SENTINEL_THEME.mono_style(size_pt=7.0, bold=True, color=SENTINEL_BLACK),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(rect.x_mm + 3.0, rect.y_mm + 4.0, rect.width_mm - 6.0, 3.8)),
        Rule(
            component_id=f"{prefix}-qr-card-rule-{item.payload_index}",
            color=SENTINEL_GRID_LINE,
        ).plan(surface, PdfRect(rect.x_mm + 3.0, rect.y_mm + 12.0, rect.width_mm - 6.0, 0.3)),
        Panel(
            component_id=f"{prefix}-qr-image-frame-{item.payload_index}",
            stroke=SENTINEL_GRID_LINE,
            fill=SENTINEL_WHITE,
            line_width_mm=0.15,
        ).plan(surface, image_frame),
        ImageBox(
            component_id=f"{prefix}-qr-image-{item.payload_index}",
            image=item.image,
            image_type="PNG",
        ).plan(surface, image_rect),
    ]
    plans.extend(
        build_sentinel_corner_mark_plans(
            surface,
            component_prefix=prefix,
            marker_name=f"card-{item.payload_index}",
            rect=image_frame,
            color=SENTINEL_BLACK,
            length_mm=3.2,
            width_mm=0.5,
        )
    )
    return plans


def _continuation_page_plans(
    surface: PdfSurface,
    context: SentinelShellContext,
    qr_page: _QrPage,
) -> list[PaintPlan]:
    prefix = sentinel_component_prefix(_COMPONENT_BASE, qr_page.page_number)
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-continuation-panel",
            stroke=SENTINEL_ORANGE,
            fill=SENTINEL_BACKGROUND,
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
            component_id=f"{prefix}-continuation-hint",
            text=str(context.copy.get("continuation_hint") or ""),
            style=SENTINEL_THEME.sans_style(size_pt=8.2, color=SENTINEL_BLACK),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(26.0, 37.0, 160.0, 4.5)),
    ]
    top_y = 56.0
    row_stride = _SMALL_CARD_HEIGHT_MM + _SMALL_CARD_GAP_MM
    for slot_index, item in enumerate(qr_page.items):
        row = math.floor(slot_index / _CONTINUATION_COLUMNS)
        col = slot_index % _CONTINUATION_COLUMNS
        rect = PdfRect(
            15.0 + col * (_SMALL_CARD_WIDTH_MM + _SMALL_CARD_GAP_MM),
            top_y + row * row_stride,
            _SMALL_CARD_WIDTH_MM,
            _SMALL_CARD_HEIGHT_MM,
        )
        plans.extend(
            _small_qr_card_plans(surface, context, item, rect, page_number=qr_page.page_number)
        )
    return plans


__all__ = [
    "SentinelMainDirectPlan",
    "build_sentinel_main_direct_plan",
    "render_sentinel_main_direct_pdf",
]
