"""Forge design tokens for direct PDF rendering.

The HTML Forge templates use Tailwind utility classes with these reference families:
Libre Baskerville, Public Sans, Roboto Mono, and Material Symbols. The packaged HTML currently
bundles only Material Symbols, so the direct renderer maps text roles to stable PDF built-ins that
match the current rendered baselines instead of silently changing typography.
"""

from __future__ import annotations

from dataclasses import dataclass

from ethernity.render.direct_pdf.assets import MATERIAL_SYMBOLS_FAMILY
from ethernity.render.direct_pdf.types import PdfColor, TextStyle


@dataclass(frozen=True)
class ForgePalette:
    """Color tokens used by the Forge direct renderer."""

    slate_50: PdfColor
    slate_100: PdfColor
    slate_200: PdfColor
    slate_300: PdfColor
    slate_500: PdfColor
    slate_600: PdfColor
    slate_700: PdfColor
    slate_800: PdfColor
    slate_900: PdfColor
    white: PdfColor


@dataclass(frozen=True)
class ForgeFontRole:
    """One reference font role and the family registered with the PDF surface."""

    reference_family: str
    pdf_family: str


@dataclass(frozen=True)
class ForgeFonts:
    """Font roles from the Forge HTML templates mapped to direct-PDF families."""

    serif: ForgeFontRole
    sans: ForgeFontRole
    mono: ForgeFontRole
    symbols: ForgeFontRole


@dataclass(frozen=True)
class ForgeTextScale:
    """Named text styles that define Forge's visual hierarchy."""

    header_title_pt: float = 27.0
    header_subtitle_pt: float = 9.0
    header_meta_pt: float = 6.0
    section_title_pt: float = 12.0
    body_pt: float = 7.5
    body_small_pt: float = 6.4
    mono_body_pt: float = 6.2
    footer_pt: float = 5.8


@dataclass(frozen=True)
class ForgeLayoutScale:
    """Shared geometry tokens for Forge A4 pages."""

    page_width_mm: float = 210.0
    page_height_mm: float = 297.0
    content_x_mm: float = 15.0
    content_width_mm: float = 180.0
    content_top_mm: float = 15.0
    footer_rule_y_mm: float = 263.0


@dataclass(frozen=True)
class ForgeTheme:
    """Direct-PDF representation of the Forge design contract."""

    palette: ForgePalette
    fonts: ForgeFonts
    text: ForgeTextScale
    layout: ForgeLayoutScale
    omit_shard_watermark: bool = True

    def serif_style(self, *, size_pt: float, color: PdfColor, bold: bool = False) -> TextStyle:
        return TextStyle(
            family=self.fonts.serif.pdf_family,
            size_pt=size_pt,
            style="B" if bold else "",
            color=color,
        )

    def sans_style(self, *, size_pt: float, color: PdfColor, bold: bool = False) -> TextStyle:
        return TextStyle(
            family=self.fonts.sans.pdf_family,
            size_pt=size_pt,
            style="B" if bold else "",
            color=color,
        )

    def mono_style(self, *, size_pt: float, color: PdfColor, bold: bool = False) -> TextStyle:
        return TextStyle(
            family=self.fonts.mono.pdf_family,
            size_pt=size_pt,
            style="B" if bold else "",
            color=color,
        )

    def symbol_style(self, *, size_pt: float, color: PdfColor) -> TextStyle:
        return TextStyle(family=self.fonts.symbols.pdf_family, size_pt=size_pt, color=color)


FORGE_THEME = ForgeTheme(
    palette=ForgePalette(
        slate_50=PdfColor(248, 250, 252),
        slate_100=PdfColor(241, 245, 249),
        slate_200=PdfColor(226, 232, 240),
        slate_300=PdfColor(203, 213, 225),
        slate_500=PdfColor(100, 116, 139),
        slate_600=PdfColor(71, 85, 105),
        slate_700=PdfColor(51, 65, 85),
        slate_800=PdfColor(30, 41, 59),
        slate_900=PdfColor(15, 23, 42),
        white=PdfColor(255, 255, 255),
    ),
    fonts=ForgeFonts(
        serif=ForgeFontRole(reference_family="Libre Baskerville", pdf_family="Times"),
        sans=ForgeFontRole(reference_family="Public Sans", pdf_family="Helvetica"),
        mono=ForgeFontRole(reference_family="Roboto Mono", pdf_family="Courier"),
        symbols=ForgeFontRole(
            reference_family="Material Symbols Outlined",
            pdf_family=MATERIAL_SYMBOLS_FAMILY,
        ),
    ),
    text=ForgeTextScale(),
    layout=ForgeLayoutScale(),
)


__all__ = [
    "FORGE_THEME",
    "ForgeFontRole",
    "ForgeFonts",
    "ForgeLayoutScale",
    "ForgePalette",
    "ForgeTextScale",
    "ForgeTheme",
]
