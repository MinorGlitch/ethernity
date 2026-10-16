"""Drawing and text measurement for direct PDF rendering through `fpdf2`."""

from __future__ import annotations

from collections.abc import Set
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Protocol, cast

from fontTools.pens.boundsPen import BoundsPen
from fpdf import FPDF
from fpdf.fonts import TTFFont

from ethernity.render.direct_pdf.types import (
    FontStyle,
    PdfColor,
    PdfRect,
    TextInkMetrics,
    TextStyle,
)
from ethernity.render.types import RenderTextMetadata

_POINT_TO_MM = 25.4 / 72.0


class _PdfContentStream(Protocol):
    def _out(self, value: str) -> None: ...


class PdfSurface(Protocol):
    """Minimal drawing and measurement interface for direct PDF rendering."""

    def add_page(self) -> None:
        """Append a page to the output document."""

    def set_creation_date(self, value: datetime) -> None:
        """Set deterministic PDF creation metadata before pages are emitted."""

    def register_ttf_font(self, family: str, path: str | Path, *, style: FontStyle = "") -> None:
        """Register a TrueType/OpenType font for later measurement and painting."""

    def measure_text_width(self, text: str, style: TextStyle) -> float:
        """Return the width of text in millimeters for the supplied style."""

    def line_height(self, style: TextStyle, *, multiplier: float = 1.2) -> float:
        """Return a default line height in millimeters for the supplied style."""

    def text_ink_metrics(self, text: str, style: TextStyle) -> TextInkMetrics:
        """Return glyph ink extents relative to the baseline in millimeters."""

    def draw_text(self, x_mm: float, baseline_y_mm: float, text: str, style: TextStyle) -> None:
        """Draw text at a PDF baseline coordinate."""

    def begin_text_metadata(self, metadata: RenderTextMetadata) -> None:
        """Mark a recovery value so extracted fallback text excludes secret data."""

    def end_text_metadata(self) -> None:
        """Finish a marked recovery value."""

    def draw_rect(
        self,
        rect: PdfRect,
        *,
        stroke: PdfColor | None = None,
        fill: PdfColor | None = None,
        line_width_mm: float = 0.2,
    ) -> None:
        """Draw a stroked and/or filled rectangle."""

    def draw_rounded_rect(
        self,
        rect: PdfRect,
        *,
        corner_radius_mm: float,
        stroke: PdfColor | None = None,
        fill: PdfColor | None = None,
        line_width_mm: float = 0.2,
    ) -> None:
        """Draw a stroked and/or filled rounded rectangle."""

    def draw_ellipse(
        self,
        rect: PdfRect,
        *,
        stroke: PdfColor | None = None,
        fill: PdfColor | None = None,
        line_width_mm: float = 0.2,
    ) -> None:
        """Draw a stroked and/or filled ellipse bounded by a rectangle."""

    def draw_line(
        self,
        start_x_mm: float,
        start_y_mm: float,
        end_x_mm: float,
        end_y_mm: float,
        *,
        color: PdfColor,
        line_width_mm: float = 0.2,
    ) -> None:
        """Draw a straight line segment."""

    def draw_image_bytes(self, image: bytes, rect: PdfRect, *, image_type: str = "") -> None:
        """Draw an encoded image byte payload into a rectangle."""

    def output(self, path: str | Path) -> None:
        """Write the PDF to disk."""


