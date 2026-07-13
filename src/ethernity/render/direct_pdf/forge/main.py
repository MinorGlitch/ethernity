"""Forge main document rendering through direct PDF primitives."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

from ethernity.qr.codec import QrConfig
from ethernity.render.direct_pdf.assets import packaged_direct_pdf_assets
from ethernity.render.direct_pdf.components import ImageBox, Panel, Rule, TextAlign, TextBox
from ethernity.render.direct_pdf.debug import write_direct_layout_debug_json
from ethernity.render.direct_pdf.forge.common import (
    FORGE_SLATE_50,
    FORGE_SLATE_100,
    FORGE_SLATE_200,
    FORGE_SLATE_300,
    FORGE_SLATE_600,
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
from ethernity.render.direct_pdf.page import DirectPdfPagePlan, PaintPlan, build_page_plan
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
_CONTINUATION_PANEL_TOP_MM = 47.0
_CONTINUATION_QR_TOP_MM = 56.0
_FIRST_PAGE_QR_ROWS = 2
_CONTINUATION_QR_ROWS = 3
_DIRECTIVE_TITLE_TOP_MM = 51.0
_DIRECTIVE_TOP_MM = 62.0
_DIRECTIVE_CARD_GAP_MM = 4.25
_DIRECTIVE_CARD_HEIGHT_MM = 27.0
_DIRECTIVE_SECTION_RULE_Y_MM = 95.6
_MINIMUM_QR_CARD_WIDTH_MM = 51.5
_MINIMUM_QR_CARD_HEIGHT_MM = 58.5
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
class _ForgeMainGeometry:
    layout: ForgePageLayout
    first_page_grid: ResolvedGrid
    continuation_grid: ResolvedGrid


def _forge_main_geometry(inputs: RenderInputs) -> _ForgeMainGeometry:
    page = resolve_page_geometry(inputs)
    layout = build_forge_page_layout(page)
    preferred_card_width_mm = (
        layout.regions.safe.width_mm - (_QR_COLUMNS - 1) * _QR_CARD_GAP_MM
    ) / _QR_COLUMNS
    policy = GridPolicy(
        max_columns=_QR_COLUMNS,
        max_rows=_CONTINUATION_QR_ROWS,
        preferred_item_width_mm=preferred_card_width_mm,
        preferred_item_height_mm=_QR_CARD_HEIGHT_MM,
        minimum_item_width_mm=_MINIMUM_QR_CARD_WIDTH_MM,
        minimum_item_height_mm=_MINIMUM_QR_CARD_HEIGHT_MM,
        minimum_column_gap_mm=_QR_CARD_GAP_MM,
        minimum_row_gap_mm=_QR_CARD_GAP_MM,
        preserve_item_aspect_ratio=True,
        horizontal_distribution="space_between",
        vertical_distribution="space_between",
    )
    first_top_mm = layout.regions.body.y_mm + (_FIRST_PAGE_QR_TOP_MM - 47.0)
    continuation_top_mm = layout.regions.body.y_mm + (_CONTINUATION_QR_TOP_MM - 47.0)
    first_page_grid = resolve_grid(
        PdfRect(
            layout.regions.safe.x_mm,
            first_top_mm,
            layout.regions.safe.width_mm,
            layout.regions.body.bottom_mm - first_top_mm,
        ),
        replace(policy, max_rows=_FIRST_PAGE_QR_ROWS),
    )
    continuation_grid = resolve_grid(
        PdfRect(
            layout.regions.safe.x_mm,
            continuation_top_mm,
            layout.regions.safe.width_mm,
            layout.regions.body.bottom_mm - continuation_top_mm,
        ),
        policy,
    )
    return _ForgeMainGeometry(
        layout=layout,
        first_page_grid=first_page_grid,
        continuation_grid=continuation_grid,
    )


def render_forge_main_direct_pdf(inputs: RenderInputs) -> RenderResult:
    """Render a Forge main document directly to PDF and return validation proofs."""

    geometry = resolve_page_geometry(inputs)
    surface = FpdfSurface(
        page_width_mm=geometry.width_mm,
        page_height_mm=geometry.height_mm,
    )
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
    geometry = _forge_main_geometry(inputs)
    payloads = resolved_qr_payloads(inputs)
    items = qr_payload_items(payloads, config=inputs.qr_config or QrConfig())
    qr_pages = _paginate_qr_items(items, geometry=geometry)
    context = build_forge_shell_context(inputs, doc_type=DOC_TYPE_MAIN)
    page_plans = tuple(
        _build_page(
            surface,
            context,
            qr_page,
            geometry=geometry,
            total_pages=len(qr_pages),
        )
        for qr_page in qr_pages
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

    resolve_page_geometry(inputs)

    qr_config = inputs.qr_config or QrConfig()
    qr_kind = str(qr_config.kind or "png").strip().lower()
    if qr_kind != "png":
        raise ValueError("direct Forge main renderer currently supports PNG QR images only")


def _paginate_qr_items(
    items: Sequence[QrPayloadItem],
    *,
    geometry: _ForgeMainGeometry,
) -> tuple[QrPage, ...]:
    if not items:
        raise ValueError("direct Forge main renderer has no QR payloads to render")

    pages: list[QrPage] = []
    cursor = 0
    page_number = 1
    while cursor < len(items):
        capacity = _page_qr_capacity(page_number, geometry=geometry)
        page_items = tuple(items[cursor : cursor + capacity])
        pages.append(QrPage(page_number=page_number, items=page_items))
        cursor += len(page_items)
        page_number += 1
    return tuple(pages)


def _page_qr_capacity(page_number: int, *, geometry: _ForgeMainGeometry) -> int:
    grid = geometry.first_page_grid if page_number <= 1 else geometry.continuation_grid
    return grid.capacity


def _build_page(
    surface: PdfSurface,
    context: ForgeShellContext,
    qr_page: QrPage,
    *,
    geometry: _ForgeMainGeometry,
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
            page_rect=geometry.layout.page.rect,
        )
    )
    if qr_page.page_number == 1:
        plans.extend(_directive_plans(surface, context, geometry))
    else:
        plans.extend(
            _continuation_hint_plans(
                surface,
                context,
                geometry,
                page_number=qr_page.page_number,
            )
        )
    plans.extend(_qr_grid_plans(surface, context, qr_page, geometry))
    plans.extend(
        build_forge_footer_plans(
            surface,
            context,
            page_label=page_label,
            page_number=qr_page.page_number,
            component_base=_COMPONENT_BASE,
            page_rect=geometry.layout.page.rect,
        )
    )
    prefix = component_prefix(_COMPONENT_BASE, qr_page.page_number)
    content_ids = tuple(f"{prefix}-qr-card-{item.payload_index}" for item in qr_page.items)
    content_ids += (
        (f"{prefix}-directives-title",)
        if qr_page.page_number == 1
        else (f"{prefix}-continuation-panel",)
    )
    constraints = build_forge_content_constraints(
        component_base=_COMPONENT_BASE,
        page_number=qr_page.page_number,
        layout=geometry.layout,
        content_component_ids=content_ids,
    )
    return build_page_plan(
        page_number=qr_page.page_number,
        rect=geometry.layout.page.rect,
        plans=plans,
        separation_constraints=constraints,
    )


def _directive_plans(
    surface: PdfSurface,
    context: ForgeShellContext,
    geometry: _ForgeMainGeometry,
) -> list[PaintPlan]:
    prefix = component_prefix(_COMPONENT_BASE, 1)
    lines = tuple(context.instruction_lines) + (
        "Store this QR document separately from the recovery document.",
    )
    content = geometry.layout.regions.safe
    card_width = (content.width_mm - _DIRECTIVE_CARD_GAP_MM * 3) / 4.0
    plans: list[PaintPlan] = [
        TextBox(
            component_id=f"{prefix}-directives-title",
            text=str(context.copy.get("directives_label") or context.instructions_label),
            style=FORGE_THEME.serif_style(size_pt=13.5, bold=True, color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(content.x_mm, _DIRECTIVE_TITLE_TOP_MM, 62.0, 7.5)),
    ]
    for index, line in enumerate(lines[:4]):
        card_x = content.x_mm + index * (card_width + _DIRECTIVE_CARD_GAP_MM)
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
        ).plan(
            surface,
            PdfRect(
                content.x_mm,
                _DIRECTIVE_SECTION_RULE_Y_MM,
                content.width_mm,
                0.35,
            ),
        )
    )
    return plans


def _directive_card_plans(
    surface: PdfSurface,
    *,
    text: str,
    component_index: int,
    rect: PdfRect,
) -> list[PaintPlan]:
    prefix = component_prefix(_COMPONENT_BASE, 1)
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
            min_size_pt=6.0,
            line_height_multiplier=1.15,
        ).plan(surface, PdfRect(rect.x_mm + 3.0, rect.y_mm + 12.0, rect.width_mm - 6.0, 12.6)),
    ]


def _continuation_hint_plans(
    surface: PdfSurface,
    context: ForgeShellContext,
    geometry: _ForgeMainGeometry,
    *,
    page_number: int,
) -> list[PaintPlan]:
    prefix = component_prefix(_COMPONENT_BASE, page_number)
    return [
        Panel(
            component_id=f"{prefix}-continuation-panel",
            stroke=FORGE_SLATE_200,
            fill=FORGE_SLATE_50,
            line_width_mm=0.18,
        ).plan(
            surface,
            PdfRect(
                geometry.layout.regions.safe.x_mm,
                _CONTINUATION_PANEL_TOP_MM,
                geometry.layout.regions.safe.width_mm,
                8.0,
            ),
        ),
        TextBox(
            component_id=f"{prefix}-continuation-hint",
            text=str(context.copy.get("continuation_hint") or ""),
            style=FORGE_THEME.sans_style(size_pt=7.5, bold=True, color=FORGE_SLATE_600),
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.CENTER,
            min_size_pt=6.0,
        ).plan(
            surface,
            PdfRect(
                geometry.layout.regions.safe.x_mm + 3.0,
                _CONTINUATION_PANEL_TOP_MM + 2.0,
                geometry.layout.regions.safe.width_mm - 6.0,
                4.8,
            ),
        ),
    ]


def _qr_grid_plans(
    surface: PdfSurface,
    context: ForgeShellContext,
    qr_page: QrPage,
    geometry: _ForgeMainGeometry,
) -> list[PaintPlan]:
    prefix = component_prefix(_COMPONENT_BASE, qr_page.page_number)
    grid = geometry.first_page_grid if qr_page.page_number <= 1 else geometry.continuation_grid
    segment_prefix = str(context.copy.get("segment_prefix") or "Segment").upper()

    plans: list[PaintPlan] = []
    rects = grid.item_rects(len(qr_page.items), reserve_all_rows=True)
    for item, rect in zip(qr_page.items, rects, strict=True):
        image_size_mm = rect.height_mm * (_QR_IMAGE_SIZE_MM / _QR_CARD_HEIGHT_MM)
        plans.extend(
            _qr_card_plans(
                surface,
                prefix=prefix,
                segment_prefix=segment_prefix,
                item=item,
                rect=rect,
                image_size_mm=image_size_mm,
            )
        )
    return plans


def _qr_card_plans(
    surface: PdfSurface,
    *,
    prefix: str,
    segment_prefix: str,
    item: QrPayloadItem,
    rect: PdfRect,
    image_size_mm: float,
) -> list[PaintPlan]:
    image_x = rect.x_mm + (rect.width_mm - image_size_mm) / 2.0
    image_rect = PdfRect(image_x, rect.y_mm + 10.6, image_size_mm, image_size_mm)
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
