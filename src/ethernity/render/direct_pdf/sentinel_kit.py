"""Sentinel recovery-kit document rendering through direct PDF primitives."""

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
from ethernity.render.direct_pdf.text_fit import TextFitPolicy
from ethernity.render.direct_pdf.types import PdfColor, PdfRect, TextStyle
from ethernity.render.doc_types import DOC_TYPE_KIT
from ethernity.render.proofs import build_render_artifact_proof
from ethernity.render.types import RenderArtifactProof, RenderInputs, RenderResult

_COMPONENT_BASE = "sentinel-kit"
_QR_COLUMNS = 3
_QR_ROWS_PER_PAGE = 3
_QR_CARD_GAP_MM = 2.2
_QR_CARD_HEIGHT_MM = 63.6
_QR_IMAGE_SIZE_MM = 50.8
_QR_FRAME_SIZE_MM = 53.6
_QR_TOP_MM = 52.6
_QR_CONTENT_X_MM = 15.0
_QR_CONTENT_WIDTH_MM = 180.0
_INSTRUCTION_FRAME_RECT = PdfRect(15.0, 13.0, 180.0, 269.0)
_INSTRUCTION_RULE_COLOR = PdfColor(209, 199, 183)
_INSTRUCTION_CARD_FILL = PdfColor(255, 247, 231)
_INSTRUCTION_CARD_BORDER = PdfColor(250, 203, 114)
_DOT_COLOR = PdfColor(246, 244, 240)
_ICON_WARNING = chr(0xE002)
_ICON_ADJUST = chr(0xE39E)
_ICON_BUILD = chr(0xE869)
_ICON_CHECK_BOX = chr(0xE835)
_ICON_HUB = chr(0xE9F4)
_ICON_LANGUAGE = chr(0xE894)
_ICON_VERIFIED_USER = chr(0xE8E8)


@dataclass(frozen=True)
class SentinelKitDirectPlan:
    """Measured pages and app-wide proof for one direct Sentinel kit render."""

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


def render_sentinel_kit_direct_pdf(inputs: RenderInputs) -> RenderResult:
    """Render a Sentinel recovery-kit QR document directly to PDF."""

    surface = build_sentinel_surface()
    packaged_direct_pdf_assets().register_fonts(surface)
    plan = build_sentinel_kit_direct_plan(surface, inputs)
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


def build_sentinel_kit_direct_plan(
    surface: PdfSurface,
    inputs: RenderInputs,
) -> SentinelKitDirectPlan:
    """Build measured direct-PDF plans and render proof for Sentinel kit inputs."""

    _validate_inputs(inputs)
    payloads = _resolved_qr_payloads(inputs)
    items = _qr_payload_items(payloads, config=inputs.qr_config or QrConfig())
    qr_pages = _paginate_qr_items(items)
    context = build_sentinel_shell_context(inputs, doc_type=DOC_TYPE_KIT)
    total_pages = len(qr_pages) + 1
    page_plans = tuple(
        _build_qr_page(surface, context, qr_page, total_pages=total_pages) for qr_page in qr_pages
    )
    instruction_page = _build_instruction_page(
        surface,
        context,
        page_number=total_pages,
    )
    page_plans = (*page_plans, instruction_page)
    artifact_proof = build_render_artifact_proof(
        inputs,
        qr_payloads=payloads,
        encoded_payload_count=len(payloads),
        physical_qr_count=len(items),
        physical_qr_payload_indexes=tuple(item.payload_index for item in items),
        page_count=len(page_plans),
        fallback_proof=None,
    )
    return SentinelKitDirectPlan(page_plans=page_plans, artifact_proof=artifact_proof)


