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
from ethernity.render.direct_pdf.page import DirectPdfPagePlan, PaintPlan, build_page_plan
from ethernity.render.direct_pdf.surface import FpdfSurface, PdfSurface
from ethernity.render.direct_pdf.text_fit import TextFitPolicy
from ethernity.render.direct_pdf.types import PdfColor, PdfRect, TextStyle

A4_WIDTH_MM = 210.0
A4_HEIGHT_MM = 297.0

_PAGE_RECT = PdfRect(0.0, 0.0, A4_WIDTH_MM, A4_HEIGHT_MM)
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


def render_forge_recovery_preview(output_path: str | Path) -> ForgePreviewResult:
    """Render a one-page Forge-style recovery preview directly to PDF."""

    surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
    packaged_direct_pdf_assets().register_fonts(surface)
    page_plan = build_forge_recovery_preview_page(surface)
    page_plan.paint(surface)
    surface.output(output_path)
    return ForgePreviewResult(page_plan=page_plan)


def build_forge_recovery_preview_page(surface: PdfSurface) -> DirectPdfPagePlan:
    """Build a measured Forge-style recovery preview page."""

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
        ).plan(surface, PdfRect(15, 15, 180, 267)),
        TextBox(
            component_id="forge-header-class",
            text="THE FORGE // SECURE OFFLINE STORAGE",
            style=label_style,
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(15, 19, 95, 8)),
        TextBox(
            component_id="forge-header-title",
            text="Recovery Document",
            style=title_style,
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(15, 28, 96, 14)),
        TextBox(
            component_id="forge-header-subtitle",
            text="Keys + Text Fallback",
            style=subtitle_style,
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(15, 43, 100, 8)),
        Panel(
            component_id="forge-icon-box",
            stroke=_SLATE_900,
            fill=_SLATE_50,
            line_width_mm=0.25,
        ).plan(surface, PdfRect(132, 23, 14, 14)),
        TextBox(
            component_id="forge-header-icon",
            text=_ICON_TOKEN,
            style=icon_style,
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.CENTER,
            min_size_pt=8,
        ).plan(surface, PdfRect(132, 23.5, 14, 13)),
        Panel(
            component_id="forge-classification-pill",
            stroke=_SLATE_900,
            fill=_SLATE_50,
            line_width_mm=0.2,
        ).plan(surface, PdfRect(150, 22, 45, 7)),
        TextBox(
            component_id="forge-classification-text",
            text="MANUAL ENTRY ONLY",
            style=TextStyle(family="Courier", size_pt=6.2, style="B", color=_SLATE_900),
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.CENTER,
            min_size_pt=5.0,
        ).plan(surface, PdfRect(151, 23, 43, 5)),
        TextBox(
            component_id="forge-header-doc-id",
            text="DOC ID: 0123456789ABCDEF",
            style=meta_style,
            policy=TextFitPolicy.FAIL,
            align=TextAlign.RIGHT,
        ).plan(surface, PdfRect(118, 32, 77, 6)),
        TextBox(
            component_id="forge-header-generated",
            text="GENERATED (UTC): 2026-07-06 00:00 UTC",
            style=meta_style,
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.RIGHT,
            min_size_pt=5.5,
        ).plan(surface, PdfRect(118, 39, 77, 6)),
        Rule(
            component_id="forge-heavy-header-rule",
            color=_SLATE_900,
        ).plan(surface, PdfRect(15, 55, 180, 1.4)),
        Panel(
            component_id="forge-warning-panel",
            stroke=_SLATE_300,
            fill=_SLATE_100,
            line_width_mm=0.25,
        ).plan(surface, PdfRect(15, 65, 180, 24)),
        TextBox(
            component_id="forge-warning-icon",
            text=_ICON_WARNING,
            style=TextStyle(family=MATERIAL_SYMBOLS_FAMILY, size_pt=14, color=_SLATE_900),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=8,
        ).plan(surface, PdfRect(20, 70, 17, 8)),
        TextBox(
            component_id="forge-warning-title",
            text="Print and store this document offline",
            style=TextStyle(family="Helvetica", size_pt=8.0, style="B", color=_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(38, 68, 125, 6)),
        TextBox(
            component_id="forge-warning-body",
            text=(
                "This preview exercises the Forge visual shell through measured direct PDF "
                "components instead of browser layout."
            ),
            style=body_style,
            policy=TextFitPolicy.WRAP,
        ).plan(surface, PdfRect(38, 75, 146, 11)),
        TextBox(
            component_id="forge-instructions-title",
            text="Instructions",
            style=TextStyle(family="Helvetica", size_pt=9.0, style="B", color=_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(17, 101, 45, 7)),
        Rule(
            component_id="forge-instructions-title-rule",
            color=_SLATE_900,
        ).plan(surface, PdfRect(17, 109, 28, 0.35)),
        TextBox(
            component_id="forge-instructions-body",
            text=(
                "1. Keep this document separate from the main QR carrier.\n"
                "2. Use fallback text only when scanning fails.\n"
                "3. Verify every copied line before recovery."
            ),
            style=body_style,
            policy=TextFitPolicy.WRAP,
        ).plan(surface, PdfRect(17, 116, 88, 31)),
        ImageBox(
            component_id="forge-preview-qr",
            image=qr_bytes("forge-direct-pdf-preview", scale=3),
            image_type="PNG",
        ).plan(surface, PdfRect(137, 104, 42, 42)),
        Panel(
            component_id="forge-fallback-panel",
            stroke=_SLATE_300,
            fill=_SLATE_50,
            line_width_mm=0.2,
        ).plan(surface, PdfRect(15, 160, 180, 82)),
        TextBox(
            component_id="forge-fallback-title",
            text="Fallback Payload Lines",
            style=TextStyle(family="Helvetica", size_pt=8.0, style="B", color=_SLATE_600),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(20, 166, 70, 6)),
        TextBox(
            component_id="forge-fallback-lines",
            text=(
                "AUTH 0001 FJ3D 8KQ2 Q4KX FJ3D 8KQ2 Q4KX\n"
                "MAIN 0002 T6YH P9NC B7RM T6YH P9NC B7RM\n"
                "MAIN 0003 Z2KD R5MA H8YP Z2KD R5MA H8YP"
            ),
            style=TextStyle(family="Courier", size_pt=8.0, color=_SLATE_800),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(20, 178, 150, 22)),
        Rule(
            component_id="forge-footer-rule",
            color=_SLATE_300,
        ).plan(surface, PdfRect(15, 262, 180, 0.35)),
        TextBox(
            component_id="forge-footer-left",
            text="ETHERNITY DIRECT PDF PREVIEW",
            style=mono_style,
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(15, 268, 80, 6)),
        TextBox(
            component_id="forge-footer-page",
            text="PAGE 1 / 1",
            style=mono_style,
            policy=TextFitPolicy.FAIL,
            align=TextAlign.CENTER,
        ).plan(surface, PdfRect(89, 268, 32, 6)),
    ]
    return build_page_plan(page_number=1, rect=_PAGE_RECT, plans=plans)


__all__ = [
    "A4_HEIGHT_MM",
    "A4_WIDTH_MM",
    "ForgePreviewResult",
    "build_forge_recovery_preview_page",
    "render_forge_recovery_preview",
]
