"""A thin direct-PDF surface over `fpdf2`.

The surface is deliberately small: layout code should measure and paint through this API instead
of reaching into `FPDF` directly. That keeps the renderer testable and leaves room to swap the
backend if the feasibility spike proves `fpdf2` insufficient.
"""

from __future__ import annotations

from collections.abc import Set
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Protocol, cast

from fpdf import FPDF

from ethernity.render.direct_pdf.types import FontStyle, PdfColor, PdfRect, TextStyle

_POINT_TO_MM = 25.4 / 72.0


class PdfSurface(Protocol):
    """Minimal drawing and measurement boundary for direct PDF rendering."""

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

    def draw_text(self, x_mm: float, baseline_y_mm: float, text: str, style: TextStyle) -> None:
        """Draw text at a PDF baseline coordinate."""

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

    def add_page(self) -> None:
        self._pdf.add_page()

    def set_creation_date(self, value: datetime) -> None:
        self._pdf.set_creation_date(value)

    def register_ttf_font(self, family: str, path: str | Path, *, style: FontStyle = "") -> None:
        font_path = Path(path)
        if not font_path.is_file():
            raise FileNotFoundError(font_path)
        self._pdf.add_font(family, style, str(font_path))
        self._registered_fonts.add((family, style))

    def measure_text_width(self, text: str, style: TextStyle) -> float:
        self._set_text_style(style)
        return float(self._pdf.get_string_width(text))

    def line_height(self, style: TextStyle, *, multiplier: float = 1.2) -> float:
        if multiplier <= 0:
            raise ValueError("multiplier must be positive")
        return style.size_pt * _POINT_TO_MM * multiplier

    def draw_text(self, x_mm: float, baseline_y_mm: float, text: str, style: TextStyle) -> None:
        self._set_text_style(style)
        self._set_text_color(style.color)
        self._pdf.text(x=x_mm, y=baseline_y_mm, text=text)

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
        self._pdf.set_font(style.family, style=style.style, size=cast(int, style.size_pt))
        self._pdf.set_char_spacing(style.char_spacing_mm)

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