def _validate_inputs(inputs: RenderInputs) -> None:
    if inputs.doc_type.strip().lower() != DOC_TYPE_KIT:
        raise ValueError("direct Sentinel kit renderer only supports kit documents")
    if not inputs.render_qr:
        raise ValueError("direct Sentinel kit renderer requires QR rendering")
    if inputs.render_fallback:
        raise ValueError("direct Sentinel kit renderer does not render fallback text")
    if not inputs.frames:
        raise ValueError("frames cannot be empty for direct Sentinel kit rendering")

    paper_size = str(inputs.context.get("paper_size") or "A4").strip().lower()
    if paper_size != "a4":
        raise ValueError("direct Sentinel kit renderer currently supports A4 paper only")

    qr_config = inputs.qr_config or QrConfig()
    qr_kind = str(qr_config.kind or "png").strip().lower()
    if qr_kind != "png":
        raise ValueError("direct Sentinel kit renderer currently supports PNG QR images only")


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
        raise ValueError("direct Sentinel kit renderer has no QR payloads to render")
    capacity = _QR_COLUMNS * _QR_ROWS_PER_PAGE
    pages: list[_QrPage] = []
    for start in range(0, len(items), capacity):
        pages.append(
            _QrPage(
                page_number=len(pages) + 1,
                items=tuple(items[start : start + capacity]),
            )
        )
    return tuple(pages)


def _build_qr_page(
    surface: PdfSurface,
    context: SentinelShellContext,
    qr_page: _QrPage,
    *,
    total_pages: int,
) -> DirectPdfPagePlan:
    page_label = f"Page {qr_page.page_number} / {total_pages}"
    prefix = sentinel_component_prefix(_COMPONENT_BASE, qr_page.page_number)
    plans: list[PaintPlan] = []
    plans.extend(
        build_sentinel_header_plans(
            surface,
            context,
            page_label=page_label,
            page_number=qr_page.page_number,
            component_base=_COMPONENT_BASE,
            top_strip_text="Recovery Kit Media // Offline Processing Only // Do Not Scan Online",
            title_default="Recovery Kit",
            subtitle_default="Standalone Offline HTML Bundle",
        )
    )
    plans.extend(_background_dot_plans(surface, prefix=prefix))
    plans.extend(_warning_plans(surface, context, prefix=prefix))
    plans.extend(_qr_grid_plans(surface, qr_page, prefix=prefix))
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


def _background_dot_plans(surface: PdfSurface, *, prefix: str) -> list[PaintPlan]:
    plans: list[PaintPlan] = []
    dot_size = 0.34
    index = 0
    for y_mm in _frange(34.0, 281.0, 9.5):
        for x_mm in _frange(6.0, 204.0, 9.5):
            plans.append(
                Ellipse(
                    component_id=f"{prefix}-background-dot-{index}",
                    fill=_DOT_COLOR,
                    line_width_mm=0.1,
                ).plan(surface, PdfRect(x_mm, y_mm, dot_size, dot_size))
            )
            index += 1
    return plans


def _warning_plans(
    surface: PdfSurface,
    context: SentinelShellContext,
    *,
    prefix: str,
) -> list[PaintPlan]:
    return [
        Panel(
            component_id=f"{prefix}-warning-panel",
            stroke=_INSTRUCTION_CARD_BORDER,
            fill=SENTINEL_WARNING_FILL,
            line_width_mm=0.18,
        ).plan(surface, PdfRect(15.0, 32.2, 180.0, 12.8)),
        TextBox(
            component_id=f"{prefix}-warning-icon",
            text=_ICON_WARNING,
            style=SENTINEL_THEME.symbol_style(size_pt=16.0, color=SENTINEL_MUTED),
            policy=TextFitPolicy.FAIL,
            line_height_multiplier=1.0,
        ).plan(surface, PdfRect(18.6, 35.7, 8.0, 6.5)),
        TextBox(
            component_id=f"{prefix}-warning-text",
            text=str(context.copy.get("continuation_hint") or "").upper(),
            style=SENTINEL_THEME.sans_style(
                size_pt=9.4,
                bold=True,
                color=SENTINEL_MUTED,
                char_spacing_mm=0.04,
            ),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=7.5,
        ).plan(surface, PdfRect(28.5, 37.2, 160.0, 4.8)),
    ]


