"""Sentinel recovery-kit index rendering through direct PDF primitives."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ethernity.render.direct_pdf.assets import packaged_direct_pdf_assets
from ethernity.render.direct_pdf.components import Line, Panel, Rule, TextAlign, TextBox
from ethernity.render.direct_pdf.debug import write_direct_layout_debug_json
from ethernity.render.direct_pdf.layout_proof import build_direct_layout_proof
from ethernity.render.direct_pdf.page import DirectPdfPagePlan, PaintPlan
from ethernity.render.direct_pdf.page_geometry import resolve_page_geometry
from ethernity.render.direct_pdf.responsive_layout import GridPolicy, resolve_grid
from ethernity.render.direct_pdf.sentinel.common import (
    SENTINEL_BACKGROUND,
    SENTINEL_BLACK,
    SENTINEL_BORDER,
    SENTINEL_MUTED,
    SENTINEL_ORANGE,
    SENTINEL_TEXT,
    SENTINEL_WHITE,
    SentinelPageLayout,
    SentinelShellContext,
    build_sentinel_footer_plans,
    build_sentinel_header_plans,
    build_sentinel_page_plan,
    build_sentinel_shell_context,
    build_sentinel_surface,
)
from ethernity.render.direct_pdf.sentinel.theme import SENTINEL_THEME
from ethernity.render.direct_pdf.structured_common import component_prefix
from ethernity.render.direct_pdf.surface import PdfSurface
from ethernity.render.direct_pdf.text_fit import TextFitPolicy
from ethernity.render.direct_pdf.types import PdfColor, PdfRect
from ethernity.render.doc_types import DOC_TYPE_KIT_INDEX
from ethernity.render.proofs import build_render_artifact_proof
from ethernity.render.types import RenderArtifactProof, RenderInputs, RenderResult

_COMPONENT_BASE = "sentinel-kit-index"
_MAX_INVENTORY_ROWS = 14
_MIN_INVENTORY_ROW_HEIGHT_MM = 16.4
_INVENTORY_TABLE_RECT = PdfRect(15.5, 90.5, 179.0, 60.5)
_CUSTODY_TABLE_RECT = PdfRect(15.5, 168.0, 179.0, 100.8)
_DASH_COLOR = PdfColor(214, 201, 176)
_ICON_WARNING = chr(0xE002)


@dataclass(frozen=True)
class SentinelKitIndexDirectPlan:
    """Measured pages and proof for one direct Sentinel kit-index render."""

    page_plans: tuple[DirectPdfPagePlan, ...]
    artifact_proof: RenderArtifactProof


@dataclass(frozen=True)
class _InventoryRow:
    component_id: str
    detail: str


@dataclass(frozen=True)
class _InventoryPage:
    page_number: int
    rows: tuple[_InventoryRow, ...]


def render_sentinel_kit_index_direct_pdf(inputs: RenderInputs) -> RenderResult:
    """Render a Sentinel kit-index document directly to PDF."""

    surface = build_sentinel_surface(inputs)
    packaged_direct_pdf_assets().register_fonts(surface)
    plan = build_sentinel_kit_index_direct_plan(surface, inputs)
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


def build_sentinel_kit_index_direct_plan(
    surface: PdfSurface,
    inputs: RenderInputs,
) -> SentinelKitIndexDirectPlan:
    """Build measured direct-PDF plans and render proof for Sentinel kit-index inputs."""

    _validate_inputs(inputs)
    context = build_sentinel_shell_context(inputs, doc_type=DOC_TYPE_KIT_INDEX)
    pages = _paginate_inventory_rows(
        _inventory_rows(inputs.context),
        page_layout=context.page_layout,
    )
    page_plans = tuple(
        _build_page(surface, context, page, total_pages=len(pages)) for page in pages
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
    return SentinelKitIndexDirectPlan(page_plans=page_plans, artifact_proof=artifact_proof)


def _validate_inputs(inputs: RenderInputs) -> None:
    normalized_doc_type = inputs.doc_type.strip().lower()
    if normalized_doc_type != DOC_TYPE_KIT_INDEX:
        raise ValueError("direct Sentinel kit-index renderer only supports kit-index documents")
    if inputs.render_qr:
        raise ValueError("direct Sentinel kit-index renderer does not render QR codes")
    if inputs.render_fallback:
        raise ValueError("direct Sentinel kit-index renderer does not render fallback text")

    resolve_page_geometry(inputs)


def _inventory_rows(context: Mapping[str, object]) -> tuple[_InventoryRow, ...]:
    rows = context.get("inventory_rows")
    resolved: list[_InventoryRow] = []
    if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes)):
        for item in rows:
            if not isinstance(item, Mapping):
                continue
            component_id = str(item.get("component_id") or "").strip()
            detail = str(item.get("detail") or "").strip()
            if component_id:
                resolved.append(_InventoryRow(component_id=component_id, detail=detail))
    if resolved:
        return tuple(resolved)

    qr_page_count = _positive_int(context.get("kit_qr_page_count"), default=0)
    if qr_page_count <= 0:
        return (_InventoryRow(component_id="KIT-PAGE-01", detail="No QR chunks"),)
    return tuple(
        _InventoryRow(component_id=f"KIT-PAGE-{index + 1:02d}", detail=f"KIT {index + 1:02d}")
        for index in range(qr_page_count)
    )


def _paginate_inventory_rows(
    rows: Sequence[_InventoryRow],
    *,
    page_layout: SentinelPageLayout,
) -> tuple[_InventoryPage, ...]:
    row_tuple = tuple(rows)
    if not row_tuple:
        return (_InventoryPage(page_number=1, rows=()),)
    pages: list[_InventoryPage] = []
    cursor = 0
    page_number = 1
    capacity = _inventory_capacity(page_layout)
    while cursor < len(row_tuple):
        page_rows = row_tuple[cursor : cursor + capacity]
        pages.append(_InventoryPage(page_number=page_number, rows=page_rows))
        cursor += len(page_rows)
        page_number += 1
    return tuple(pages)


def _inventory_capacity(page_layout: SentinelPageLayout) -> int:
    table_rect = page_layout.map_rect(_INVENTORY_TABLE_RECT)
    header_bottom = page_layout.map_y(_INVENTORY_TABLE_RECT.y_mm + 9.0)
    body_rect = PdfRect(
        table_rect.x_mm,
        header_bottom,
        table_rect.width_mm,
        table_rect.bottom_mm - header_bottom,
    )
    return resolve_grid(
        body_rect,
        GridPolicy(
            max_columns=1,
            max_rows=_MAX_INVENTORY_ROWS,
            preferred_item_width_mm=body_rect.width_mm,
            preferred_item_height_mm=17.1,
            minimum_item_width_mm=body_rect.width_mm,
            minimum_item_height_mm=_MIN_INVENTORY_ROW_HEIGHT_MM,
        ),
    ).capacity


def _build_page(
    surface: PdfSurface,
    context: SentinelShellContext,
    page: _InventoryPage,
    *,
    total_pages: int,
) -> DirectPdfPagePlan:
    page_label = f"Page {page.page_number} / {total_pages}"
    prefix = component_prefix(_COMPONENT_BASE, page.page_number)
    plans: list[PaintPlan] = []
    plans.extend(
        build_sentinel_header_plans(
            surface,
            context,
            page_label=page_label,
            page_number=page.page_number,
            component_base=_COMPONENT_BASE,
            top_strip_text="Custody Log // Offline Record // Authorized Personnel Only",
            title_default="Recovery Kit Index",
            subtitle_default="Inventory + Custody Log",
        )
    )
    plans.extend(_stats_plans(surface, context, prefix=prefix))
    plans.extend(_warning_plans(surface, context, prefix=prefix))
    plans.extend(_inventory_plans(surface, context, page.rows, prefix=prefix))
    plans.extend(_custody_plans(surface, context, prefix=prefix))
    plans.extend(
        build_sentinel_footer_plans(
            surface,
            context,
            page_label=page_label,
            page_number=page.page_number,
            component_base=_COMPONENT_BASE,
        )
    )
    return build_sentinel_page_plan(
        page_number=page.page_number,
        page_layout=context.page_layout,
        plans=plans,
    )


def _stats_plans(
    surface: PdfSurface,
    context: SentinelShellContext,
    *,
    prefix: str,
) -> list[PaintPlan]:
    layout = SENTINEL_THEME.layout
    values = (
        ("QR PAGES", str(_positive_int(context.values.get("kit_qr_page_count"), default=0))),
        ("QR CHUNKS", str(_positive_int(context.values.get("kit_qr_chunk_count"), default=0))),
        ("GENERATED (UTC)", context.created_timestamp_utc),
    )
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-stats-band",
            stroke=None,
            fill=SENTINEL_WHITE,
            line_width_mm=0.2,
        ).plan(surface, PdfRect(0.0, 27.9, layout.page_width_mm, 22.1)),
        Rule(
            component_id=f"{prefix}-stats-bottom-rule",
            color=SENTINEL_BORDER,
        ).plan(surface, PdfRect(0.0, 49.9, layout.page_width_mm, 0.25)),
    ]
    for index, (label, value) in enumerate(values):
        x_mm = index * 70.0
        if index:
            plans.append(
                Rule(
                    component_id=f"{prefix}-stats-divider-{index}",
                    color=SENTINEL_BORDER,
                ).plan(surface, PdfRect(x_mm, 27.9, 0.18, 22.1))
            )
        plans.append(
            TextBox(
                component_id=f"{prefix}-stats-label-{index}",
                text=label,
                style=SENTINEL_THEME.sans_style(size_pt=8.8, bold=True, color=SENTINEL_TEXT),
                policy=TextFitPolicy.SHRINK,
                min_size_pt=6.0,
                align=TextAlign.CENTER,
            ).plan(surface, PdfRect(x_mm + 6.0, 33.1, 58.0, 4.5))
        )
        value_style = (
            SENTINEL_THEME.mono_style(size_pt=12.0, color=SENTINEL_BLACK)
            if index == 2
            else SENTINEL_THEME.sans_style(size_pt=19.0, bold=True, color=SENTINEL_BLACK)
        )
        plans.append(
            TextBox(
                component_id=f"{prefix}-stats-value-{index}",
                text=value,
                style=value_style,
                policy=TextFitPolicy.SHRINK,
                min_size_pt=8.0,
                align=TextAlign.CENTER,
                line_height_multiplier=1.0,
            ).plan(surface, PdfRect(x_mm + 6.0, 39.4, 58.0, 7.0))
        )
    return plans


def _warning_plans(
    surface: PdfSurface,
    context: SentinelShellContext,
    *,
    prefix: str,
) -> list[PaintPlan]:
    rect = PdfRect(15.5, 56.7, 179.0, 18.2)
    return [
        Panel(
            component_id=f"{prefix}-warning-panel",
            stroke=None,
            fill=PdfColor(255, 248, 235),
            line_width_mm=0.2,
        ).plan(surface, rect),
        Rule(
            component_id=f"{prefix}-warning-accent",
            color=SENTINEL_ORANGE,
        ).plan(surface, PdfRect(rect.x_mm, rect.y_mm, 0.9, rect.height_mm)),
        TextBox(
            component_id=f"{prefix}-warning-icon",
            text=_ICON_WARNING,
            style=SENTINEL_THEME.symbol_style(size_pt=18.0, color=SENTINEL_ORANGE),
            policy=TextFitPolicy.FAIL,
            line_height_multiplier=1.0,
        ).plan(surface, PdfRect(rect.x_mm + 4.5, rect.y_mm + 5.0, 7.5, 7.5)),
        TextBox(
            component_id=f"{prefix}-warning-title",
            text=str(context.copy.get("warning_title") or "Critical Security Warning").upper(),
            style=SENTINEL_THEME.sans_style(size_pt=11.2, bold=True, color=SENTINEL_BLACK),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=8.0,
            line_height_multiplier=1.0,
        ).plan(surface, PdfRect(rect.x_mm + 14.0, rect.y_mm + 3.8, 95.0, 5.0)),
        TextBox(
            component_id=f"{prefix}-warning-body",
            text=str(context.copy.get("warning_body") or ""),
            style=SENTINEL_THEME.sans_style(size_pt=10.0, color=SENTINEL_TEXT),
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=1.12,
        ).plan(surface, PdfRect(rect.x_mm + 14.0, rect.y_mm + 9.2, 155.0, 8.8)),
    ]


def _inventory_plans(
    surface: PdfSurface,
    context: SentinelShellContext,
    rows: Sequence[_InventoryRow],
    *,
    prefix: str,
) -> list[PaintPlan]:
    title_y = 80.2
    plans: list[PaintPlan] = [
        *_small_box_icon_plans(surface, prefix=prefix, name="inventory-icon", x_mm=15.8, y_mm=81.4),
        TextBox(
            component_id=f"{prefix}-inventory-title",
            text=str(context.copy.get("hardware_inventory_label") or "Hardware Inventory").upper(),
            style=SENTINEL_THEME.sans_style(size_pt=15.0, bold=True, color=SENTINEL_BLACK),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=10.0,
            line_height_multiplier=1.0,
        ).plan(surface, PdfRect(23.5, title_y, 95.0, 7.0)),
        Panel(
            component_id=f"{prefix}-inventory-table",
            stroke=SENTINEL_BORDER,
            fill=SENTINEL_WHITE,
            line_width_mm=0.2,
        ).plan(surface, _INVENTORY_TABLE_RECT),
        Panel(
            component_id=f"{prefix}-inventory-header",
            stroke=None,
            fill=SENTINEL_BACKGROUND,
            line_width_mm=0.2,
        ).plan(
            surface,
            PdfRect(
                _INVENTORY_TABLE_RECT.x_mm,
                _INVENTORY_TABLE_RECT.y_mm,
                _INVENTORY_TABLE_RECT.width_mm,
                9.0,
            ),
        ),
        Rule(
            component_id=f"{prefix}-inventory-header-rule",
            color=SENTINEL_BORDER,
        ).plan(
            surface,
            PdfRect(_INVENTORY_TABLE_RECT.x_mm, _INVENTORY_TABLE_RECT.y_mm + 9.0, 179.0, 0.2),
        ),
    ]
    header_y = _INVENTORY_TABLE_RECT.y_mm + 3.0
    headers = (
        ("COMPONENT ID", 18.5, 64.0, TextAlign.LEFT),
        ("DESIGNATED CUSTODIAN", 85.0, 55.0, TextAlign.LEFT),
        ("STORAGE LOCATION", 146.0, 45.0, TextAlign.LEFT),
    )
    for label, x_mm, width_mm, align in headers:
        plans.append(
            TextBox(
                component_id=f"{prefix}-inventory-header-{label.lower().replace(' ', '-')}",
                text=label,
                style=SENTINEL_THEME.sans_style(size_pt=8.8, bold=True, color=SENTINEL_TEXT),
                policy=TextFitPolicy.SHRINK,
                min_size_pt=6.0,
                align=align,
            ).plan(surface, PdfRect(x_mm, header_y, width_mm, 4.0))
        )
    row_height = 17.1
    row_y = _INVENTORY_TABLE_RECT.y_mm + 9.0
    if not rows:
        plans.append(
            TextBox(
                component_id=f"{prefix}-inventory-empty",
                text="No inventory entries.",
                style=SENTINEL_THEME.sans_style(size_pt=9.0, color=SENTINEL_MUTED),
                policy=TextFitPolicy.SHRINK,
                min_size_pt=7.0,
            ).plan(surface, PdfRect(18.5, row_y + 4.0, 100.0, 4.5))
        )
        return plans
    for index, row in enumerate(rows):
        current_y = row_y + index * row_height
        if index:
            plans.append(
                Rule(
                    component_id=f"{prefix}-inventory-row-rule-{index}",
                    color=SENTINEL_BORDER,
                ).plan(surface, PdfRect(_INVENTORY_TABLE_RECT.x_mm, current_y, 179.0, 0.18))
            )
        plans.extend(
            _inventory_row_plans(
                surface,
                prefix=prefix,
                row=row,
                index=index,
                y_mm=current_y,
            )
        )
    return plans


def _inventory_row_plans(
    surface: PdfSurface,
    *,
    prefix: str,
    row: _InventoryRow,
    index: int,
    y_mm: float,
) -> list[PaintPlan]:
    return [
        TextBox(
            component_id=f"{prefix}-inventory-component-{index}",
            text=row.component_id,
            style=SENTINEL_THEME.mono_style(size_pt=9.0, bold=True, color=SENTINEL_BLACK),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.5,
        ).plan(surface, PdfRect(18.5, y_mm + 4.1, 58.0, 4.5)),
        TextBox(
            component_id=f"{prefix}-inventory-detail-{index}",
            text=row.detail,
            style=SENTINEL_THEME.mono_style(size_pt=6.4, color=SENTINEL_MUTED),
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=1.05,
        ).plan(surface, PdfRect(18.5, y_mm + 8.6, 58.0, 7.8)),
        *_dash_line_plans(
            surface,
            prefix=prefix,
            name=f"inventory-custodian-{index}",
            x_mm=85.0,
            y_mm=y_mm + 11.7,
            width_mm=55.0,
        ),
        *_dash_line_plans(
            surface,
            prefix=prefix,
            name=f"inventory-location-{index}",
            x_mm=146.0,
            y_mm=y_mm + 11.7,
            width_mm=45.0,
        ),
    ]


def _custody_plans(
    surface: PdfSurface,
    context: SentinelShellContext,
    *,
    prefix: str,
) -> list[PaintPlan]:
    plans: list[PaintPlan] = [
        *_small_pen_icon_plans(surface, prefix=prefix, x_mm=15.8, y_mm=159.4),
        TextBox(
            component_id=f"{prefix}-custody-title",
            text=str(context.copy.get("chain_of_custody_label") or "Chain of Custody").upper(),
            style=SENTINEL_THEME.sans_style(size_pt=15.0, bold=True, color=SENTINEL_BLACK),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=10.0,
            line_height_multiplier=1.0,
        ).plan(surface, PdfRect(23.5, 158.2, 95.0, 7.0)),
        Panel(
            component_id=f"{prefix}-custody-table",
            stroke=SENTINEL_BORDER,
            fill=SENTINEL_WHITE,
            line_width_mm=0.2,
        ).plan(surface, _CUSTODY_TABLE_RECT),
        Panel(
            component_id=f"{prefix}-custody-header",
            stroke=None,
            fill=SENTINEL_BACKGROUND,
            line_width_mm=0.2,
        ).plan(
            surface,
            PdfRect(
                _CUSTODY_TABLE_RECT.x_mm,
                _CUSTODY_TABLE_RECT.y_mm,
                _CUSTODY_TABLE_RECT.width_mm,
                11.0,
            ),
        ),
        Rule(
            component_id=f"{prefix}-custody-header-rule",
            color=SENTINEL_BORDER,
        ).plan(
            surface,
            PdfRect(_CUSTODY_TABLE_RECT.x_mm, _CUSTODY_TABLE_RECT.y_mm + 11.0, 179.0, 0.2),
        ),
    ]
    headers = (
        ("DATE", 20.0, 33.0, TextAlign.LEFT),
        ("PERSON", 57.0, 40.0, TextAlign.LEFT),
        ("ACTION / NOTES", 102.0, 58.0, TextAlign.LEFT),
        ("SIGNATURE", 163.0, 27.0, TextAlign.RIGHT),
    )
    for label, x_mm, width_mm, align in headers:
        plans.append(
            _custody_header_plan(
                surface,
                prefix=prefix,
                label=label,
                x_mm=x_mm,
                width_mm=width_mm,
                align=align,
            )
        )
    plans.extend(_custody_grid_plans(surface, prefix=prefix))
    return plans


def _custody_header_plan(
    surface: PdfSurface,
    *,
    prefix: str,
    label: str,
    x_mm: float,
    width_mm: float,
    align: TextAlign,
) -> PaintPlan:
    component_label = label.lower().replace(" / ", "-").replace(" ", "-")
    return TextBox(
        component_id=f"{prefix}-custody-header-{component_label}",
        text=label,
        style=SENTINEL_THEME.sans_style(size_pt=8.8, bold=True, color=SENTINEL_TEXT),
        policy=TextFitPolicy.SHRINK,
        min_size_pt=6.0,
        align=align,
    ).plan(surface, PdfRect(x_mm, _CUSTODY_TABLE_RECT.y_mm + 3.7, width_mm, 4.0))


def _custody_grid_plans(surface: PdfSurface, *, prefix: str) -> list[PaintPlan]:
    plans: list[PaintPlan] = []
    body_y = _CUSTODY_TABLE_RECT.y_mm + 11.0
    body_height = _CUSTODY_TABLE_RECT.height_mm - 11.0
    row_height = body_height / 7.0
    for index in range(1, 7):
        y_mm = body_y + index * row_height
        plans.append(
            Rule(
                component_id=f"{prefix}-custody-row-rule-{index}",
                color=SENTINEL_BORDER,
            ).plan(surface, PdfRect(_CUSTODY_TABLE_RECT.x_mm, y_mm, 179.0, 0.16))
        )
    for index, x_mm in enumerate((52.5, 97.5, 149.5)):
        plans.extend(
            _vertical_dash_line_plans(
                surface,
                prefix=prefix,
                name=f"custody-col-{index}",
                x_mm=x_mm,
                y_mm=body_y,
                height_mm=body_height,
            )
        )
    return plans


def _small_box_icon_plans(
    surface: PdfSurface,
    *,
    prefix: str,
    name: str,
    x_mm: float,
    y_mm: float,
) -> list[PaintPlan]:
    return [
        Panel(
            component_id=f"{prefix}-{name}-outer",
            stroke=SENTINEL_BLACK,
            fill=None,
            line_width_mm=0.55,
        ).plan(surface, PdfRect(x_mm, y_mm, 4.6, 4.9)),
        Rule(component_id=f"{prefix}-{name}-lid", color=SENTINEL_BLACK).plan(
            surface, PdfRect(x_mm - 0.4, y_mm - 0.7, 5.4, 0.55)
        ),
        Rule(component_id=f"{prefix}-{name}-slot", color=SENTINEL_BLACK).plan(
            surface, PdfRect(x_mm + 1.0, y_mm + 1.2, 2.5, 0.45)
        ),
    ]


def _small_pen_icon_plans(
    surface: PdfSurface,
    *,
    prefix: str,
    x_mm: float,
    y_mm: float,
) -> list[PaintPlan]:
    return [
        Line(
            component_id=f"{prefix}-custody-icon-pen",
            color=SENTINEL_BLACK,
            line_width_mm=0.55,
        ).plan(
            surface,
            start_x_mm=x_mm,
            start_y_mm=y_mm + 1.0,
            end_x_mm=x_mm + 4.4,
            end_y_mm=y_mm + 5.2,
        ),
        Panel(
            component_id=f"{prefix}-custody-icon-box",
            stroke=SENTINEL_BLACK,
            fill=None,
            line_width_mm=0.5,
        ).plan(surface, PdfRect(x_mm + 0.4, y_mm + 1.6, 4.2, 3.8)),
    ]


def _dash_line_plans(
    surface: PdfSurface,
    *,
    prefix: str,
    name: str,
    x_mm: float,
    y_mm: float,
    width_mm: float,
) -> list[PaintPlan]:
    plans: list[PaintPlan] = []
    cursor = 0.0
    index = 0
    while cursor < width_mm:
        dash_end = min(cursor + 1.8, width_mm)
        plans.append(
            Line(
                component_id=f"{prefix}-{name}-dash-{index}",
                color=_DASH_COLOR,
                line_width_mm=0.18,
            ).plan(
                surface,
                start_x_mm=x_mm + cursor,
                start_y_mm=y_mm,
                end_x_mm=x_mm + dash_end,
                end_y_mm=y_mm,
            )
        )
        cursor += 3.0
        index += 1
    return plans


def _vertical_dash_line_plans(
    surface: PdfSurface,
    *,
    prefix: str,
    name: str,
    x_mm: float,
    y_mm: float,
    height_mm: float,
) -> list[PaintPlan]:
    plans: list[PaintPlan] = []
    cursor = 0.0
    index = 0
    while cursor < height_mm:
        dash_end = min(cursor + 1.8, height_mm)
        plans.append(
            Line(
                component_id=f"{prefix}-{name}-dash-{index}",
                color=_DASH_COLOR,
                line_width_mm=0.18,
            ).plan(
                surface,
                start_x_mm=x_mm,
                start_y_mm=y_mm + cursor,
                end_x_mm=x_mm,
                end_y_mm=y_mm + dash_end,
            )
        )
        cursor += 3.0
        index += 1
    return plans


def _positive_int(value: object, *, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(0, value)


__all__ = [
    "SentinelKitIndexDirectPlan",
    "build_sentinel_kit_index_direct_plan",
    "render_sentinel_kit_index_direct_pdf",
]
