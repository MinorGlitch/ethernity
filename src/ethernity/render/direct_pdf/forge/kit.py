"""Forge recovery-kit document rendering through direct PDF primitives."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ethernity.qr.codec import QrConfig
from ethernity.render.direct_pdf.assets import packaged_direct_pdf_assets
from ethernity.render.direct_pdf.components import ImageBox, Panel, Rule, TextAlign, TextBox
from ethernity.render.direct_pdf.debug import write_direct_layout_debug_json
from ethernity.render.direct_pdf.forge.common import (
    FORGE_SLATE_50,
    FORGE_SLATE_100,
    FORGE_SLATE_200,
    FORGE_SLATE_300,
    FORGE_SLATE_700,
    FORGE_SLATE_800,
    FORGE_SLATE_900,
    FORGE_WHITE,
    ForgePageLayout,
    ForgeShellContext,
    build_forge_content_constraints,
    build_forge_footer_plans,
    build_forge_header_plans,
    build_forge_page_layout,
    build_forge_shell_context,
)
from ethernity.render.direct_pdf.forge.theme import FORGE_THEME
from ethernity.render.direct_pdf.layout_proof import build_direct_layout_proof
from ethernity.render.direct_pdf.page import (
    ComponentGroup,
    DirectPdfPagePlan,
    LayoutRegion,
    PaintPlan,
    SeparationConstraint,
    build_page_plan,
)
from ethernity.render.direct_pdf.page_geometry import resolve_page_geometry
from ethernity.render.direct_pdf.responsive_layout import GridPolicy, ResolvedGrid, resolve_grid
from ethernity.render.direct_pdf.structured_common import (
    QrPage,
    QrPayloadItem,
    component_prefix,
    qr_payload_items,
    resolved_qr_payloads,
)
from ethernity.render.direct_pdf.surface import FpdfSurface, PdfSurface
from ethernity.render.direct_pdf.text_fit import TextFitPolicy
from ethernity.render.direct_pdf.types import PdfColor, PdfRect, TextStyle
from ethernity.render.doc_types import DOC_TYPE_KIT, DOC_TYPE_KIT_INDEX
from ethernity.render.proofs import build_render_artifact_proof
from ethernity.render.types import RenderArtifactProof, RenderInputs, RenderResult

_KIT_COMPONENT_BASE = "forge-kit"
_KIT_INDEX_COMPONENT_BASE = "forge-kit-index"
_QR_COLUMNS = 3
_QR_MAX_ROWS_PER_PAGE = 3
_QR_CARD_GAP_MM = 4.0
_QR_CARD_HEIGHT_MM = 67.0
_QR_IMAGE_SIZE_MM = 47.0
_QR_TOP_MM = 78.5
_QR_MINIMUM_CARD_WIDTH_MM = 48.5
_QR_MINIMUM_CARD_HEIGHT_MM = 64.2
_INDEX_TABLE_ROW_HEIGHT_MM = 18.5
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
class _ForgeKitGeometry:
    layout: ForgePageLayout
    qr_grid: ResolvedGrid


@dataclass(frozen=True)
class _ForgeKitIndexGeometry:
    layout: ForgePageLayout
    first_page_row_capacity: int
    continuation_row_capacity: int
    first_table_top_mm: float
    continuation_table_top_mm: float
    first_custody_top_mm: float


def _forge_kit_geometry(inputs: RenderInputs) -> _ForgeKitGeometry:
    layout = build_forge_page_layout(resolve_page_geometry(inputs))
    grid_top_mm = layout.regions.body.y_mm + (_QR_TOP_MM - 47.0)
    grid = resolve_grid(
        PdfRect(
            layout.regions.safe.x_mm,
            grid_top_mm,
            layout.regions.safe.width_mm,
            layout.regions.body.bottom_mm - grid_top_mm,
        ),
        GridPolicy(
            max_columns=_QR_COLUMNS,
            max_rows=_QR_MAX_ROWS_PER_PAGE,
            preferred_item_width_mm=(
                layout.regions.safe.width_mm - (_QR_COLUMNS - 1) * _QR_CARD_GAP_MM
            )
            / _QR_COLUMNS,
            preferred_item_height_mm=_QR_CARD_HEIGHT_MM,
            minimum_item_width_mm=_QR_MINIMUM_CARD_WIDTH_MM,
            minimum_item_height_mm=_QR_MINIMUM_CARD_HEIGHT_MM,
            minimum_column_gap_mm=_QR_CARD_GAP_MM,
            minimum_row_gap_mm=_QR_CARD_GAP_MM,
            preserve_item_aspect_ratio=True,
            horizontal_distribution="space_between",
            vertical_distribution="space_between",
        ),
    )
    return _ForgeKitGeometry(layout=layout, qr_grid=grid)


def _forge_kit_index_geometry(inputs: RenderInputs) -> _ForgeKitIndexGeometry:
    layout = build_forge_page_layout(resolve_page_geometry(inputs))
    first_table_top_mm = layout.regions.body.y_mm + 81.5
    continuation_table_top_mm = layout.regions.body.y_mm + 20.0
    custody_height_mm = 59.5
    first_custody_top_mm = layout.regions.body.bottom_mm - custody_height_mm
    first_table_body_top_mm = first_table_top_mm + 10.0
    continuation_table_body_top_mm = continuation_table_top_mm + 10.0
    first_capacity = int(
        (first_custody_top_mm - first_table_body_top_mm) // _INDEX_TABLE_ROW_HEIGHT_MM
    )
    continuation_capacity = int(
        (layout.regions.body.bottom_mm - continuation_table_body_top_mm)
        // _INDEX_TABLE_ROW_HEIGHT_MM
    )
    if first_capacity <= 0 or continuation_capacity <= 0:
        raise ValueError("Forge kit index page body has zero inventory-row capacity")
    return _ForgeKitIndexGeometry(
        layout=layout,
        first_page_row_capacity=first_capacity,
        continuation_row_capacity=continuation_capacity,
        first_table_top_mm=first_table_top_mm,
        continuation_table_top_mm=continuation_table_top_mm,
        first_custody_top_mm=first_custody_top_mm,
    )


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

    page = resolve_page_geometry(inputs)
    surface = FpdfSurface(page_width_mm=page.width_mm, page_height_mm=page.height_mm)
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

    page = resolve_page_geometry(inputs)
    surface = FpdfSurface(page_width_mm=page.width_mm, page_height_mm=page.height_mm)
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
    geometry = _forge_kit_geometry(inputs)
    payloads = resolved_qr_payloads(inputs)
    items = qr_payload_items(payloads, config=inputs.qr_config or QrConfig())
    qr_pages = _paginate_qr_items(items, capacity=geometry.qr_grid.capacity)
    context = build_forge_shell_context(inputs, doc_type=DOC_TYPE_KIT)
    page_plans = tuple(
        _build_kit_qr_page(
            surface,
            context,
            qr_page,
            geometry=geometry,
            total_pages=len(qr_pages) + 1,
        )
        for qr_page in qr_pages
    )
    instructions_page = _build_kit_instruction_page(
        surface,
        context,
        layout=geometry.layout,
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
    geometry = _forge_kit_index_geometry(inputs)
    context = build_forge_shell_context(inputs, doc_type=DOC_TYPE_KIT_INDEX)
    rows = _inventory_rows(inputs)
    pages = _paginate_inventory_rows(rows, geometry=geometry)
    page_plans = tuple(
        _build_index_page(
            surface,
            context,
            page,
            geometry=geometry,
            total_pages=len(pages),
        )
        for page in pages
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

    resolve_page_geometry(inputs)

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

    resolve_page_geometry(inputs)


def _paginate_qr_items(
    items: Sequence[QrPayloadItem],
    *,
    capacity: int,
) -> tuple[QrPage, ...]:
    if not items:
        raise ValueError("direct Forge kit renderer has no QR payloads to render")
    pages: list[QrPage] = []
    for start in range(0, len(items), capacity):
        pages.append(
            QrPage(
                page_number=len(pages) + 1,
                items=tuple(items[start : start + capacity]),
            )
        )
    return tuple(pages)


def _build_kit_qr_page(
    surface: PdfSurface,
    context: ForgeShellContext,
    qr_page: QrPage,
    *,
    geometry: _ForgeKitGeometry,
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
            page_rect=geometry.layout.page.rect,
        )
    )
    plans.extend(
        _kit_warning_plans(
            surface,
            context,
            layout=geometry.layout,
            page_number=qr_page.page_number,
        )
    )
    plans.extend(_kit_qr_grid_plans(surface, qr_page, geometry=geometry))
    plans.extend(
        build_forge_footer_plans(
            surface,
            context,
            page_label=page_label,
            page_number=qr_page.page_number,
            component_base=_KIT_COMPONENT_BASE,
            page_rect=geometry.layout.page.rect,
        )
    )
    prefix = component_prefix(_KIT_COMPONENT_BASE, qr_page.page_number)
    content_ids = (f"{prefix}-warning-panel",) + tuple(
        f"{prefix}-qr-card-{item.payload_index}" for item in qr_page.items
    )
    return build_page_plan(
        page_number=qr_page.page_number,
        rect=geometry.layout.page.rect,
        plans=plans,
        separation_constraints=build_forge_content_constraints(
            component_base=_KIT_COMPONENT_BASE,
            page_number=qr_page.page_number,
            layout=geometry.layout,
            content_component_ids=content_ids,
        ),
    )


def _kit_warning_plans(
    surface: PdfSurface,
    context: ForgeShellContext,
    *,
    layout: ForgePageLayout,
    page_number: int,
) -> list[PaintPlan]:
    prefix = component_prefix(_KIT_COMPONENT_BASE, page_number)
    x_mm = layout.regions.safe.x_mm
    width_mm = layout.regions.safe.width_mm
    return [
        Panel(
            component_id=f"{prefix}-warning-panel",
            stroke=None,
            fill=_FORGE_BLUE_50,
            line_width_mm=0.18,
        ).plan(surface, PdfRect(x_mm, 55.0, width_mm, 15.0)),
        Rule(
            component_id=f"{prefix}-warning-accent",
            color=_FORGE_BLUE,
        ).plan(surface, PdfRect(x_mm, 55.0, 1.0, 15.0)),
        TextBox(
            component_id=f"{prefix}-warning-icon",
            text=_ICON_WARNING,
            style=FORGE_THEME.symbol_style(size_pt=15.0, color=_FORGE_BLUE),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(x_mm + 5.0, 60.0, 8.0, 7.0)),
        TextBox(
            component_id=f"{prefix}-warning-text",
            text=str(context.copy.get("continuation_hint") or ""),
            style=TextStyle(family="Helvetica", size_pt=11.0, color=FORGE_SLATE_800),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=8.5,
        ).plan(surface, PdfRect(x_mm + 14.0, 61.0, width_mm - 22.0, 5.5)),
    ]


def _kit_qr_grid_plans(
    surface: PdfSurface,
    qr_page: QrPage,
    *,
    geometry: _ForgeKitGeometry,
) -> list[PaintPlan]:
    prefix = component_prefix(_KIT_COMPONENT_BASE, qr_page.page_number)
    plans: list[PaintPlan] = []
    rects = geometry.qr_grid.item_rects(len(qr_page.items), reserve_all_rows=True)
    for item, rect in zip(qr_page.items, rects, strict=True):
        plans.extend(_kit_qr_card_plans(surface, prefix=prefix, item=item, rect=rect))
    return plans


def _kit_qr_card_plans(
    surface: PdfSurface,
    *,
    prefix: str,
    item: QrPayloadItem,
    rect: PdfRect,
) -> list[PaintPlan]:
    image_size_mm = rect.height_mm * (_QR_IMAGE_SIZE_MM / _QR_CARD_HEIGHT_MM)
    image_x = rect.x_mm + (rect.width_mm - image_size_mm) / 2.0
    image_rect = PdfRect(image_x, rect.y_mm + 13.5, image_size_mm, image_size_mm)
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
                image_size_mm + 2.4,
                image_size_mm + 2.4,
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
    layout: ForgePageLayout,
    page_number: int,
    total_pages: int,
) -> DirectPdfPagePlan:
    prefix = component_prefix(_KIT_COMPONENT_BASE, page_number)
    safe = layout.regions.safe
    inner_x_mm = safe.x_mm + 7.0
    inner_width_mm = safe.width_mm - 14.0
    column_gap_mm = 8.0
    column_width_mm = (inner_width_mm - column_gap_mm) / 2.0
    right_x_mm = inner_x_mm + column_width_mm + column_gap_mm
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-instruction-shell",
            stroke=FORGE_SLATE_200,
            fill=FORGE_SLATE_50,
            line_width_mm=0.5,
        ).plan(surface, safe),
        TextBox(
            component_id=f"{prefix}-instruction-title",
            text="HOW TO REBUILD THE RECOVERY KIT",
            style=TextStyle(family="Times", size_pt=19.0, style="B", color=FORGE_SLATE_900),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=17.5,
        ).plan(surface, PdfRect(inner_x_mm, 22.0, inner_width_mm, 10.0)),
        TextBox(
            component_id=f"{prefix}-instruction-subtitle",
            text="Use this page after scanning the QR pages. Keep everything offline.",
            style=TextStyle(family="Helvetica", size_pt=10.8, color=FORGE_SLATE_700),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(inner_x_mm, 34.5, inner_width_mm - 20.0, 6.0)),
        Rule(
            component_id=f"{prefix}-instruction-rule",
            color=FORGE_SLATE_300,
        ).plan(surface, PdfRect(inner_x_mm, 42.0, inner_width_mm, 0.45)),
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
            rect=PdfRect(inner_x_mm, 43.5, column_width_mm, 52.0),
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
            rect=PdfRect(inner_x_mm, 102.0, column_width_mm, 42.0),
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
            rect=PdfRect(inner_x_mm, 151.0, column_width_mm, 46.0),
            index=3,
            bullet_icon="disc",
        )
    )
    plans.extend(
        _instruction_right_column_plans(
            surface,
            context,
            prefix=prefix,
            rect=PdfRect(
                right_x_mm,
                43.5,
                column_width_mm,
                layout.regions.body.bottom_mm - 43.5,
            ),
        )
    )
    plans.extend(
        [
            Rule(
                component_id=f"{prefix}-instruction-footer-rule",
                color=FORGE_SLATE_300,
            ).plan(
                surface,
                PdfRect(inner_x_mm, layout.regions.footer.y_mm, inner_width_mm, 0.25),
            ),
            TextBox(
                component_id=f"{prefix}-instruction-footer-kind",
                text="RECOVERY KIT: OFFLINE HTML BUNDLE",
                style=TextStyle(family="Helvetica", size_pt=8.0, color=FORGE_SLATE_700),
                policy=TextFitPolicy.FAIL,
            ).plan(
                surface,
                PdfRect(inner_x_mm, layout.regions.footer.y_mm + 5.0, 72.0, 5.0),
            ),
            TextBox(
                component_id=f"{prefix}-instruction-footer-doc-id",
                text=f"DOCUMENT ID: {context.doc_id}",
                style=TextStyle(family="Courier", size_pt=7.0, color=FORGE_SLATE_700),
                policy=TextFitPolicy.SHRINK,
                align=TextAlign.RIGHT,
                min_size_pt=6.0,
            ).plan(
                surface,
                PdfRect(
                    inner_x_mm + inner_width_mm - 86.0,
                    layout.regions.footer.y_mm + 5.0,
                    86.0,
                    5.0,
                ),
            ),
        ]
    )
    constraints = (
        SeparationConstraint(
            constraint_id=f"{prefix}-instruction-content-before-footer",
            first=ComponentGroup(
                group_id=f"{prefix}-instruction-content",
                component_ids=(
                    f"{prefix}-instruction-badge-3",
                    f"{prefix}-checklist-card",
                ),
            ),
            second=LayoutRegion(
                region_id=f"{prefix}-instruction-footer-region",
                rect=layout.regions.footer,
            ),
            minimum_clearance_mm=3.0,
        ),
    )
    page_label = f"PAGE {page_number} / {total_pages}"
    plans.append(
        TextBox(
            component_id=f"{prefix}-instruction-footer-page",
            text=page_label,
            style=TextStyle(family="Courier", size_pt=7.0, color=FORGE_SLATE_700),
            policy=TextFitPolicy.FAIL,
            align=TextAlign.CENTER,
        ).plan(
            surface,
            PdfRect(
                (layout.page.width_mm - 42.0) / 2.0,
                layout.regions.footer.y_mm + 5.0,
                42.0,
                5.0,
            ),
        )
    )
    return build_page_plan(
        page_number=page_number,
        rect=layout.page.rect,
        plans=plans,
        separation_constraints=constraints,
    )


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

    checklist_y_mm = rect.y_mm + 118.0
    checklist_rect = PdfRect(
        rect.x_mm,
        checklist_y_mm,
        rect.width_mm,
        rect.bottom_mm - checklist_y_mm,
    )
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


def _paginate_inventory_rows(
    rows: Sequence[_InventoryRow],
    *,
    geometry: _ForgeKitIndexGeometry,
) -> tuple[_InventoryPage, ...]:
    source = tuple(rows) or (_InventoryRow("KIT-PAGE-01", "No QR chunks", "Generated"),)
    pages: list[_InventoryPage] = [
        _InventoryPage(
            page_number=1,
            rows=tuple(source[: geometry.first_page_row_capacity]),
        )
    ]
    remaining = source[geometry.first_page_row_capacity :]
    for start in range(0, len(remaining), geometry.continuation_row_capacity):
        pages.append(
            _InventoryPage(
                page_number=len(pages) + 1,
                rows=tuple(remaining[start : start + geometry.continuation_row_capacity]),
            )
        )
    return tuple(pages)


def _build_index_page(
    surface: PdfSurface,
    context: ForgeShellContext,
    page: _InventoryPage,
    *,
    geometry: _ForgeKitIndexGeometry,
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
            page_rect=geometry.layout.page.rect,
        )
    )
    if page.page_number == 1:
        plans.extend(
            _index_stats_plans(
                surface,
                context,
                layout=geometry.layout,
                page_number=page.page_number,
            )
        )
        plans.extend(
            _index_warning_plans(
                surface,
                context,
                layout=geometry.layout,
                page_number=page.page_number,
            )
        )
    else:
        plans.extend(
            _index_continuation_plans(
                surface,
                context,
                layout=geometry.layout,
                page_number=page.page_number,
            )
        )
    table_top_mm = (
        geometry.first_table_top_mm if page.page_number == 1 else geometry.continuation_table_top_mm
    )
    plans.extend(
        _inventory_table_plans(
            surface,
            context,
            page,
            layout=geometry.layout,
            table_top_mm=table_top_mm,
        )
    )
    if page.page_number == 1:
        plans.extend(
            _custody_plans(
                surface,
                context,
                layout=geometry.layout,
                page_number=page.page_number,
                top_mm=geometry.first_custody_top_mm,
            )
        )
    plans.extend(
        _kit_index_footer_plans(
            surface,
            context,
            layout=geometry.layout,
            page_label=page_label,
            page_number=page.page_number,
        )
    )
    prefix = component_prefix(_KIT_INDEX_COMPONENT_BASE, page.page_number)
    content_ids = [f"{prefix}-inventory-header"]
    content_ids.extend(f"{prefix}-inventory-row-{index}" for index in range(len(page.rows)))
    if page.page_number == 1:
        content_ids.extend(
            f"{prefix}-custody-card-{index}"
            for index in range(min(4, len(context.instruction_lines)))
        )
    return build_page_plan(
        page_number=page.page_number,
        rect=geometry.layout.page.rect,
        plans=plans,
        separation_constraints=build_forge_content_constraints(
            component_base=_KIT_INDEX_COMPONENT_BASE,
            page_number=page.page_number,
            layout=geometry.layout,
            content_component_ids=tuple(content_ids),
        ),
    )


def _index_stats_plans(
    surface: PdfSurface,
    context: ForgeShellContext,
    *,
    layout: ForgePageLayout,
    page_number: int,
) -> list[PaintPlan]:
    prefix = component_prefix(_KIT_INDEX_COMPONENT_BASE, page_number)
    x_mm = layout.regions.safe.x_mm
    second_x_mm = x_mm + layout.regions.safe.width_mm / 2.0
    qr_pages = str(context.values.get("kit_qr_page_count") or 0)
    qr_chunks = str(context.values.get("kit_qr_chunk_count") or 0)
    return [
        TextBox(
            component_id=f"{prefix}-qr-pages-label",
            text="QR PAGES",
            style=TextStyle(family="Helvetica", size_pt=9.0, style="B", color=FORGE_SLATE_800),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(x_mm, 68.8, 55.0, 5.5)),
        TextBox(
            component_id=f"{prefix}-qr-pages-value",
            text=qr_pages,
            style=TextStyle(family="Courier", size_pt=8.8, color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(x_mm, 77.0, 55.0, 5.5)),
        TextBox(
            component_id=f"{prefix}-qr-chunks-label",
            text="QR CHUNKS",
            style=TextStyle(family="Helvetica", size_pt=9.0, style="B", color=FORGE_SLATE_800),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(second_x_mm, 68.8, 55.0, 5.5)),
        TextBox(
            component_id=f"{prefix}-qr-chunks-value",
            text=qr_chunks,
            style=TextStyle(family="Courier", size_pt=8.8, color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(second_x_mm, 77.0, 55.0, 5.5)),
    ]


def _index_warning_plans(
    surface: PdfSurface,
    context: ForgeShellContext,
    *,
    layout: ForgePageLayout,
    page_number: int,
) -> list[PaintPlan]:
    prefix = component_prefix(_KIT_INDEX_COMPONENT_BASE, page_number)
    x_mm = layout.regions.safe.x_mm
    width_mm = layout.regions.safe.width_mm
    return [
        Panel(
            component_id=f"{prefix}-warning-panel",
            stroke=None,
            fill=_FORGE_BLUE_50,
            line_width_mm=0.18,
        ).plan(surface, PdfRect(x_mm, 88.0, width_mm, 20.8)),
        Rule(
            component_id=f"{prefix}-warning-accent",
            color=_FORGE_BLUE,
        ).plan(surface, PdfRect(x_mm, 88.0, 1.0, 20.8)),
        TextBox(
            component_id=f"{prefix}-warning-icon",
            text=_ICON_WARNING,
            style=FORGE_THEME.symbol_style(size_pt=15.0, color=_FORGE_BLUE),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(x_mm + 5.0, 94.5, 8.0, 7.0)),
        TextBox(
            component_id=f"{prefix}-warning-title",
            text=str(context.copy.get("warning_title") or "Critical Security Warning").upper(),
            style=TextStyle(family="Helvetica", size_pt=10.0, style="B", color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(x_mm + 14.0, 93.6, 94.0, 5.5)),
        TextBox(
            component_id=f"{prefix}-warning-body",
            text=str(context.copy.get("warning_body") or ""),
            style=TextStyle(family="Helvetica", size_pt=8.4, color=FORGE_SLATE_800),
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=1.05,
        ).plan(surface, PdfRect(x_mm + 14.0, 100.4, width_mm - 22.0, 7.6)),
    ]


def _index_continuation_plans(
    surface: PdfSurface,
    context: ForgeShellContext,
    *,
    layout: ForgePageLayout,
    page_number: int,
) -> list[PaintPlan]:
    prefix = component_prefix(_KIT_INDEX_COMPONENT_BASE, page_number)
    return [
        Panel(
            component_id=f"{prefix}-continuation-panel",
            stroke=FORGE_SLATE_200,
            fill=FORGE_SLATE_50,
            line_width_mm=0.18,
        ).plan(
            surface,
            PdfRect(
                layout.regions.safe.x_mm,
                layout.regions.body.y_mm + 4.0,
                layout.regions.safe.width_mm,
                9.0,
            ),
        ),
        TextBox(
            component_id=f"{prefix}-continuation-text",
            text=str(context.copy.get("continuation_hint") or "Inventory continued"),
            style=TextStyle(family="Helvetica", size_pt=8.0, color=FORGE_SLATE_700),
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.CENTER,
            min_size_pt=6.0,
        ).plan(
            surface,
            PdfRect(
                layout.regions.safe.x_mm + 4.0,
                layout.regions.body.y_mm + 6.5,
                layout.regions.safe.width_mm - 8.0,
                4.5,
            ),
        ),
    ]


def _inventory_table_plans(
    surface: PdfSurface,
    context: ForgeShellContext,
    page: _InventoryPage,
    *,
    layout: ForgePageLayout,
    table_top_mm: float,
) -> list[PaintPlan]:
    prefix = component_prefix(_KIT_INDEX_COMPONENT_BASE, page.page_number)
    x_mm = layout.regions.safe.x_mm
    width_mm = layout.regions.safe.width_mm
    title_y_mm = table_top_mm - 13.8
    plans: list[PaintPlan] = [
        TextBox(
            component_id=f"{prefix}-inventory-icon",
            text=_ICON_INVENTORY,
            style=FORGE_THEME.symbol_style(size_pt=15.0, color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(x_mm, title_y_mm + 1.5, 8.0, 7.0)),
        TextBox(
            component_id=f"{prefix}-inventory-title",
            text=str(context.copy.get("hardware_inventory_label") or "Hardware Inventory").upper(),
            style=TextStyle(family="Helvetica", size_pt=14.0, style="B", color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(x_mm + 9.0, title_y_mm, 100.0, 7.5)),
        Rule(
            component_id=f"{prefix}-inventory-title-rule",
            color=FORGE_SLATE_200,
        ).plan(surface, PdfRect(x_mm, table_top_mm - 4.6, width_mm, 0.35)),
        Panel(
            component_id=f"{prefix}-inventory-header",
            stroke=FORGE_SLATE_200,
            fill=FORGE_SLATE_50,
            line_width_mm=0.15,
        ).plan(surface, PdfRect(x_mm, table_top_mm, width_mm, 10.0)),
    ]
    headers = ("Component ID", "Custodian", "Location", "Status")
    width_ratios = (52.0 / 180.0, 45.0 / 180.0, 48.0 / 180.0, 35.0 / 180.0)
    widths = tuple(width_mm * ratio for ratio in width_ratios)
    x = x_mm
    for index, (header, column_width) in enumerate(zip(headers, widths, strict=True)):
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
            ).plan(surface, PdfRect(x + 3.0, table_top_mm + 2.8, column_width - 6.0, 5.0))
        )
        x += column_width
    for row_index, row in enumerate(page.rows):
        y = table_top_mm + 10.0 + row_index * _INDEX_TABLE_ROW_HEIGHT_MM
        plans.extend(
            _inventory_row_plans(
                surface,
                prefix=prefix,
                row=row,
                row_index=row_index,
                y_mm=y,
                row_height=_INDEX_TABLE_ROW_HEIGHT_MM,
                table_x_mm=x_mm,
                table_width_mm=width_mm,
                column_widths=widths,
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
    table_x_mm: float,
    table_width_mm: float,
    column_widths: tuple[float, ...],
) -> list[PaintPlan]:
    component_width, custodian_width, location_width, status_width = column_widths
    custodian_x_mm = table_x_mm + component_width
    location_x_mm = custodian_x_mm + custodian_width
    status_x_mm = location_x_mm + location_width
    return [
        Panel(
            component_id=f"{prefix}-inventory-row-{row_index}",
            stroke=FORGE_SLATE_200,
            fill=FORGE_WHITE,
            line_width_mm=0.12,
        ).plan(surface, PdfRect(table_x_mm, y_mm, table_width_mm, row_height)),
        TextBox(
            component_id=f"{prefix}-inventory-component-{row_index}",
            text=row.component_id,
            style=TextStyle(family="Courier", size_pt=9.0, style="B", color=FORGE_SLATE_900),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.5,
        ).plan(surface, PdfRect(table_x_mm + 3.0, y_mm + 4.0, component_width - 6.0, 5.0)),
        TextBox(
            component_id=f"{prefix}-inventory-detail-{row_index}",
            text=row.detail,
            style=TextStyle(family="Courier", size_pt=6.4, color=FORGE_SLATE_700),
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=1.0,
        ).plan(
            surface,
            PdfRect(table_x_mm + 3.0, y_mm + 9.7, component_width - 6.0, 7.3),
        ),
        Rule(
            component_id=f"{prefix}-inventory-custodian-line-{row_index}",
            color=FORGE_SLATE_300,
        ).plan(
            surface,
            PdfRect(custodian_x_mm + 3.0, y_mm + 12.3, custodian_width - 6.0, 0.25),
        ),
        Rule(
            component_id=f"{prefix}-inventory-location-line-{row_index}",
            color=FORGE_SLATE_300,
        ).plan(
            surface,
            PdfRect(location_x_mm + 3.0, y_mm + 12.3, location_width - 6.0, 0.25),
        ),
        Panel(
            component_id=f"{prefix}-inventory-status-pill-{row_index}",
            stroke=FORGE_SLATE_200,
            fill=_FORGE_BLUE_50,
            line_width_mm=0.12,
        ).plan(
            surface,
            PdfRect(status_x_mm + 3.5, y_mm + 6.2, status_width - 7.0, 6.0),
        ),
        TextBox(
            component_id=f"{prefix}-inventory-status-{row_index}",
            text=row.status,
            style=TextStyle(family="Helvetica", size_pt=6.6, color=FORGE_SLATE_800),
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.CENTER,
            min_size_pt=6.0,
        ).plan(
            surface,
            PdfRect(status_x_mm + 4.5, y_mm + 7.3, status_width - 9.0, 3.8),
        ),
    ]


def _custody_plans(
    surface: PdfSurface,
    context: ForgeShellContext,
    *,
    layout: ForgePageLayout,
    page_number: int,
    top_mm: float,
) -> list[PaintPlan]:
    prefix = component_prefix(_KIT_INDEX_COMPONENT_BASE, page_number)
    x_mm = layout.regions.safe.x_mm
    width_mm = layout.regions.safe.width_mm
    column_gap_mm = 2.0
    card_width_mm = (width_mm - column_gap_mm) / 2.0
    lines = tuple(context.instruction_lines)
    plans: list[PaintPlan] = [
        TextBox(
            component_id=f"{prefix}-custody-icon",
            text=_ICON_VERIFIED_USER,
            style=FORGE_THEME.symbol_style(size_pt=15.0, color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(x_mm, top_mm, 8.0, 7.0)),
        TextBox(
            component_id=f"{prefix}-custody-title",
            text=str(context.copy.get("chain_of_custody_label") or "Chain of Custody").upper(),
            style=TextStyle(family="Helvetica", size_pt=14.0, style="B", color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(x_mm + 9.0, top_mm - 1.5, 96.0, 7.5)),
        Rule(
            component_id=f"{prefix}-custody-title-rule",
            color=FORGE_SLATE_200,
        ).plan(surface, PdfRect(x_mm, top_mm + 8.5, width_mm, 0.35)),
    ]
    for index, line in enumerate(lines[:4]):
        x = x_mm + (index % 2) * (card_width_mm + column_gap_mm)
        y = top_mm + 15.0 + (index // 2) * 23.0
        plans.extend(
            [
                Panel(
                    component_id=f"{prefix}-custody-card-{index}",
                    stroke=FORGE_SLATE_200,
                    fill=FORGE_SLATE_50,
                    line_width_mm=0.12,
                ).plan(surface, PdfRect(x, y, card_width_mm, 21.5)),
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
                ).plan(surface, PdfRect(x + 13.0, y + 4.3, card_width_mm - 19.0, 13.5)),
            ]
        )
    return plans


def _kit_index_footer_plans(
    surface: PdfSurface,
    context: ForgeShellContext,
    *,
    layout: ForgePageLayout,
    page_label: str,
    page_number: int,
) -> list[PaintPlan]:
    prefix = component_prefix(_KIT_INDEX_COMPONENT_BASE, page_number)
    footer = layout.regions.footer
    right_mm = footer.right_mm
    return [
        Rule(
            component_id=f"{prefix}-index-footer-rule",
            color=FORGE_SLATE_200,
        ).plan(surface, PdfRect(footer.x_mm, footer.y_mm, footer.width_mm, 0.35)),
        TextBox(
            component_id=f"{prefix}-protocol-label",
            text="Ethernity Forge Security Protocols v2.1",
            style=TextStyle(family="Helvetica", size_pt=7.6, color=FORGE_SLATE_900),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(footer.x_mm, footer.y_mm + 3.0, 64.0, 4.5)),
        TextBox(
            component_id=f"{prefix}-session-id",
            text=f"Printed from secure session ID: {context.doc_id}",
            style=TextStyle(family="Helvetica", size_pt=7.4, color=FORGE_SLATE_900),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(footer.x_mm, footer.y_mm + 10.0, 86.0, 4.5)),
        TextBox(
            component_id=f"{prefix}-signature-label",
            text="CUSTODIAN SIGNATURE",
            style=TextStyle(family="Helvetica", size_pt=7.0, style="B", color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
            align=TextAlign.RIGHT,
        ).plan(surface, PdfRect(right_mm - 63.0, footer.y_mm + 3.0, 63.0, 4.5)),
        Rule(
            component_id=f"{prefix}-signature-line",
            color=FORGE_SLATE_300,
        ).plan(surface, PdfRect(right_mm - 50.0, footer.y_mm + 10.0, 50.0, 0.3)),
        TextBox(
            component_id=f"{prefix}-verification-lock",
            text=_ICON_LOCK,
            style=FORGE_THEME.symbol_style(size_pt=12.0, color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(right_mm - 39.0, footer.y_mm + 11.5, 6.0, 6.0)),
        TextBox(
            component_id=f"{prefix}-verification-complete",
            text="Verification Complete",
            style=TextStyle(family="Courier", size_pt=6.2, color=FORGE_SLATE_800),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(right_mm - 32.0, footer.y_mm + 12.5, 32.0, 4.0)),
        TextBox(
            component_id=f"{prefix}-index-footer-page",
            text=page_label,
            style=TextStyle(family="Courier", size_pt=6.2, color=FORGE_SLATE_800),
            policy=TextFitPolicy.FAIL,
            align=TextAlign.CENTER,
        ).plan(
            surface,
            PdfRect((layout.page.width_mm - 38.0) / 2.0, footer.y_mm + 3.0, 38.0, 4.5),
        ),
    ]


__all__ = [
    "ForgeKitDirectPlan",
    "ForgeKitIndexDirectPlan",
    "build_forge_kit_direct_plan",
    "build_forge_kit_index_direct_plan",
    "render_forge_kit_direct_pdf",
    "render_forge_kit_index_direct_pdf",
]