def _qr_grid_plans(
    surface: PdfSurface,
    qr_page: _QrPage,
    *,
    prefix: str,
) -> list[PaintPlan]:
    card_width = (_QR_CONTENT_WIDTH_MM - (_QR_COLUMNS - 1) * _QR_CARD_GAP_MM) / _QR_COLUMNS
    row_stride = _QR_CARD_HEIGHT_MM + _QR_CARD_GAP_MM
    plans: list[PaintPlan] = []
    for slot_index, item in enumerate(qr_page.items):
        row = math.floor(slot_index / _QR_COLUMNS)
        col = slot_index % _QR_COLUMNS
        rect = PdfRect(
            _QR_CONTENT_X_MM + col * (card_width + _QR_CARD_GAP_MM),
            _QR_TOP_MM + row * row_stride,
            card_width,
            _QR_CARD_HEIGHT_MM,
        )
        plans.extend(_qr_card_plans(surface, prefix=prefix, item=item, rect=rect))
    return plans


def _qr_card_plans(
    surface: PdfSurface,
    *,
    prefix: str,
    item: _QrPayloadItem,
    rect: PdfRect,
) -> list[PaintPlan]:
    frame_x = rect.x_mm + (rect.width_mm - _QR_FRAME_SIZE_MM) / 2.0
    frame_rect = PdfRect(frame_x, rect.y_mm + 7.5, _QR_FRAME_SIZE_MM, _QR_FRAME_SIZE_MM)
    image_rect = PdfRect(
        frame_rect.x_mm + (_QR_FRAME_SIZE_MM - _QR_IMAGE_SIZE_MM) / 2.0,
        frame_rect.y_mm + (_QR_FRAME_SIZE_MM - _QR_IMAGE_SIZE_MM) / 2.0,
        _QR_IMAGE_SIZE_MM,
        _QR_IMAGE_SIZE_MM,
    )
    return [
        Panel(
            component_id=f"{prefix}-qr-card-{item.payload_index}",
            stroke=_INSTRUCTION_RULE_COLOR,
            fill=SENTINEL_WHITE,
            line_width_mm=0.22,
        ).plan(surface, rect),
        TextBox(
            component_id=f"{prefix}-qr-label-{item.payload_index}",
            text=f"PART {item.label_index:02d}",
            style=SENTINEL_THEME.mono_style(
                size_pt=6.5,
                color=SENTINEL_TEXT,
                char_spacing_mm=0.24,
            ),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(rect.x_mm + 2.3, rect.y_mm + 3.1, rect.width_mm - 5.0, 3.8)),
        Panel(
            component_id=f"{prefix}-qr-frame-{item.payload_index}",
            stroke=SENTINEL_TEXT,
            fill=SENTINEL_WHITE,
            line_width_mm=0.55,
        ).plan(surface, frame_rect),
        ImageBox(
            component_id=f"{prefix}-qr-image-{item.payload_index}",
            image=item.image,
            image_type="PNG",
        ).plan(surface, image_rect),
    ]


def _build_instruction_page(
    surface: PdfSurface,
    context: SentinelShellContext,
    *,
    page_number: int,
) -> DirectPdfPagePlan:
    prefix = sentinel_component_prefix(_COMPONENT_BASE, page_number)
    plans: list[PaintPlan] = []
    plans.extend(
        _top_strip_plans(
            surface,
            prefix=prefix,
            text="Recovery Kit Media // Offline Processing Only // Do Not Scan Online",
        )
    )
    plans.extend(_instruction_shell_plans(surface, context, prefix=prefix))
    return build_page_plan(page_number=page_number, rect=SENTINEL_PAGE_RECT, plans=plans)