class FpdfSurface:
    """`PdfSurface` implementation backed by `fpdf2`."""

    def __init__(self, *, page_width_mm: float, page_height_mm: float) -> None:
        self._pdf = FPDF(unit="mm", format=(page_width_mm, page_height_mm))
        self._pdf.set_auto_page_break(False)
        self._registered_fonts: set[tuple[str, FontStyle]] = set()
        self._glyph_bounds: dict[tuple[str, str], tuple[float, float]] = {}

    def add_page(self) -> None:
        self._pdf.add_page()

    def set_creation_date(self, value: datetime) -> None:
        self._pdf.set_creation_date(value)

    def register_ttf_font(self, family: str, path: str | Path, *, style: FontStyle = "") -> None:
        font_path = Path(path)
        if not font_path.is_file():
            raise FileNotFoundError(font_path)
        # fpdf2 reserves the standard PDF family names for unembedded fonts.
        # Keep template names stable while registering explicit font programs.
        self._pdf.add_font(f"embedded-{family}", style, str(font_path))
        self._registered_fonts.add((family, style))

    def measure_text_width(self, text: str, style: TextStyle) -> float:
        self._set_text_style(style)
        return float(self._pdf.get_string_width(text))

    def line_height(self, style: TextStyle, *, multiplier: float = 1.2) -> float:
        if multiplier <= 0:
            raise ValueError("multiplier must be positive")
        return style.size_pt * _POINT_TO_MM * multiplier

    def text_ink_metrics(self, text: str, style: TextStyle) -> TextInkMetrics:
        self._set_text_style(style)
        if not text.strip():
            return TextInkMetrics(0.0, 0.0)
        font = self._pdf.current_font
        if isinstance(font, TTFFont) and style.family.lower() not in {
            "helvetica",
            "courier",
            "times",
        }:
            glyph_set = font.ttfont.getGlyphSet()
            bottom, top = 0.0, 0.0
            for character in set(text):
                glyph_name = font.cmap.get(ord(character), ".notdef")
                key = (font.fontkey, glyph_name)
                if key not in self._glyph_bounds:
                    pen = BoundsPen(glyph_set)
                    glyph_set[glyph_name].draw(pen)
                    self._glyph_bounds[key] = (
                        (pen.bounds[1], pen.bounds[3]) if pen.bounds else (0.0, 0.0)
                    )
                glyph_bottom, glyph_top = self._glyph_bounds[key]
                bottom = min(bottom, glyph_bottom)
                top = max(top, glyph_top)
            scale = style.size_pt * _POINT_TO_MM / font.ttfont["head"].unitsPerEm
            return TextInkMetrics(top * scale, -bottom * scale)

        # Preserve the template's standard-family line boxes when embedding their
        # replacements. These extents include accented capitals and descenders.
        ascent, descent = _core_font_extents(style.family)
        scale = style.size_pt * _POINT_TO_MM / 1000.0
        return TextInkMetrics(ascent * scale, descent * scale)

    def draw_text(self, x_mm: float, baseline_y_mm: float, text: str, style: TextStyle) -> None:
        self._set_text_style(style)
        self._set_text_color(style.color)
        self._pdf.text(x=x_mm, y=baseline_y_mm, text=text)

    def begin_text_metadata(self, metadata: RenderTextMetadata) -> None:
        # Marked-content tags carry structure without changing page appearance.
        cast(_PdfContentStream, self._pdf)._out(f"/{metadata.role} BMC")

    def end_text_metadata(self) -> None:
        cast(_PdfContentStream, self._pdf)._out("EMC")

    def draw_rect(
        self,
        rect: PdfRect,
        *,
        stroke: PdfColor | None = None,
        fill: PdfColor | None = None,
        line_width_mm: float = 0.2,
    ) -> None:
        if stroke is None and fill is None:
            raise ValueError("stroke or fill is required")
        if line_width_mm <= 0:
            raise ValueError("line_width_mm must be positive")
        style = _rect_style(stroke=stroke, fill=fill)
        self._pdf.set_line_width(line_width_mm)
        if stroke is not None:
            self._set_draw_color(stroke)
        if fill is not None:
            self._set_fill_color(fill)
        self._pdf.rect(
            x=rect.x_mm,
            y=rect.y_mm,
            w=rect.width_mm,
            h=rect.height_mm,
            style=style,
        )

    def draw_rounded_rect(
        self,
        rect: PdfRect,
        *,
        corner_radius_mm: float,
        stroke: PdfColor | None = None,
        fill: PdfColor | None = None,
        line_width_mm: float = 0.2,
    ) -> None:
        if stroke is None and fill is None:
            raise ValueError("stroke or fill is required")
        if line_width_mm <= 0:
            raise ValueError("line_width_mm must be positive")
        if corner_radius_mm <= 0:
            raise ValueError("corner_radius_mm must be positive")
        style = _rect_style(stroke=stroke, fill=fill)
        self._pdf.set_line_width(line_width_mm)
        if stroke is not None:
            self._set_draw_color(stroke)
        if fill is not None:
            self._set_fill_color(fill)
        self._pdf.rect(
            x=rect.x_mm,
            y=rect.y_mm,
            w=rect.width_mm,
            h=rect.height_mm,
            style=style,
            round_corners=True,
            corner_radius=corner_radius_mm,
        )

    def draw_ellipse(
        self,
        rect: PdfRect,
        *,
        stroke: PdfColor | None = None,
        fill: PdfColor | None = None,
        line_width_mm: float = 0.2,
    ) -> None:
        if stroke is None and fill is None:
            raise ValueError("stroke or fill is required")
        if line_width_mm <= 0:
            raise ValueError("line_width_mm must be positive")
        style = _rect_style(stroke=stroke, fill=fill)
        self._pdf.set_line_width(line_width_mm)
        if stroke is not None:
            self._set_draw_color(stroke)
        if fill is not None:
            self._set_fill_color(fill)
        self._pdf.ellipse(
            x=rect.x_mm,
            y=rect.y_mm,
            w=rect.width_mm,
            h=rect.height_mm,
            style=style,
        )

    def draw_line(
        self,
        start_x_mm: float,
        start_y_mm: float,
        end_x_mm: float,
        end_y_mm: float,
        *,
        color: PdfColor,
        line_width_mm: float = 0.2,
    ) -> None:
        if line_width_mm <= 0:
            raise ValueError("line_width_mm must be positive")
        self._pdf.set_line_width(line_width_mm)
        self._set_draw_color(color)
        self._pdf.line(start_x_mm, start_y_mm, end_x_mm, end_y_mm)

    def draw_image_bytes(self, image: bytes, rect: PdfRect, *, image_type: str = "") -> None:
        if not image:
            raise ValueError("image must be non-empty")
        _ = image_type
        self._pdf.image(
            BytesIO(image),
            x=rect.x_mm,
            y=rect.y_mm,
            w=rect.width_mm,
            h=rect.height_mm,
        )

    def output(self, path: str | Path) -> None:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._pdf.output(str(output_path))

    @property
    def registered_fonts(self) -> Set[tuple[str, FontStyle]]:
        return frozenset(self._registered_fonts)

    def _set_text_style(self, style: TextStyle) -> None:
        family = (
            f"embedded-{style.family}"
            if (style.family, style.style) in self._registered_fonts
            else style.family
        )
        self._pdf.set_font(family, style=style.style, size=cast(int, style.size_pt))
        self._pdf.set_char_spacing(style.char_spacing_pt)

    def _set_text_color(self, color: PdfColor) -> None:
        self._pdf.set_text_color(color.red, color.green, color.blue)

    def _set_draw_color(self, color: PdfColor) -> None:
        self._pdf.set_draw_color(color.red, color.green, color.blue)

    def _set_fill_color(self, color: PdfColor) -> None:
        self._pdf.set_fill_color(color.red, color.green, color.blue)


def _rect_style(*, stroke: PdfColor | None, fill: PdfColor | None) -> str:
    if stroke is not None and fill is not None:
        return "DF"
    if fill is not None:
        return "F"
    return "D"


def _core_font_extents(family: str) -> tuple[int, int]:
    normalized = family.lower()
    if normalized == "courier":
        return 805, 250
    if normalized == "times":
        return 935, 218
    if normalized == "symbol":
        return 1010, 293
    if normalized == "zapfdingbats":
        return 820, 143
    return 962, 228
