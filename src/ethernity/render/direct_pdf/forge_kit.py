"""Forge recovery-kit document rendering through direct PDF primitives."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

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
    FORGE_SLATE_700,
    FORGE_SLATE_800,
    FORGE_SLATE_900,
    FORGE_WHITE,
    ForgeShellContext,
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
from ethernity.render.direct_pdf.types import PdfColor, PdfRect, TextStyle
from ethernity.render.doc_types import DOC_TYPE_KIT, DOC_TYPE_KIT_INDEX
from ethernity.render.proofs import build_render_artifact_proof
from ethernity.render.types import RenderArtifactProof, RenderInputs, RenderResult

_KIT_COMPONENT_BASE = "forge-kit"
_KIT_INDEX_COMPONENT_BASE = "forge-kit-index"
_QR_COLUMNS = 3
_QR_ROWS_PER_PAGE = 3
_QR_CARD_GAP_MM = 4.0
_QR_CARD_HEIGHT_MM = 67.0
_QR_IMAGE_SIZE_MM = 47.0
_QR_TOP_MM = 78.5
_INDEX_FIRST_PAGE_ROWS = 4
_INDEX_CONTINUATION_ROWS = 10
_ICON_WARNING = chr(0xE002)
_ICON_INVENTORY = chr(0xE1A1)
_ICON_VERIFIED_USER = chr(0xE8E8)
_ICON_LOCK = chr(0xE88D)
_ICON_ADJUST = chr(0xE39E)
_ICON_BUILD = chr(0xE869)
_ICON_CHECK_BOX = chr(0xE835)
_ICON_HUB = chr(0xE9F4)
_ICON_LANGUAGE = chr(0xE894)
_FORGE_BLUE = PdfColor(25, 118, 210)
_FORGE_BLUE_50 = PdfColor(239, 246, 255)


@dataclass(frozen=True)
class ForgeKitDirectPlan:
    """Measured pages and app-wide proof for one direct Forge kit render."""

    page_plans: tuple[DirectPdfPagePlan, ...]
    artifact_proof: RenderArtifactProof


@dataclass(frozen=True)
class ForgeKitIndexDirectPlan:
    """Measured pages and app-wide proof for one direct Forge kit-index render."""

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


@dataclass(frozen=True)
class _InventoryRow:
    component_id: str
    detail: str
    status: str


@dataclass(frozen=True)
class _InventoryPage:
    page_number: int
    rows: tuple[_InventoryRow, ...]


def render_forge_kit_direct_pdf(inputs: RenderInputs) -> RenderResult:
    """Render a Forge recovery-kit QR document directly to PDF."""

    surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
    packaged_direct_pdf_assets().register_fonts(surface)
    plan = build_forge_kit_direct_plan(surface, inputs)
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


def render_forge_kit_index_direct_pdf(inputs: RenderInputs) -> RenderResult:
    """Render a Forge recovery-kit index document directly to PDF."""

    surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
    packaged_direct_pdf_assets().register_fonts(surface)
    plan = build_forge_kit_index_direct_plan(surface, inputs)
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


def build_forge_kit_direct_plan(
    surface: PdfSurface,
    inputs: RenderInputs,
) -> ForgeKitDirectPlan:
    """Build measured direct-PDF plans and render proof for Forge kit inputs."""

    _validate_kit_inputs(inputs)
    payloads = _resolved_qr_payloads(inputs)
    items = _qr_payload_items(payloads, config=inputs.qr_config or QrConfig())
    qr_pages = _paginate_qr_items(items)
    context = build_forge_shell_context(inputs, doc_type=DOC_TYPE_KIT)
    page_plans = tuple(
        _build_kit_qr_page(surface, context, qr_page, total_pages=len(qr_pages) + 1)
        for qr_page in qr_pages
    )
    instructions_page = _build_kit_instruction_page(
        surface,
        context,
        page_number=len(page_plans) + 1,
        total_pages=len(page_plans) + 1,
    )
    page_plans = (*page_plans, instructions_page)
    artifact_proof = build_render_artifact_proof(
        inputs,
        qr_payloads=payloads,
        encoded_payload_count=len(payloads),
        physical_qr_count=len(items),
        physical_qr_payload_indexes=tuple(item.payload_index for item in items),
        page_count=len(page_plans),
        fallback_proof=None,
    )
    return ForgeKitDirectPlan(page_plans=page_plans, artifact_proof=artifact_proof)


def build_forge_kit_index_direct_plan(
    surface: PdfSurface,
    inputs: RenderInputs,
) -> ForgeKitIndexDirectPlan:
    """Build measured direct-PDF plans and render proof for Forge kit-index inputs."""

    _validate_kit_index_inputs(inputs)
    context = build_forge_shell_context(inputs, doc_type=DOC_TYPE_KIT_INDEX)
    rows = _inventory_rows(inputs)
    pages = _paginate_inventory_rows(rows)
    page_plans = tuple(
        _build_index_page(surface, context, page, total_pages=len(pages)) for page in pages
    )
    artifact_proof = build_render_artifact_proof(
        inputs,
        qr_payloads=(),
        encoded_payload_count=0,
        physical_qr_count=0,
        physical_qr_payload_indexes=(),
        page_count=len(page_plans),
        fallback_proof=None,
    )
    return ForgeKitIndexDirectPlan(page_plans=page_plans, artifact_proof=artifact_proof)


def _validate_kit_inputs(inputs: RenderInputs) -> None:
    if inputs.doc_type.strip().lower() != DOC_TYPE_KIT:
        raise ValueError("direct Forge kit renderer only supports kit documents")
    if not inputs.render_qr:
        raise ValueError("direct Forge kit renderer requires QR rendering")
    if inputs.render_fallback:
        raise ValueError("direct Forge kit renderer does not render fallback text")
    if not inputs.frames:
        raise ValueError("frames cannot be empty for direct Forge kit rendering")

    paper_size = str(inputs.context.get("paper_size") or "A4").strip().lower()
    if paper_size != "a4":
        raise ValueError("direct Forge kit renderer currently supports A4 paper only")

    qr_config = inputs.qr_config or QrConfig()
    qr_kind = str(qr_config.kind or "png").strip().lower()
    if qr_kind != "png":
        raise ValueError("direct Forge kit renderer currently supports PNG QR images only")


def _validate_kit_index_inputs(inputs: RenderInputs) -> None:
    if inputs.doc_type.strip().lower() != DOC_TYPE_KIT_INDEX:
        raise ValueError("direct Forge kit-index renderer only supports kit-index documents")
    if inputs.render_qr or inputs.render_fallback:
        raise ValueError("direct Forge kit-index renderer does not render QR or fallback text")
    if inputs.frames:
        raise ValueError("direct Forge kit-index renderer expects no frames")

    paper_size = str(inputs.context.get("paper_size") or "A4").strip().lower()
    if paper_size != "a4":
        raise ValueError("direct Forge kit-index renderer currently supports A4 paper only")


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
        raise ValueError("direct Forge kit renderer has no QR payloads to render")
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


def _build_kit_qr_page(
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
            component_base=_KIT_COMPONENT_BASE,
            classification_default="Offline Processing Required",
            classification_override="Offline Processing Required",
        )
    )
    plans.extend(_kit_warning_plans(surface, context, page_number=qr_page.page_number))
    plans.extend(_kit_qr_grid_plans(surface, qr_page))
    return build_page_plan(page_number=qr_page.page_number, rect=FORGE_PAGE_RECT, plans=plans)


def _kit_warning_plans(
    surface: PdfSurface,
    context: ForgeShellContext,
    *,
    page_number: int,
) -> list[PaintPlan]:
    prefix = forge_component_prefix(_KIT_COMPONENT_BASE, page_number)
    return [
        Panel(
            component_id=f"{prefix}-warning-panel",
            stroke=None,
            fill=_FORGE_BLUE_50,
            line_width_mm=0.18,
        ).plan(surface, PdfRect(15.0, 55.0, 180.0, 15.0)),
        Rule(
            component_id=f"{prefix}-warning-accent",
            color=_FORGE_BLUE,
        ).plan(surface, PdfRect(15.0, 55.0, 1.0, 15.0)),
        TextBox(
            component_id=f"{prefix}-warning-icon",
            text=_ICON_WARNING,
            style=FORGE_THEME.symbol_style(size_pt=15.0, color=_FORGE_BLUE),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(20.0, 60.0, 8.0, 7.0)),
        TextBox(
            component_id=f"{prefix}-warning-text",
            text=str(context.copy.get("continuation_hint") or ""),
            style=TextStyle(family="Helvetica", size_pt=11.0, color=FORGE_SLATE_800),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=8.5,
        ).plan(surface, PdfRect(29.0, 61.0, 158.0, 5.5)),
    ]


def _kit_qr_grid_plans(surface: PdfSurface, qr_page: _QrPage) -> list[PaintPlan]:
    prefix = forge_component_prefix(_KIT_COMPONENT_BASE, qr_page.page_number)
    card_width = (FORGE_CONTENT_WIDTH_MM - (_QR_COLUMNS - 1) * _QR_CARD_GAP_MM) / _QR_COLUMNS
    row_stride = _QR_CARD_HEIGHT_MM + _QR_CARD_GAP_MM
    plans: list[PaintPlan] = []
    for slot_index, item in enumerate(qr_page.items):
        row = math.floor(slot_index / _QR_COLUMNS)
        col = slot_index % _QR_COLUMNS
        rect = PdfRect(
            FORGE_CONTENT_X_MM + col * (card_width + _QR_CARD_GAP_MM),
            _QR_TOP_MM + row * row_stride,
            card_width,
            _QR_CARD_HEIGHT_MM,
        )
        plans.extend(_kit_qr_card_plans(surface, prefix=prefix, item=item, rect=rect))
    return plans


def _kit_qr_card_plans(
    surface: PdfSurface,
    *,
    prefix: str,
    item: _QrPayloadItem,
    rect: PdfRect,
) -> list[PaintPlan]:
    image_x = rect.x_mm + (rect.width_mm - _QR_IMAGE_SIZE_MM) / 2.0
    image_rect = PdfRect(image_x, rect.y_mm + 13.5, _QR_IMAGE_SIZE_MM, _QR_IMAGE_SIZE_MM)
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
        ).plan(surface, PdfRect(rect.x_mm + 3.0, rect.y_mm + 9.0, rect.width_mm - 6.0, 0.35)),
        TextBox(
            component_id=f"{prefix}-qr-label-{item.payload_index}",
            text=f"KIT {item.label_index:02d}",
            style=TextStyle(family="Courier", size_pt=6.6, style="B", color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(rect.x_mm + 3.0, rect.y_mm + 3.0, rect.width_mm - 6.0, 5.0)),
        Panel(
            component_id=f"{prefix}-qr-image-backdrop-{item.payload_index}",
            fill=FORGE_SLATE_900,
            line_width_mm=0.2,
        ).plan(
            surface,
            PdfRect(
                image_rect.x_mm - 1.2,
                image_rect.y_mm - 1.2,
                _QR_IMAGE_SIZE_MM + 2.4,
                _QR_IMAGE_SIZE_MM + 2.4,
            ),
        ),
        ImageBox(
            component_id=f"{prefix}-qr-image-{item.payload_index}",
            image=item.image,
            image_type="PNG",
        ).plan(surface, image_rect),
    ]


def _build_kit_instruction_page(
    surface: PdfSurface,
    context: ForgeShellContext,
    *,
    page_number: int,
    total_pages: int,
) -> DirectPdfPagePlan:
    _ = total_pages
    prefix = forge_component_prefix(_KIT_COMPONENT_BASE, page_number)
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-instruction-shell",
            stroke=FORGE_SLATE_200,
            fill=FORGE_SLATE_50,
            line_width_mm=0.5,
        ).plan(surface, PdfRect(15.0, 15.0, 180.0, 267.0)),
        TextBox(
            component_id=f"{prefix}-instruction-title",
            text="HOW TO REBUILD THE RECOVERY KIT",
            style=TextStyle(family="Times", size_pt=19.0, style="B", color=FORGE_SLATE_900),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=17.5,
        ).plan(surface, PdfRect(22.0, 22.0, 166.0, 10.0)),
        TextBox(
            component_id=f"{prefix}-instruction-subtitle",
            text="Use this page after scanning the QR pages. Keep everything offline.",
            style=TextStyle(family="Helvetica", size_pt=10.8, color=FORGE_SLATE_700),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(22.0, 34.5, 146.0, 6.0)),
        Rule(
            component_id=f"{prefix}-instruction-rule",
            color=FORGE_SLATE_300,
        ).plan(surface, PdfRect(22.0, 42.0, 166.0, 0.45)),
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
            rect=PdfRect(22.0, 43.5, 80.0, 52.0),
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
            rect=PdfRect(22.0, 102.0, 80.0, 42.0),
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
            rect=PdfRect(22.0, 151.0, 80.0, 46.0),
            index=3,
            bullet_icon="disc",
        )
    )
    plans.extend(
        _instruction_right_column_plans(
            surface,
            context,
            prefix=prefix,
            rect=PdfRect(110.0, 43.5, 78.0, 199.0),
        )
    )
    plans.extend(
        [
            Rule(
                component_id=f"{prefix}-instruction-footer-rule",
                color=FORGE_SLATE_300,
            ).plan(surface, PdfRect(22.0, 263.0, 166.0, 0.25)),
            TextBox(
                component_id=f"{prefix}-instruction-footer-kind",
                text="RECOVERY KIT: OFFLINE HTML BUNDLE",
                style=TextStyle(family="Helvetica", size_pt=8.0, color=FORGE_SLATE_700),
                policy=TextFitPolicy.FAIL,
            ).plan(surface, PdfRect(22.0, 268.0, 72.0, 5.0)),
            TextBox(
                component_id=f"{prefix}-instruction-footer-doc-id",
                text=f"DOCUMENT ID: {context.doc_id}",
                style=TextStyle(family="Courier", size_pt=7.0, color=FORGE_SLATE_700),
                policy=TextFitPolicy.SHRINK,
                align=TextAlign.RIGHT,
                min_size_pt=5.4,
            ).plan(surface, PdfRect(102.0, 268.0, 86.0, 5.0)),
        ]
    )
    return build_page_plan(page_number=page_number, rect=FORGE_PAGE_RECT, plans=plans)


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
    header_width = min(rect.width_mm, 18.0 + len(title) * 1.7)
    plans: list[PaintPlan] = _instruction_badge_plans(
        surface,
        prefix=prefix,
        title=title,
        icon=icon,
        rect=PdfRect(rect.x_mm, rect.y_mm, header_width, 9.0),
        index=index,
    )
    bullet_top = rect.y_mm + 14.0
    for line_index, line in enumerate(lines):
        y_mm = bullet_top + line_index * 11.0
        if bullet_icon == "disc":
            plans.append(
                Panel(
                    component_id=f"{prefix}-instruction-disc-{index}-{line_index}",
                    fill=FORGE_SLATE_800,
                    line_width_mm=0.18,
                ).plan(surface, PdfRect(rect.x_mm + 0.8, y_mm + 3.1, 1.0, 1.0))
            )
        else:
            plans.append(
                TextBox(
                    component_id=f"{prefix}-instruction-bullet-icon-{index}-{line_index}",
                    text=_ICON_ADJUST,
                    style=FORGE_THEME.symbol_style(size_pt=16.0, color=FORGE_SLATE_900),
                    policy=TextFitPolicy.FAIL,
                    line_height_multiplier=1.0,
                ).plan(surface, PdfRect(rect.x_mm, y_mm, 7.0, 7.0))
            )
        plans.append(
            TextBox(
                component_id=f"{prefix}-instruction-line-{index}-{line_index}",
                text=line,
                style=TextStyle(family="Helvetica", size_pt=10.7, color=FORGE_SLATE_800),
                policy=TextFitPolicy.WRAP,
                line_height_multiplier=1.16,
            ).plan(surface, PdfRect(rect.x_mm + 8.0, y_mm, rect.width_mm - 8.0, 10.0))
        )
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
            stroke=FORGE_SLATE_900,
            fill=None,
            line_width_mm=0.25,
        ).plan(surface, rect),
        TextBox(
            component_id=f"{prefix}-instruction-badge-icon-{index}",
            text=icon,
            style=FORGE_THEME.symbol_style(size_pt=15.5, color=FORGE_SLATE_800),
            policy=TextFitPolicy.FAIL,
            line_height_multiplier=1.0,
        ).plan(surface, PdfRect(rect.x_mm + 3.0, rect.y_mm + 1.2, 6.0, 7.0)),
        TextBox(
            component_id=f"{prefix}-instruction-section-title-{index}",
            text=title.upper(),
            style=TextStyle(family="Helvetica", size_pt=8.8, style="B", color=FORGE_SLATE_900),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=7.0,
        ).plan(surface, PdfRect(rect.x_mm + 11.5, rect.y_mm + 2.5, rect.width_mm - 14.0, 4.2)),
    ]


def _instruction_right_column_plans(
    surface: PdfSurface,
    context: ForgeShellContext,
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
            PdfRect(rect.x_mm, rect.y_mm, rect.width_mm, 34.0),
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
            PdfRect(rect.x_mm, rect.y_mm + 78.0, rect.width_mm, 38.0),
        ),
    )
    for index, (title, paragraphs, card_rect) in enumerate(cards):
        plans.extend(
            _instruction_info_card_plans(surface, prefix, title, paragraphs, card_rect, index)
        )

    checklist_rect = PdfRect(rect.x_mm, rect.y_mm + 118.0, rect.width_mm, 86.0)
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
            stroke=FORGE_SLATE_300,
            fill=FORGE_WHITE,
            line_width_mm=0.22,
        ).plan(surface, rect),
        TextBox(
            component_id=f"{prefix}-summary-title-{index}",
            text=title.upper(),
            style=TextStyle(family="Helvetica", size_pt=8.1, style="B", color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(rect.x_mm + 3.5, rect.y_mm + 4.0, rect.width_mm - 7.0, 4.5)),
    ]
    y_mm = rect.y_mm + 12.5
    for paragraph_index, paragraph in enumerate(paragraphs):
        plans.append(
            TextBox(
                component_id=f"{prefix}-summary-body-{index}-{paragraph_index}",
                text=paragraph,
                style=TextStyle(family="Helvetica", size_pt=10.6, color=FORGE_SLATE_800),
                policy=TextFitPolicy.WRAP,
                line_height_multiplier=1.16,
            ).plan(surface, PdfRect(rect.x_mm + 3.5, y_mm, rect.width_mm - 7.0, 10.5))
        )
        y_mm += 10.7
    return plans


def _instruction_checklist_plans(
    surface: PdfSurface,
    context: ForgeShellContext,
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
            stroke=FORGE_SLATE_300,
            fill=FORGE_WHITE,
            line_width_mm=0.22,
        ).plan(surface, rect),
        TextBox(
            component_id=f"{prefix}-checklist-icon",
            text=_ICON_VERIFIED_USER,
            style=FORGE_THEME.symbol_style(size_pt=15.0, color=FORGE_SLATE_800),
            policy=TextFitPolicy.FAIL,
            line_height_multiplier=1.0,
        ).plan(surface, PdfRect(rect.x_mm + 3.5, rect.y_mm + 3.8, 6.0, 7.0)),
        TextBox(
            component_id=f"{prefix}-checklist-title",
            text=str(
                context.copy.get("checklist_label") or "Security Verification Checklist"
            ).upper(),
            style=TextStyle(family="Helvetica", size_pt=8.0, style="B", color=FORGE_SLATE_900),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.6,
        ).plan(surface, PdfRect(rect.x_mm + 11.0, rect.y_mm + 5.0, rect.width_mm - 14.5, 4.5)),
    ]
    y_mm = rect.y_mm + 16.0
    checklist_text_style = TextStyle(family="Helvetica", size_pt=9.4, color=FORGE_SLATE_800)
    for line_index, line in enumerate(checklist_lines):
        text_plan = TextBox(
            component_id=f"{prefix}-checklist-line-{line_index}",
            text=line,
            style=checklist_text_style,
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=1.08,
        ).plan(surface, PdfRect(rect.x_mm + 12.0, y_mm, rect.width_mm - 16.0, 13.0))
        plans.append(
            TextBox(
                component_id=f"{prefix}-checklist-box-{line_index}",
                text=_ICON_CHECK_BOX,
                style=FORGE_THEME.symbol_style(size_pt=16.0, color=FORGE_SLATE_800),
                policy=TextFitPolicy.FAIL,
                line_height_multiplier=1.0,
            ).plan(surface, PdfRect(rect.x_mm + 4.0, y_mm, 6.0, 7.0))
        )
        plans.append(text_plan)
        y_mm += max(9.0, text_plan.proof.used_rect.height_mm + 2.0)
    return plans


def _inventory_rows(inputs: RenderInputs) -> tuple[_InventoryRow, ...]:
    raw_rows = inputs.context.get("inventory_rows")
    if isinstance(raw_rows, Sequence) and not isinstance(raw_rows, (str, bytes)):
        mapped_rows = tuple(
            _inventory_row_from_mapping(row) for row in raw_rows if isinstance(row, Mapping)
        )
        if mapped_rows:
            return mapped_rows

    page_count = _positive_int(inputs.context.get("kit_qr_page_count"), default=0)
    chunk_count = _positive_int(inputs.context.get("kit_qr_chunk_count"), default=0)
    rows: list[_InventoryRow] = []
    if page_count <= 0:
        return (_InventoryRow("KIT-PAGE-01", "No QR chunks", "Generated"),)
    chunks_per_page = max(1, math.ceil(max(1, chunk_count) / page_count))
    for page_index in range(page_count):
        first_chunk = page_index * chunks_per_page + 1
        last_chunk = min(chunk_count, first_chunk + chunks_per_page - 1)
        detail = (
            f"KIT {first_chunk:02d}"
            if last_chunk <= first_chunk
            else f"KIT {first_chunk:02d} to KIT {last_chunk:02d}"
        )
        rows.append(
            _InventoryRow(
                component_id=f"KIT-PAGE-{page_index + 1:02d}",
                detail=detail,
                status="Generated",
            )
        )
    return tuple(rows)


def _inventory_row_from_mapping(row: Mapping[object, object]) -> _InventoryRow:
    return _InventoryRow(
        component_id=str(row.get("component_id") or "KIT-PAGE"),
        detail=str(row.get("detail") or ""),
        status=str(row.get("status") or "Generated"),
    )


def _positive_int(value: object, *, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(0, value)


def _paginate_inventory_rows(rows: Sequence[_InventoryRow]) -> tuple[_InventoryPage, ...]:
    source = tuple(rows) or (_InventoryRow("KIT-PAGE-01", "No QR chunks", "Generated"),)
    pages: list[_InventoryPage] = [
        _InventoryPage(page_number=1, rows=tuple(source[:_INDEX_FIRST_PAGE_ROWS]))
    ]
    remaining = source[_INDEX_FIRST_PAGE_ROWS:]
    for start in range(0, len(remaining), _INDEX_CONTINUATION_ROWS):
        pages.append(
            _InventoryPage(
                page_number=len(pages) + 1,
                rows=tuple(remaining[start : start + _INDEX_CONTINUATION_ROWS]),
            )
        )
    return tuple(pages)


def _build_index_page(
    surface: PdfSurface,
    context: ForgeShellContext,
    page: _InventoryPage,
    *,
    total_pages: int,
) -> DirectPdfPagePlan:
    page_label = f"PAGE {page.page_number} / {total_pages}"
    plans: list[PaintPlan] = []
    plans.extend(
        build_forge_header_plans(
            surface,
            context,
            page_label=page_label,
            page_number=page.page_number,
            component_base=_KIT_INDEX_COMPONENT_BASE,
            classification_default="Authorized Personnel Only",
        )
    )
    plans.extend(_index_stats_plans(surface, context, page_number=page.page_number))
    plans.extend(_index_warning_plans(surface, context, page_number=page.page_number))
    plans.extend(_inventory_table_plans(surface, context, page))
    plans.extend(_custody_plans(surface, context, page_number=page.page_number))
    plans.extend(_kit_index_footer_plans(surface, context, page_number=page.page_number))
    return build_page_plan(page_number=page.page_number, rect=FORGE_PAGE_RECT, plans=plans)


def _index_stats_plans(
    surface: PdfSurface,
    context: ForgeShellContext,
    *,
    page_number: int,
) -> list[PaintPlan]:
    prefix = forge_component_prefix(_KIT_INDEX_COMPONENT_BASE, page_number)
    qr_pages = str(context.values.get("kit_qr_page_count") or 0)
    qr_chunks = str(context.values.get("kit_qr_chunk_count") or 0)
    return [
        TextBox(
            component_id=f"{prefix}-qr-pages-label",
            text="QR PAGES",
            style=TextStyle(family="Helvetica", size_pt=9.0, style="B", color=FORGE_SLATE_800),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(15.0, 68.8, 55.0, 5.5)),
        TextBox(
            component_id=f"{prefix}-qr-pages-value",
            text=qr_pages,
            style=TextStyle(family="Courier", size_pt=8.8, color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(15.0, 77.0, 55.0, 5.5)),
        TextBox(
            component_id=f"{prefix}-qr-chunks-label",
            text="QR CHUNKS",
            style=TextStyle(family="Helvetica", size_pt=9.0, style="B", color=FORGE_SLATE_800),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(103.0, 68.8, 55.0, 5.5)),
        TextBox(
            component_id=f"{prefix}-qr-chunks-value",
            text=qr_chunks,
            style=TextStyle(family="Courier", size_pt=8.8, color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(103.0, 77.0, 55.0, 5.5)),
    ]


def _index_warning_plans(
    surface: PdfSurface,
    context: ForgeShellContext,
    *,
    page_number: int,
) -> list[PaintPlan]:
    prefix = forge_component_prefix(_KIT_INDEX_COMPONENT_BASE, page_number)
    return [
        Panel(
            component_id=f"{prefix}-warning-panel",
            stroke=None,
            fill=_FORGE_BLUE_50,
            line_width_mm=0.18,
        ).plan(surface, PdfRect(15.0, 88.0, 180.0, 20.8)),
        Rule(
            component_id=f"{prefix}-warning-accent",
            color=_FORGE_BLUE,
        ).plan(surface, PdfRect(15.0, 88.0, 1.0, 20.8)),
        TextBox(
            component_id=f"{prefix}-warning-icon",
            text=_ICON_WARNING,
            style=FORGE_THEME.symbol_style(size_pt=15.0, color=_FORGE_BLUE),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(20.0, 94.5, 8.0, 7.0)),
        TextBox(
            component_id=f"{prefix}-warning-title",
            text=str(context.copy.get("warning_title") or "Critical Security Warning").upper(),
            style=TextStyle(family="Helvetica", size_pt=10.0, style="B", color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(29.0, 93.6, 94.0, 5.5)),
        TextBox(
            component_id=f"{prefix}-warning-body",
            text=str(context.copy.get("warning_body") or ""),
            style=TextStyle(family="Helvetica", size_pt=8.4, color=FORGE_SLATE_800),
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=1.05,
        ).plan(surface, PdfRect(29.0, 100.4, 158.0, 7.6)),
    ]


def _inventory_table_plans(
    surface: PdfSurface,
    context: ForgeShellContext,
    page: _InventoryPage,
) -> list[PaintPlan]:
    prefix = forge_component_prefix(_KIT_INDEX_COMPONENT_BASE, page.page_number)
    table_top = 128.5
    row_height = 18.5
    plans: list[PaintPlan] = [
        TextBox(
            component_id=f"{prefix}-inventory-icon",
            text=_ICON_INVENTORY,
            style=FORGE_THEME.symbol_style(size_pt=15.0, color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(15.0, 116.2, 8.0, 7.0)),
        TextBox(
            component_id=f"{prefix}-inventory-title",
            text=str(context.copy.get("hardware_inventory_label") or "Hardware Inventory").upper(),
            style=TextStyle(family="Helvetica", size_pt=14.0, style="B", color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(24.0, 114.7, 100.0, 7.5)),
        Rule(
            component_id=f"{prefix}-inventory-title-rule",
            color=FORGE_SLATE_200,
        ).plan(surface, PdfRect(15.0, 123.9, 180.0, 0.35)),
        Panel(
            component_id=f"{prefix}-inventory-header",
            stroke=FORGE_SLATE_200,
            fill=FORGE_SLATE_50,
            line_width_mm=0.15,
        ).plan(surface, PdfRect(15.0, table_top, 180.0, 10.0)),
    ]
    headers = ("Component ID", "Custodian", "Location", "Status")
    widths = (52.0, 45.0, 48.0, 35.0)
    x = 15.0
    for index, (header, width) in enumerate(zip(headers, widths, strict=True)):
        plans.append(
            TextBox(
                component_id=f"{prefix}-inventory-header-{index}",
                text=header.upper(),
                style=TextStyle(
                    family="Helvetica",
                    size_pt=9.2,
                    style="B",
                    color=FORGE_SLATE_900,
                ),
                policy=TextFitPolicy.FAIL,
            ).plan(surface, PdfRect(x + 3.0, table_top + 2.8, width - 6.0, 5.0))
        )
        x += width
    for row_index, row in enumerate(page.rows):
        y = table_top + 10.0 + row_index * row_height
        plans.extend(
            _inventory_row_plans(
                surface,
                prefix=prefix,
                row=row,
                row_index=row_index,
                y_mm=y,
                row_height=row_height,
            )
        )
    return plans


def _inventory_row_plans(
    surface: PdfSurface,
    *,
    prefix: str,
    row: _InventoryRow,
    row_index: int,
    y_mm: float,
    row_height: float,
) -> list[PaintPlan]:
    return [
        Panel(
            component_id=f"{prefix}-inventory-row-{row_index}",
            stroke=FORGE_SLATE_200,
            fill=FORGE_WHITE,
            line_width_mm=0.12,
        ).plan(surface, PdfRect(15.0, y_mm, 180.0, row_height)),
        TextBox(
            component_id=f"{prefix}-inventory-component-{row_index}",
            text=row.component_id,
            style=TextStyle(family="Courier", size_pt=9.0, style="B", color=FORGE_SLATE_900),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.5,
        ).plan(surface, PdfRect(18.0, y_mm + 4.0, 48.0, 5.0)),
        TextBox(
            component_id=f"{prefix}-inventory-detail-{row_index}",
            text=row.detail,
            style=TextStyle(family="Courier", size_pt=6.4, color=FORGE_SLATE_700),
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=1.0,
        ).plan(surface, PdfRect(18.0, y_mm + 9.7, 48.0, 7.3)),
        Rule(
            component_id=f"{prefix}-inventory-custodian-line-{row_index}",
            color=FORGE_SLATE_300,
        ).plan(surface, PdfRect(73.0, y_mm + 12.3, 43.0, 0.25)),
        Rule(
            component_id=f"{prefix}-inventory-location-line-{row_index}",
            color=FORGE_SLATE_300,
        ).plan(surface, PdfRect(123.0, y_mm + 12.3, 38.0, 0.25)),
        Panel(
            component_id=f"{prefix}-inventory-status-pill-{row_index}",
            stroke=FORGE_SLATE_200,
            fill=_FORGE_BLUE_50,
            line_width_mm=0.12,
        ).plan(surface, PdfRect(170.0, y_mm + 6.2, 18.0, 6.0)),
        TextBox(
            component_id=f"{prefix}-inventory-status-{row_index}",
            text=row.status,
            style=TextStyle(family="Helvetica", size_pt=6.6, color=FORGE_SLATE_800),
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.CENTER,
            min_size_pt=5.2,
        ).plan(surface, PdfRect(171.0, y_mm + 7.3, 16.0, 3.8)),
    ]


def _custody_plans(
    surface: PdfSurface,
    context: ForgeShellContext,
    *,
    page_number: int,
) -> list[PaintPlan]:
    prefix = forge_component_prefix(_KIT_INDEX_COMPONENT_BASE, page_number)
    top = 202.0
    lines = tuple(context.instruction_lines)
    plans: list[PaintPlan] = [
        TextBox(
            component_id=f"{prefix}-custody-icon",
            text=_ICON_VERIFIED_USER,
            style=FORGE_THEME.symbol_style(size_pt=15.0, color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(15.0, top, 8.0, 7.0)),
        TextBox(
            component_id=f"{prefix}-custody-title",
            text=str(context.copy.get("chain_of_custody_label") or "Chain of Custody").upper(),
            style=TextStyle(family="Helvetica", size_pt=14.0, style="B", color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(24.0, top - 1.5, 96.0, 7.5)),
        Rule(
            component_id=f"{prefix}-custody-title-rule",
            color=FORGE_SLATE_200,
        ).plan(surface, PdfRect(15.0, top + 8.5, 180.0, 0.35)),
    ]
    for index, line in enumerate(lines[:4]):
        x = 15.0 + (index % 2) * 90.0
        y = top + 15.0 + (index // 2) * 23.0
        plans.extend(
            [
                Panel(
                    component_id=f"{prefix}-custody-card-{index}",
                    stroke=FORGE_SLATE_200,
                    fill=FORGE_SLATE_50,
                    line_width_mm=0.12,
                ).plan(surface, PdfRect(x, y, 89.0, 21.5)),
                Panel(
                    component_id=f"{prefix}-custody-check-{index}",
                    stroke=FORGE_SLATE_300,
                    fill=FORGE_WHITE,
                    line_width_mm=0.25,
                ).plan(surface, PdfRect(x + 3.5, y + 4.2, 5.8, 5.8)),
                TextBox(
                    component_id=f"{prefix}-custody-line-{index}",
                    text=line,
                    style=TextStyle(
                        family="Helvetica",
                        size_pt=8.6,
                        style="B",
                        color=FORGE_SLATE_800,
                    ),
                    policy=TextFitPolicy.WRAP,
                    line_height_multiplier=1.18,
                ).plan(surface, PdfRect(x + 13.0, y + 4.3, 70.0, 13.5)),
            ]
        )
    return plans


def _kit_index_footer_plans(
    surface: PdfSurface,
    context: ForgeShellContext,
    *,
    page_number: int,
) -> list[PaintPlan]:
    prefix = forge_component_prefix(_KIT_INDEX_COMPONENT_BASE, page_number)
    return [
        Rule(
            component_id=f"{prefix}-index-footer-rule",
            color=FORGE_SLATE_200,
        ).plan(surface, PdfRect(15.0, 263.0, 180.0, 0.35)),
        TextBox(
            component_id=f"{prefix}-protocol-label",
            text="Ethernity Forge Security Protocols v2.1",
            style=TextStyle(family="Helvetica", size_pt=7.6, color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(15.0, 282.0, 78.0, 4.5)),
        TextBox(
            component_id=f"{prefix}-session-id",
            text=f"Printed from secure session ID: {context.doc_id}",
            style=TextStyle(family="Helvetica", size_pt=7.4, color=FORGE_SLATE_900),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=5.4,
        ).plan(surface, PdfRect(15.0, 287.2, 86.0, 4.5)),
        TextBox(
            component_id=f"{prefix}-signature-label",
            text="CUSTODIAN SIGNATURE",
            style=TextStyle(family="Helvetica", size_pt=7.0, style="B", color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
            align=TextAlign.RIGHT,
        ).plan(surface, PdfRect(132.0, 268.5, 63.0, 4.5)),
        Rule(
            component_id=f"{prefix}-signature-line",
            color=FORGE_SLATE_300,
        ).plan(surface, PdfRect(145.0, 282.8, 50.0, 0.3)),
        TextBox(
            component_id=f"{prefix}-verification-lock",
            text=_ICON_LOCK,
            style=FORGE_THEME.symbol_style(size_pt=12.0, color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(156.0, 288.2, 6.0, 6.0)),
        TextBox(
            component_id=f"{prefix}-verification-complete",
            text="Verification Complete",
            style=TextStyle(family="Courier", size_pt=6.2, color=FORGE_SLATE_800),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(163.0, 290.0, 32.0, 4.0)),
    ]


__all__ = [
    "ForgeKitDirectPlan",
    "ForgeKitIndexDirectPlan",
    "build_forge_kit_direct_plan",
    "build_forge_kit_index_direct_plan",
    "render_forge_kit_direct_pdf",
    "render_forge_kit_index_direct_pdf",
]