def _top_strip_plans(surface: PdfSurface, *, prefix: str, text: str) -> list[PaintPlan]:
    layout = SENTINEL_THEME.layout
    text_scale = SENTINEL_THEME.text
    return [
        Panel(
            component_id=f"{prefix}-top-strip",
            stroke=None,
            fill=SENTINEL_ORANGE,
            line_width_mm=0.2,
        ).plan(
            surface,
            PdfRect(0.0, 0.0, layout.page_width_mm, layout.top_strip_height_mm),
        ),
        TextBox(
            component_id=f"{prefix}-top-strip-text",
            text=text.upper(),
            style=SENTINEL_THEME.sans_style(
                size_pt=text_scale.top_strip_pt,
                bold=True,
                color=SENTINEL_BLACK,
                char_spacing_mm=0.25,
            ),
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.CENTER,
            min_size_pt=text_scale.top_strip_min_pt,
        ).plan(surface, PdfRect(15.0, 2.2, 180.0, 3.8)),
        Rule(
            component_id=f"{prefix}-top-strip-rule",
            color=SENTINEL_BLACK,
        ).plan(
            surface,
            PdfRect(
                0.0,
                layout.top_strip_height_mm,
                layout.page_width_mm,
                layout.top_strip_rule_height_mm,
            ),
        ),
    ]


def _instruction_shell_plans(
    surface: PdfSurface,
    context: SentinelShellContext,
    *,
    prefix: str,
) -> list[PaintPlan]:
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-instruction-shell",
            stroke=_INSTRUCTION_RULE_COLOR,
            fill=SENTINEL_BACKGROUND,
            line_width_mm=0.55,
        ).plan(surface, _INSTRUCTION_FRAME_RECT),
        TextBox(
            component_id=f"{prefix}-instruction-title",
            text="HOW TO REBUILD THE RECOVERY KIT",
            style=TextStyle(family="Times", size_pt=20.5, style="B", color=SENTINEL_TEXT),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=17.0,
        ).plan(surface, PdfRect(22.0, 21.2, 166.0, 10.0)),
        TextBox(
            component_id=f"{prefix}-instruction-subtitle",
            text="Use this page after scanning the QR pages. Keep everything offline.",
            style=SENTINEL_THEME.sans_style(size_pt=10.7, color=SENTINEL_TEXT),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=8.5,
        ).plan(surface, PdfRect(22.0, 34.3, 154.0, 6.0)),
        Rule(
            component_id=f"{prefix}-instruction-title-rule",
            color=_INSTRUCTION_RULE_COLOR,
        ).plan(surface, PdfRect(22.0, 42.2, 166.0, 0.45)),
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
            rect=PdfRect(22.0, 48.0, 80.0, 49.0),
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
            rect=PdfRect(22.0, 112.0, 80.0, 42.0),
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
            rect=PdfRect(22.0, 161.0, 80.0, 45.0),
            index=3,
            bullet_icon="disc",
        )
    )
    plans.extend(
        _instruction_right_column_plans(
            surface,
            context,
            prefix=prefix,
            rect=PdfRect(110.0, 48.0, 78.0, 200.0),
        )
    )
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
    header_width = min(rect.width_mm, 19.0 + len(title) * 1.62)
    plans: list[PaintPlan] = _instruction_badge_plans(
        surface,
        prefix=prefix,
        title=title,
        icon=icon,
        rect=PdfRect(rect.x_mm, rect.y_mm, header_width, 7.9),
        index=index,
    )
    y_mm = rect.y_mm + 13.0
    for line_index, line in enumerate(lines):
        if bullet_icon == "disc":
            plans.append(
                Ellipse(
                    component_id=f"{prefix}-instruction-disc-{index}-{line_index}",
                    fill=SENTINEL_TEXT,
                    line_width_mm=0.18,
                ).plan(surface, PdfRect(rect.x_mm + 0.2, y_mm + 3.0, 1.0, 1.0))
            )
        else:
            plans.append(
                TextBox(
                    component_id=f"{prefix}-instruction-bullet-icon-{index}-{line_index}",
                    text=_ICON_ADJUST,
                    style=SENTINEL_THEME.symbol_style(size_pt=13.4, color=SENTINEL_TEXT),
                    policy=TextFitPolicy.FAIL,
                    line_height_multiplier=1.0,
                ).plan(surface, PdfRect(rect.x_mm, y_mm, 6.0, 6.0))
            )
        text_plan = TextBox(
            component_id=f"{prefix}-instruction-line-{index}-{line_index}",
            text=line,
            style=SENTINEL_THEME.sans_style(size_pt=10.2, color=SENTINEL_TEXT),
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=1.16,
        ).plan(surface, PdfRect(rect.x_mm + 8.0, y_mm - 0.3, rect.width_mm - 8.0, 12.8))
        plans.append(text_plan)
        y_mm += max(9.0, text_plan.proof.used_rect.height_mm + 2.4)
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
            stroke=SENTINEL_TEXT,
            fill=None,
            line_width_mm=0.25,
        ).plan(surface, rect),
        TextBox(
            component_id=f"{prefix}-instruction-badge-icon-{index}",
            text=icon,
            style=SENTINEL_THEME.symbol_style(size_pt=13.0, color=SENTINEL_TEXT),
            policy=TextFitPolicy.FAIL,
            line_height_multiplier=1.0,
        ).plan(surface, PdfRect(rect.x_mm + 2.3, rect.y_mm + 1.3, 5.0, 5.5)),
        TextBox(
            component_id=f"{prefix}-instruction-section-title-{index}",
            text=title.upper(),
            style=SENTINEL_THEME.sans_style(
                size_pt=7.8,
                bold=True,
                color=SENTINEL_TEXT,
                char_spacing_mm=0.18,
            ),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.3,
        ).plan(surface, PdfRect(rect.x_mm + 10.5, rect.y_mm + 2.2, rect.width_mm - 12.4, 3.8)),
    ]


