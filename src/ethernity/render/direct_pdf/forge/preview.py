"""Forge-style direct PDF preview page for renderer migration spikes.

This module is intentionally narrow: it is not the production renderer. It is a visual tracer that
proves the direct-PDF primitives can preserve the current Forge design language without routing
through HTML, CSS, or a browser renderer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ethernity.qr.codec import qr_bytes
from ethernity.render.direct_pdf.assets import (
    MATERIAL_SYMBOLS_FAMILY,
    packaged_direct_pdf_assets,
)
from ethernity.render.direct_pdf.components import (
    ImageBox,
    Panel,
    Rule,
    TextAlign,
    TextBox,
)
from ethernity.render.direct_pdf.page import (
    ComponentGroup,
    DirectPdfPagePlan,
    PaintPlan,
    SeparationConstraint,
    build_page_plan,
)
from ethernity.render.direct_pdf.page_geometry import A4_HEIGHT_MM, A4_WIDTH_MM, PageGeometry
from ethernity.render.direct_pdf.responsive_layout import Insets, PageRegions, resolve_page_regions
from ethernity.render.direct_pdf.surface import FpdfSurface, PdfSurface
from ethernity.render.direct_pdf.text_fit import TextFitPolicy
from ethernity.render.direct_pdf.types import PdfColor, PdfRect, TextStyle

_DEFAULT_PAGE_GEOMETRY = PageGeometry("A4", A4_WIDTH_MM, A4_HEIGHT_MM)
_SAFE_MARGIN_MM = 15.0
_HEADER_HEIGHT_MM = 41.4
_HEADER_BODY_GAP_MM = 8.6
_FOOTER_HEIGHT_MM = 20.0
_BODY_FOOTER_GAP_MM = 20.0
_MINIMUM_SAFE_WIDTH_MM = 180.0
_MINIMUM_FALLBACK_HEIGHT_MM = 40.0
_SLATE_50 = PdfColor(248, 250, 252)
_SLATE_100 = PdfColor(241, 245, 249)
_SLATE_300 = PdfColor(203, 213, 225)
_SLATE_500 = PdfColor(100, 116, 139)
_SLATE_600 = PdfColor(71, 85, 105)
_SLATE_800 = PdfColor(30, 41, 59)
_SLATE_900 = PdfColor(15, 23, 42)
_ICON_TOKEN = chr(0xEA25)
_ICON_WARNING = chr(0xE002)


@dataclass(frozen=True)
class ForgePreviewResult:
    """Result of rendering a Forge-style direct-PDF preview page."""

    page_plan: DirectPdfPagePlan


@dataclass(frozen=True)
class _ForgePreviewGeometry:
    page: PageGeometry
    regions: PageRegions


def _forge_preview_geometry(page: PageGeometry) -> _ForgePreviewGeometry:
    if page.height_mm <= page.width_mm:
        raise ValueError("Forge preview requires portrait page geometry")
    regions = resolve_page_regions(
        page.rect,
        safe_insets=Insets.uniform(_SAFE_MARGIN_MM),
        header_height_mm=_HEADER_HEIGHT_MM,
        footer_height_mm=_FOOTER_HEIGHT_MM,
        header_body_gap_mm=_HEADER_BODY_GAP_MM,
        body_footer_gap_mm=_BODY_FOOTER_GAP_MM,
    )
    if regions.safe.width_mm < _MINIMUM_SAFE_WIDTH_MM:
        raise ValueError(
            "Forge preview page is too narrow for legible content: "
            f"{regions.safe.width_mm:.3f} < {_MINIMUM_SAFE_WIDTH_MM:.3f} mm"
        )
    fallback_top_mm = regions.body.y_mm + 95.0
    if regions.body.bottom_mm - fallback_top_mm < _MINIMUM_FALLBACK_HEIGHT_MM:
        raise ValueError("Forge preview page is too short for the fallback payload panel")
    return _ForgePreviewGeometry(page=page, regions=regions)


def render_forge_recovery_preview(
    output_path: str | Path,
    *,
    geometry: PageGeometry | None = None,
) -> ForgePreviewResult:
    """Render a one-page Forge-style recovery preview directly to PDF."""

    resolved_geometry = geometry or _DEFAULT_PAGE_GEOMETRY
    surface = FpdfSurface(
        page_width_mm=resolved_geometry.width_mm,
        page_height_mm=resolved_geometry.height_mm,
    )
    packaged_direct_pdf_assets().register_fonts(surface)
    page_plan = build_forge_recovery_preview_page(surface, geometry=resolved_geometry)
    page_plan.paint(surface)
    surface.output(output_path)
    return ForgePreviewResult(page_plan=page_plan)


def build_forge_recovery_preview_page(
    surface: PdfSurface,
    *,
    geometry: PageGeometry | None = None,
) -> DirectPdfPagePlan:
    """Build a measured Forge-style recovery preview page."""

    preview = _forge_preview_geometry(geometry or _DEFAULT_PAGE_GEOMETRY)
    page = preview.page
    regions = preview.regions
    safe = regions.safe
    left_mm = safe.x_mm
    right_mm = safe.right_mm
    body_top_mm = regions.body.y_mm
    fallback_top_mm = body_top_mm + 95.0
    fallback_height_mm = regions.body.bottom_mm - fallback_top_mm
    footer_top_mm = regions.footer.y_mm

    body_style = TextStyle(family="Helvetica", size_pt=8.5, color=_SLATE_800)
    meta_style = TextStyle(family="Courier", size_pt=7.2, color=_SLATE_600)
    label_style = TextStyle(family="Helvetica", size_pt=7.0, style="B", color=_SLATE_500)
    title_style = TextStyle(family="Helvetica", size_pt=22.0, style="B", color=_SLATE_900)
    subtitle_style = TextStyle(family="Helvetica", size_pt=9.0, color=_SLATE_600)
    mono_style = TextStyle(family="Courier", size_pt=7.0, color=_SLATE_600)
    icon_style = TextStyle(family=MATERIAL_SYMBOLS_FAMILY, size_pt=18.0, color=_SLATE_900)

    plans: list[PaintPlan] = [
        Panel(
            component_id="forge-page-border",
            stroke=_SLATE_300,
            line_width_mm=0.2,
        ).plan(surface, safe),
        TextBox(
            component_id="forge-header-class",
            text="THE FORGE // SECURE OFFLINE STORAGE",
            style=label_style,
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(left_mm, safe.y_mm + 4.0, 95.0, 8.0)),
        TextBox(
            component_id="forge-header-title",
            text="Recovery Document",
            style=title_style,
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(left_mm, safe.y_mm + 13.0, 96.0, 14.0)),
        TextBox(
            component_id="forge-header-subtitle",
            text="Keys + Text Fallback",
            style=subtitle_style,
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(left_mm, safe.y_mm + 28.0, 100.0, 8.0)),
        Panel(
            component_id="forge-icon-box",
            stroke=_SLATE_900,
            fill=_SLATE_50,
            line_width_mm=0.25,
        ).plan(surface, PdfRect(right_mm - 63.0, safe.y_mm + 8.0, 14.0, 14.0)),
        TextBox(
            component_id="forge-header-icon",
            text=_ICON_TOKEN,
            style=icon_style,
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.CENTER,
            min_size_pt=8,
        ).plan(surface, PdfRect(right_mm - 63.0, safe.y_mm + 8.5, 14.0, 13.0)),
        Panel(
            component_id="forge-classification-pill",
            stroke=_SLATE_900,
            fill=_SLATE_50,
            line_width_mm=0.2,
        ).plan(surface, PdfRect(right_mm - 45.0, safe.y_mm + 7.0, 45.0, 7.0)),
        TextBox(
            component_id="forge-classification-text",
            text="MANUAL ENTRY ONLY",
            style=TextStyle(family="Courier", size_pt=6.2, style="B", color=_SLATE_900),
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.CENTER,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(right_mm - 44.0, safe.y_mm + 8.0, 43.0, 5.0)),
        TextBox(
            component_id="forge-header-doc-id",
            text="DOC ID: 0123456789ABCDEF",
            style=meta_style,
            policy=TextFitPolicy.FAIL,
            align=TextAlign.RIGHT,
        ).plan(surface, PdfRect(right_mm - 77.0, safe.y_mm + 17.0, 77.0, 6.0)),
        TextBox(
            component_id="forge-header-generated",
            text="GENERATED (UTC): 2026-07-06 00:00 UTC",
            style=meta_style,
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.RIGHT,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(right_mm - 77.0, safe.y_mm + 24.0, 77.0, 6.0)),
        Rule(
            component_id="forge-heavy-header-rule",
            color=_SLATE_900,
        ).plan(surface, PdfRect(left_mm, safe.y_mm + 40.0, safe.width_mm, 1.4)),
        Panel(
            component_id="forge-warning-panel",
            stroke=_SLATE_300,
            fill=_SLATE_100,
            line_width_mm=0.25,
        ).plan(surface, PdfRect(left_mm, body_top_mm, safe.width_mm, 24.0)),
        TextBox(
            component_id="forge-warning-icon",
            text=_ICON_WARNING,
            style=TextStyle(family=MATERIAL_SYMBOLS_FAMILY, size_pt=14, color=_SLATE_900),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=8,
        ).plan(surface, PdfRect(left_mm + 5.0, body_top_mm + 5.0, 17.0, 8.0)),
        TextBox(
            component_id="forge-warning-title",
            text="Print and store this document offline",
            style=TextStyle(family="Helvetica", size_pt=8.0, style="B", color=_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(left_mm + 23.0, body_top_mm + 3.0, 125.0, 6.0)),
        TextBox(
            component_id="forge-warning-body",
            text=(
                "This preview exercises the Forge visual shell through measured direct PDF "
                "components instead of browser layout."
            ),
            style=body_style,
            policy=TextFitPolicy.WRAP,
        ).plan(
            surface,
            PdfRect(left_mm + 23.0, body_top_mm + 10.0, safe.width_mm - 34.0, 11.0),
        ),
        TextBox(
            component_id="forge-instructions-title",
            text="Instructions",
            style=TextStyle(family="Helvetica", size_pt=9.0, style="B", color=_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(left_mm + 2.0, body_top_mm + 36.0, 45.0, 7.0)),
        Rule(
            component_id="forge-instructions-title-rule",
            color=_SLATE_900,
        ).plan(surface, PdfRect(left_mm + 2.0, body_top_mm + 44.0, 28.0, 0.35)),
        TextBox(
            component_id="forge-instructions-body",
            text=(
                "1. Keep this document separate from the main QR carrier.\n"
                "2. Use fallback text only when scanning fails.\n"
                "3. Verify every copied line before recovery."
            ),
            style=body_style,
            policy=TextFitPolicy.WRAP,
        ).plan(surface, PdfRect(left_mm + 2.0, body_top_mm + 51.0, 88.0, 31.0)),
        ImageBox(
            component_id="forge-preview-qr",
            image=qr_bytes("forge-direct-pdf-preview", scale=3),
            image_type="PNG",
        ).plan(surface, PdfRect(right_mm - 58.0, body_top_mm + 39.0, 42.0, 42.0)),
        Panel(
            component_id="forge-fallback-panel",
            stroke=_SLATE_300,
            fill=_SLATE_50,
            line_width_mm=0.2,
        ).plan(surface, PdfRect(left_mm, fallback_top_mm, safe.width_mm, fallback_height_mm)),
        TextBox(
            component_id="forge-fallback-title",
            text="Fallback Payload Lines",
            style=TextStyle(family="Helvetica", size_pt=8.0, style="B", color=_SLATE_600),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(left_mm + 5.0, fallback_top_mm + 6.0, 70.0, 6.0)),
        TextBox(
            component_id="forge-fallback-lines",
            text=(
                "AUTH 0001 FJ3D 8KQ2 Q4KX FJ3D 8KQ2 Q4KX\n"
                "MAIN 0002 T6YH P9NC B7RM T6YH P9NC B7RM\n"
                "MAIN 0003 Z2KD R5MA H8YP Z2KD R5MA H8YP"
            ),
            style=TextStyle(family="Courier", size_pt=8.0, color=_SLATE_800),
            policy=TextFitPolicy.FAIL,
        ).plan(
            surface,
            PdfRect(left_mm + 5.0, fallback_top_mm + 18.0, safe.width_mm - 30.0, 22.0),
        ),
        Rule(
            component_id="forge-footer-rule",
            color=_SLATE_300,
        ).plan(surface, PdfRect(left_mm, footer_top_mm, safe.width_mm, 0.35)),
        TextBox(
            component_id="forge-footer-left",
            text="ETHERNITY DIRECT PDF PREVIEW",
            style=mono_style,
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(left_mm, footer_top_mm + 6.0, 80.0, 6.0)),
        TextBox(
            component_id="forge-footer-page",
            text="PAGE 1 / 1",
            style=mono_style,
            policy=TextFitPolicy.FAIL,
            align=TextAlign.CENTER,
        ).plan(
            surface,
            PdfRect((page.width_mm - 32.0) / 2.0, footer_top_mm + 6.0, 32.0, 6.0),
        ),
    ]
    constraints = (
        SeparationConstraint(
            constraint_id="forge-preview-warning-after-header",
            first=ComponentGroup(
                group_id="forge-preview-header-boundary",
                component_ids=("forge-heavy-header-rule",),
            ),
            second=ComponentGroup(
                group_id="forge-preview-warning",
                component_ids=("forge-warning-panel",),
            ),
            minimum_clearance_mm=8.0,
        ),
        SeparationConstraint(
            constraint_id="forge-preview-instructions-after-warning",
            first=ComponentGroup(
                group_id="forge-preview-warning-boundary",
                component_ids=("forge-warning-panel",),
            ),
            second=ComponentGroup(
                group_id="forge-preview-instructions",
                component_ids=("forge-instructions-title", "forge-preview-qr"),
            ),
            minimum_clearance_mm=10.0,
        ),
        SeparationConstraint(
            constraint_id="forge-preview-fallback-after-instructions",
            first=ComponentGroup(
                group_id="forge-preview-instruction-content",
                component_ids=("forge-instructions-body", "forge-preview-qr"),
            ),
            second=ComponentGroup(
                group_id="forge-preview-fallback",
                component_ids=("forge-fallback-panel",),
            ),
            minimum_clearance_mm=13.0,
        ),
        SeparationConstraint(
            constraint_id="forge-preview-footer-after-fallback",
            first=ComponentGroup(
                group_id="forge-preview-fallback-boundary",
                component_ids=("forge-fallback-panel",),
            ),
            second=ComponentGroup(
                group_id="forge-preview-footer-boundary",
                component_ids=("forge-footer-rule",),
            ),
            minimum_clearance_mm=20.0,
        ),
    )
    return build_page_plan(
        page_number=1,
        rect=page.rect,
        plans=plans,
        separation_constraints=constraints,
    )


__all__ = [
    "A4_HEIGHT_MM",
    "A4_WIDTH_MM",
    "ForgePreviewResult",
    "build_forge_recovery_preview_page",
    "render_forge_recovery_preview",
]
