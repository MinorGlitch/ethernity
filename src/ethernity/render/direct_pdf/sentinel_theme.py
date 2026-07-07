"""Sentinel design tokens for direct PDF rendering."""

from __future__ import annotations

from dataclasses import dataclass

from ethernity.render.direct_pdf.assets import (
    MATERIAL_SYMBOLS_FAMILY,
    PUBLIC_SANS_FAMILY,
    ROBOTO_MONO_FAMILY,
)
from ethernity.render.direct_pdf.types import PdfColor, TextStyle


@dataclass(frozen=True)
class SentinelPalette:
    """Color tokens used by Sentinel direct renderers."""

    primary: PdfColor
    background: PdfColor
    border: PdfColor
    text_main: PdfColor
    text_secondary: PdfColor
    black: PdfColor
    white: PdfColor
    warning_fill: PdfColor
    line_fill: PdfColor
    grid_line: PdfColor


@dataclass(frozen=True)
class SentinelFonts:
    """Font roles from the Sentinel HTML templates mapped to PDF families."""

    sans: str
    mono: str
    symbols: str


@dataclass(frozen=True)
class SentinelTextScale:
    """Shared Sentinel shell type sizes."""

    top_strip_pt: float
    top_strip_min_pt: float
    header_title_pt: float
    header_title_min_pt: float
    header_title_wrapped_pt: float
    header_title_wrapped_min_pt: float
    header_subtitle_pt: float
    header_subtitle_min_pt: float
    header_meta_pt: float
    header_meta_min_pt: float
    footer_pt: float
    footer_min_pt: float


@dataclass(frozen=True)
class SentinelLayoutScale:
    """Shared Sentinel page and shell geometry."""

    page_width_mm: float
    page_height_mm: float
    content_x_mm: float
    content_width_mm: float
    top_strip_height_mm: float
    top_strip_rule_height_mm: float
    header_rule_y_mm: float
    header_rule_height_mm: float
    footer_rule_y_mm: float
    footer_rule_height_mm: float


@dataclass(frozen=True)
class SentinelTheme:
    """Direct-PDF representation of the Sentinel design contract."""

    palette: SentinelPalette
    fonts: SentinelFonts
    text: SentinelTextScale
    layout: SentinelLayoutScale

    def sans_style(
        self,
        *,
        size_pt: float,
        color: PdfColor,
        bold: bool = False,
        char_spacing_mm: float = 0.0,
    ) -> TextStyle:
        return TextStyle(
            family=self.fonts.sans,
            size_pt=size_pt,
            style="B" if bold else "",
            color=color,
            char_spacing_mm=char_spacing_mm,
        )

    def mono_style(
        self,
        *,
        size_pt: float,
        color: PdfColor,
        bold: bool = False,
        char_spacing_mm: float = 0.0,
    ) -> TextStyle:
        return TextStyle(
            family=self.fonts.mono,
            size_pt=size_pt,
            style="B" if bold else "",
            color=color,
            char_spacing_mm=char_spacing_mm,
        )

    def symbol_style(self, *, size_pt: float, color: PdfColor) -> TextStyle:
        return TextStyle(family=self.fonts.symbols, size_pt=size_pt, color=color)


SENTINEL_THEME = SentinelTheme(
    palette=SentinelPalette(
        primary=PdfColor(242, 162, 13),
        background=PdfColor(248, 247, 245),
        border=PdfColor(232, 223, 206),
        text_main=PdfColor(28, 23, 13),
        text_secondary=PdfColor(156, 127, 73),
        black=PdfColor(0, 0, 0),
        white=PdfColor(255, 255, 255),
        warning_fill=PdfColor(255, 248, 235),
        line_fill=PdfColor(250, 248, 244),
        grid_line=PdfColor(229, 231, 235),
    ),
    fonts=SentinelFonts(
        sans=PUBLIC_SANS_FAMILY,
        mono=ROBOTO_MONO_FAMILY,
        symbols=MATERIAL_SYMBOLS_FAMILY,
    ),
    text=SentinelTextScale(
        top_strip_pt=6.75,
        top_strip_min_pt=5.6,
        header_title_pt=22.5,
        header_title_min_pt=16.0,
        header_title_wrapped_pt=14.6,
        header_title_wrapped_min_pt=11.6,
        header_subtitle_pt=9.0,
        header_subtitle_min_pt=7.0,
        header_meta_pt=6.8,
        header_meta_min_pt=5.0,
        footer_pt=6.2,
        footer_min_pt=4.8,
    ),
    layout=SentinelLayoutScale(
        page_width_mm=210.0,
        page_height_mm=297.0,
        content_x_mm=10.5,
        content_width_mm=189.0,
        top_strip_height_mm=7.8,
        top_strip_rule_height_mm=0.85,
        header_rule_y_mm=27.2,
        header_rule_height_mm=0.65,
        footer_rule_y_mm=284.0,
        footer_rule_height_mm=0.55,
    ),
)


__all__ = [
    "SENTINEL_THEME",
    "SentinelFonts",
    "SentinelLayoutScale",
    "SentinelPalette",
    "SentinelTextScale",
    "SentinelTheme",
]