def _instruction_right_column_plans(
    surface: PdfSurface,
    context: SentinelShellContext,
    *,
    prefix: str,
    rect: PdfRect,
) -> list[PaintPlan]:
    plans: list[PaintPlan] = []
    cards = (
        (
            "Verify",
            (
                "Confirm the kit loads and shows the Recovery Kit home screen.",
                "If it fails to open, re-check the order and re-save the file.",
            ),
            PdfRect(rect.x_mm, rect.y_mm, rect.width_mm, 34.2),
        ),
        (
            "Storage",
            (
                "Keep the QR pages and the bundle file in separate locations.",
                "Store the bundle on a write-protected drive if possible.",
            ),
            PdfRect(rect.x_mm, rect.y_mm + 37.5, rect.width_mm, 36.5),
        ),
        (
            "Security",
            (
                "Work offline and on a trusted machine.",
                "Delete temporary files after successful recovery.",
            ),
            PdfRect(rect.x_mm, rect.y_mm + 77.8, rect.width_mm, 35.0),
        ),
    )
    for index, (title, paragraphs, card_rect) in enumerate(cards):
        plans.extend(
            _instruction_info_card_plans(surface, prefix, title, paragraphs, card_rect, index)
        )

    checklist_rect = PdfRect(rect.x_mm, rect.y_mm + 116.6, rect.width_mm, 85.0)
    plans.extend(_instruction_checklist_plans(surface, context, prefix=prefix, rect=checklist_rect))
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
            component_id=f"{prefix}-summary-card-{index}",
            stroke=_INSTRUCTION_CARD_BORDER,
            fill=_INSTRUCTION_CARD_FILL,
            line_width_mm=0.2,
        ).plan(surface, rect),
        TextBox(
            component_id=f"{prefix}-summary-title-{index}",
            text=title.upper(),
            style=SENTINEL_THEME.sans_style(
                size_pt=7.5,
                bold=True,
                color=SENTINEL_TEXT,
                char_spacing_mm=0.16,
            ),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(rect.x_mm + 3.3, rect.y_mm + 4.0, rect.width_mm - 6.6, 4.0)),
    ]
    y_mm = rect.y_mm + 12.4
    for paragraph_index, paragraph in enumerate(paragraphs):
        text_plan = TextBox(
            component_id=f"{prefix}-summary-body-{index}-{paragraph_index}",
            text=paragraph,
            style=SENTINEL_THEME.sans_style(
                size_pt=10.2 if paragraph_index == 0 else 9.4,
                color=SENTINEL_TEXT,
            ),
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=1.16,
        ).plan(surface, PdfRect(rect.x_mm + 3.3, y_mm, rect.width_mm - 6.6, 13.0))
        plans.append(text_plan)
        y_mm += max(8.7, text_plan.proof.used_rect.height_mm + 2.0)
    return plans


def _instruction_checklist_plans(
    surface: PdfSurface,
    context: SentinelShellContext,
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
            stroke=_INSTRUCTION_CARD_BORDER,
            fill=_INSTRUCTION_CARD_FILL,
            line_width_mm=0.2,
        ).plan(surface, rect),
        TextBox(
            component_id=f"{prefix}-checklist-icon",
            text=_ICON_VERIFIED_USER,
            style=SENTINEL_THEME.symbol_style(size_pt=12.0, color=SENTINEL_TEXT),
            policy=TextFitPolicy.FAIL,
            line_height_multiplier=1.0,
        ).plan(surface, PdfRect(rect.x_mm + 3.4, rect.y_mm + 4.0, 5.0, 5.0)),
        TextBox(
            component_id=f"{prefix}-checklist-title",
            text=str(
                context.copy.get("checklist_label") or "Security Verification Checklist"
            ).upper(),
            style=SENTINEL_THEME.sans_style(
                size_pt=7.3,
                bold=True,
                color=SENTINEL_TEXT,
                char_spacing_mm=0.15,
            ),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(rect.x_mm + 9.8, rect.y_mm + 4.8, rect.width_mm - 13.0, 4.3)),
    ]
    y_mm = rect.y_mm + 15.5
    for line_index, line in enumerate(checklist_lines):
        text_plan = TextBox(
            component_id=f"{prefix}-checklist-line-{line_index}",
            text=line,
            style=SENTINEL_THEME.sans_style(size_pt=9.9, color=SENTINEL_TEXT),
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=1.08,
        ).plan(surface, PdfRect(rect.x_mm + 12.0, y_mm, rect.width_mm - 16.0, 12.6))
        plans.append(
            TextBox(
                component_id=f"{prefix}-checklist-box-{line_index}",
                text=_ICON_CHECK_BOX,
                style=SENTINEL_THEME.symbol_style(size_pt=13.5, color=SENTINEL_TEXT),
                policy=TextFitPolicy.FAIL,
                line_height_multiplier=1.0,
            ).plan(surface, PdfRect(rect.x_mm + 3.7, y_mm - 0.1, 5.5, 5.8))
        )
        plans.append(text_plan)
        y_mm += max(8.7, text_plan.proof.used_rect.height_mm + 1.9)
    return plans


def _instruction_footer_plans(
    surface: PdfSurface,
    context: SentinelShellContext,
    *,
    prefix: str,
) -> list[PaintPlan]:
    return [
        Rule(
            component_id=f"{prefix}-instruction-footer-rule",
            color=_INSTRUCTION_RULE_COLOR,
        ).plan(surface, PdfRect(22.0, 267.6, 166.0, 0.25)),
        TextBox(
            component_id=f"{prefix}-instruction-footer-kind",
            text="RECOVERY KIT: OFFLINE HTML BUNDLE",
            style=SENTINEL_THEME.sans_style(
                size_pt=7.3,
                color=SENTINEL_TEXT,
                char_spacing_mm=0.22,
            ),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=5.7,
        ).plan(surface, PdfRect(22.0, 272.0, 80.0, 4.5)),
        TextBox(
            component_id=f"{prefix}-instruction-footer-doc-id",
            text=f"DOCUMENT ID: {context.doc_id}",
            style=SENTINEL_THEME.mono_style(size_pt=6.6, color=SENTINEL_TEXT),
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.RIGHT,
            min_size_pt=5.0,
        ).plan(surface, PdfRect(103.0, 272.0, 85.0, 4.5)),
    ]


def _frange(start: float, stop: float, step: float) -> tuple[float, ...]:
    values: list[float] = []
    value = start
    while value <= stop:
        values.append(value)
        value += step
    return tuple(values)


__all__ = [
    "SentinelKitDirectPlan",
    "build_sentinel_kit_direct_plan",
    "render_sentinel_kit_direct_pdf",
]
